<#
.SYNOPSIS
    Hand2LaTeX 一键准备 + 一键启动。

.DESCRIPTION
    这个脚本把仓库变成"双击就能用"的状态：
      1. 找到或创建 Python 虚拟环境（必须是 3.10 / 3.11 / 3.12）
      2. 安装 pip 依赖与 npm 依赖
      3. 准备 .env，并检查 Tectonic、本地公式模型是否就位
      4. 运行接口契约自检 test_recognizer.py
      5. 启动工作台并打开浏览器

    每一步都是幂等的：已经就绪的部分会跳过，可以放心反复运行。
    只想看当前状态、不想装任何东西时，用 -CheckOnly。
    不带任何参数、直接双击 启动工作台.bat 时，会进入中文菜单（-Menu）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\launch.ps1 -CheckOnly
    只体检，不改动任何东西。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\launch.ps1
    首次完整安装并启动。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\launch.ps1 -Restart
    改完代码后重启服务。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\launch.ps1 -Lite
    只装跑通网页所需的最小依赖，跳过体积很大的 paddle / torch。
#>
[CmdletBinding()]
param(
    [switch]$Menu,
    [switch]$CheckOnly,
    [switch]$Restart,
    [switch]$Stop,
    [switch]$Status,
    [switch]$NoBrowser,
    [switch]$Lite,
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

# 本脚本大量调用外部命令（python / pip / npm / tectonic）。外部命令往 stderr 写警告是
# 正常行为，用 Stop 会把警告当成终止错误，所以统一用 Continue，并显式检查退出码。
$ErrorActionPreference = 'Continue'

# 让子进程输出也走 UTF-8，避免中文日志乱码。
$env:PYTHONIOENCODING = 'utf-8'

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$VenvRoot = Join-Path $Root '.venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$LogFile = Join-Path $VenvRoot 'workbench.log'
$PidFile = Join-Path $VenvRoot 'workbench.pid'
$Url = "http://127.0.0.1:$Port/"

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Line {
    param(
        [string]$Text,
        [ValidateSet('ok', 'warn', 'bad', 'info')] [string]$Level = 'info'
    )
    $color = switch ($Level) {
        'ok' { 'Green' }
        'warn' { 'Yellow' }
        'bad' { 'Red' }
        default { 'Gray' }
    }
    Write-Host "    $Text" -ForegroundColor $color
}

function Write-Block {
    param([string]$Text)
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line.Trim()) { Write-Host "      $line" -ForegroundColor DarkGray }
    }
}

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# 运行外部命令并拿到退出码 + 合并输出。参数一律用不含空格的相对文件名或 -- 开关，
# 绕开 Windows 命令行引号问题。
function Invoke-Captured {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $Root
    )
    $outPath = [System.IO.Path]::GetTempFileName()
    $errPath = [System.IO.Path]::GetTempFileName()
    try {
        $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
            -WorkingDirectory $WorkingDirectory -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $outPath -RedirectStandardError $errPath
        if (-not $process) {
            return [pscustomobject]@{ ExitCode = 1; Output = "无法启动 $FilePath" }
        }
        $text = ''
        foreach ($file in @($outPath, $errPath)) {
            if (Test-Path -LiteralPath $file) {
                $text += [System.IO.File]::ReadAllText($file, [System.Text.Encoding]::UTF8)
                $text += [Environment]::NewLine
            }
        }
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = $text.Trim() }
    } catch {
        return [pscustomobject]@{ ExitCode = 1; Output = $_.Exception.Message }
    } finally {
        Remove-Item -LiteralPath $outPath, $errPath -Force -ErrorAction SilentlyContinue
    }
}

# 用 python --version 判断版本；只接受 3.10 - 3.12（PaddlePaddle 不支持 3.13）。
function Get-PythonVersionText {
    param([string]$Command, [string[]]$Prefix = @())
    $arguments = @($Prefix) + @('--version')
    $result = Invoke-Captured -FilePath $Command -Arguments $arguments
    if ($result.Output -match 'Python (\d+)\.(\d+)') {
        return [pscustomobject]@{
            Version = "$($Matches[1]).$($Matches[2])"
            Minor = [int]$Matches[2]
            Found = $true
        }
    }
    return [pscustomobject]@{ Version = ''; Minor = -1; Found = $false }
}

function Test-PythonEntry {
    param([string]$Command, [string[]]$Prefix = @())
    $info = Get-PythonVersionText -Command $Command -Prefix $Prefix
    return [pscustomobject]@{
        Command = $Command
        Prefix = @($Prefix)
        Version = $info.Version
        Supported = ($info.Found -and $info.Minor -ge 10 -and $info.Minor -le 12)
    }
}

# 逐个探测系统 Python，返回第一个受支持的调用方式（可能是 py -3.12 这种带前缀的形式）。
function Resolve-SystemPython {
    $entries = @()
    $entries += , (Test-PythonEntry -Command 'python')
    foreach ($flag in @('-3.12', '-3.11', '-3.10')) {
        $entries += , (Test-PythonEntry -Command 'py' -Prefix @($flag))
    }
    $entries += , (Test-PythonEntry -Command 'python3')

    foreach ($entry in $entries) {
        if (-not $entry.Version) { continue }
        if ($entry.Supported) { return $entry }
        Write-Line "跳过 $($entry.Command) $($entry.Prefix -join ' ')（Python $($entry.Version)）：本项目需要 3.10 - 3.12" 'warn'
    }
    return $null
}

function Get-RunningServerProcess {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $rawPid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $rawPid) { return $null }
    $processId = 0
    if (-not [int]::TryParse(([string]$rawPid).Trim(), [ref] $processId)) { return $null }

    # PID 会被 Windows 复用：机器重启后 pid 文件可能指向别人的进程。
    # 因此还要确认命令行里确实有 workbench.app，才把它当成工作台服务。
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if (-not $process -or $process.HasExited) { return $null }
    $commandLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue).CommandLine
    if (-not $commandLine -or $commandLine -notmatch 'workbench\.app') {
        Write-Line "pid 文件指向的进程（PID $processId）不是工作台服务，忽略它" 'warn'
        return $null
    }
    return $process
}

function Stop-RunningServer {
    param([switch]$Quiet)
    $process = Get-RunningServerProcess
    if ($process) {
        Stop-Process -Id $process.Id -Force
        if (-not $Quiet) { Write-Line "已停止工作台服务（PID $($process.Id)）" 'ok' }
    } elseif (-not $Quiet) {
        Write-Line '没有正在运行的工作台服务' 'info'
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

function Test-HttpOk {
    param([string]$TargetUrl, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -Uri $TargetUrl -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-ForHttp {
    param(
        [System.Diagnostics.Process]$Process,
        [string]$TargetUrl,
        [int]$Seconds = 25
    )
    $attempts = [Math]::Ceiling($Seconds * 2)
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        if ($Process.HasExited) { return $false }
        if (Test-HttpOk $TargetUrl -TimeoutSec 3) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# 把探测代码写成临时脚本再运行，避免把带引号的 Python 代码传进命令行。
# -SpecOnly 只查包是否装了（find_spec，秒出）；默认是真 import（能发现装坏的情况）。
function Invoke-ImportProbe {
    param([string]$FileName, [string[]]$Modules, [switch]$SpecOnly)
    $lines = @('import sys', 'missing = []')
    if ($SpecOnly) {
        $lines += 'import importlib.util'
        foreach ($module in $Modules) {
            # 用单引号拼接，避免 PowerShell 把 "$module:" 当成带驱动名的变量。
            $lines += 'if importlib.util.find_spec("' + $module + '") is None:'
            $lines += '    missing.append("' + $module + '")'
        }
    } else {
        foreach ($module in $Modules) {
            $lines += 'try:'
            $lines += '    import ' + $module
            $lines += 'except Exception as error:'
            $lines += '    missing.append("' + $module + ' failed: " + repr(error))'
        }
    }
    $lines += 'if missing:'
    $lines += '    print("; ".join(missing))'
    $lines += '    sys.exit(1)'
    $lines += 'print("ok")'
    $path = Join-Path $VenvRoot $FileName
    Set-Content -LiteralPath $path -Value ($lines -join "`r`n") -Encoding UTF8
    try {
        $result = Invoke-Captured -FilePath $VenvPython -Arguments @($FileName) -WorkingDirectory $VenvRoot
        return [pscustomobject]@{ ExitCode = $result.ExitCode; Output = $result.Output }
    } finally {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}

# 只报告 .env 的状态，绝不打印密钥本身。
function Read-EnvValue {
    param([string]$Name)
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return $null }
    foreach ($line in (Get-Content -LiteralPath $envFile -Encoding UTF8)) {
        if ($line -match ('^\s*' + [regex]::Escape($Name) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Show-FailureLog {
    param([string]$LogPath)
    if (-not (Test-Path -LiteralPath $LogPath)) { return }
    Write-Line "日志末尾（$LogPath）：" 'bad'
    foreach ($line in (Get-Content -LiteralPath $LogPath -Tail 20 -Encoding UTF8)) {
        Write-Host "      $line" -ForegroundColor DarkGray
    }
}

function Stop-WithHint {
    param([string]$Message, [string]$Hint = '')
    Write-Line $Message 'bad'
    if ($Hint) { Write-Line $Hint 'info' }
    exit 1
}

function Test-PortFree {
    param([int]$PortNumber)
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $PortNumber)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        try { $listener.Stop() } catch { }
    }
}

function Show-StatusSummary {
    $process = Get-RunningServerProcess
    if ($process -and (Test-HttpOk $Url)) {
        Write-Line "工作台正在运行：PID $($process.Id)，地址 $Url" 'ok'
    } elseif ($process) {
        Write-Line "服务进程还在（PID $($process.Id)），但 $Url 没有响应，试试 -Restart" 'warn'
    } else {
        Write-Line '工作台未运行。启动：双击 启动工作台.bat' 'info'
    }
}

# 菜单只负责把选择翻译成参数，然后交给同一份脚本执行，避免逻辑分叉。
function Invoke-Menu {
    while ($true) {
        Write-Host ''
        Write-Host '==============================================' -ForegroundColor White
        Write-Host '   Hand2LaTeX 手写公式工作台 - 一键启动' -ForegroundColor White
        Write-Host '==============================================' -ForegroundColor White
        Write-Host '   [1] 体检        只检查环境，不安装不启动'
        Write-Host '   [2] 准备并启动  首次装环境 / 日常启动都用它'
        Write-Host '   [3] 重启服务    改完代码后用这个'
        Write-Host '   [4] 查看状态    看服务是否还在运行'
        Write-Host '   [5] 停止服务'
        Write-Host '   [0] 退出'
        Write-Host ''
        $choice = Read-Host '请输入 1-5 或 0'
        switch ($choice) {
            '1' { Invoke-MenuChild '-CheckOnly' }
            '2' { Invoke-MenuChild '' }
            '3' { Invoke-MenuChild '-Restart' }
            '4' { Show-StatusSummary }
            '5' { Stop-RunningServer }
            '0' { return }
            default { Write-Line '无效输入，请重新选择。' 'warn' }
        }
        Write-Host ''
        Read-Host '按回车返回菜单' | Out-Null
    }
}

function Invoke-MenuChild {
    param([string]$ArgumentLine)
    $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath)
    if ($ArgumentLine) { $arguments += ($ArgumentLine -split '\s+' | Where-Object { $_ }) }
    & powershell @arguments
}

# ---------------------------------------------------------------------------
# 菜单入口（双击 启动工作台.bat 走这里）
# ---------------------------------------------------------------------------
if ($Menu) {
    Invoke-Menu
    exit 0
}

# ---------------------------------------------------------------------------
# 快捷入口：查状态 / 停服务
# ---------------------------------------------------------------------------
if ($Status) {
    Show-StatusSummary
    exit 0
}

if ($Stop) {
    Stop-RunningServer
    exit 0
}

# ---------------------------------------------------------------------------
# 1. 虚拟环境
# ---------------------------------------------------------------------------
Write-Step '检查 Python 虚拟环境（要求 3.10 / 3.11 / 3.12）'
if (Test-Path -LiteralPath $VenvPython) {
    $venvInfo = Get-PythonVersionText -Command $VenvPython
    if (-not $venvInfo.Found) {
        Stop-WithHint '.venv 里的 python.exe 无法执行' '请删除 .venv 后重跑本脚本重建。'
    }
    if (-not ($venvInfo.Minor -ge 10 -and $venvInfo.Minor -le 12)) {
        Stop-WithHint "当前 .venv 是 Python $($venvInfo.Version)，PaddlePaddle 不支持它。" `
            '请删除 .venv，装好 Python 3.10 - 3.12 后重跑本脚本。'
    }
    Write-Line "已就绪：.venv（Python $($venvInfo.Version)）" 'ok'
} elseif ($CheckOnly) {
    Write-Line '缺少 .venv。体检模式不创建目录，去掉 -CheckOnly 会自动创建。' 'warn'
} else {
    $systemPython = Resolve-SystemPython
    if (-not $systemPython) {
        Stop-WithHint '找不到 Python 3.10 / 3.11 / 3.12。' `
            '安装其一后重跑：winget install Python.Python.3.12'
    }
    $shown = (@($systemPython.Command) + $systemPython.Prefix) -join ' '
    Write-Line "使用 $shown 创建 .venv（Python $($systemPython.Version)）……" 'info'
    $created = Invoke-Captured -FilePath $systemPython.Command `
        -Arguments (@($systemPython.Prefix) + @('-m', 'venv', '.venv'))
    if ($created.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        Write-Block $created.Output
        Stop-WithHint "虚拟环境创建失败（退出码 $($created.ExitCode)）" '请看上面的 Python 输出。'
    }
    Write-Line '.venv 创建完成' 'ok'
}

$venvReady = Test-Path -LiteralPath $VenvPython

# ---------------------------------------------------------------------------
# 2. 依赖
# ---------------------------------------------------------------------------
Write-Step '检查依赖'
$webDepsReady = $false
$paddleReady = $false
if ($venvReady) {
    $webProbe = Invoke-ImportProbe -FileName 'probe_web_deps.py' `
        -Modules @('fastapi', 'uvicorn', 'openai', 'dotenv', 'pydantic', 'multipart')
    $webDepsReady = ($webProbe.ExitCode -eq 0)
    if ($webDepsReady) {
        Write-Line '网页服务所需 Python 依赖已就绪' 'ok'
    } else {
        Write-Line "缺少网页依赖：$($webProbe.Output)" 'warn'
    }

    $paddleProbe = Invoke-ImportProbe -FileName 'probe_paddle.py' -Modules @('paddleocr') -SpecOnly
    $paddleReady = ($paddleProbe.ExitCode -eq 0)
    if ($paddleReady) {
        Write-Line '公式识别后端（paddleocr）已安装' 'ok'
    } elseif ($Lite) {
        Write-Line '-Lite 模式跳过 paddle，B 侧公式识别不可用' 'warn'
    } else {
        Write-Line 'paddleocr 未安装，公式识别（B 侧）会失败' 'warn'
    }
} else {
    Write-Line '虚拟环境不可用，跳过 Python 依赖检查' 'warn'
}

$frontendReady = Test-Path -LiteralPath (Join-Path $Root 'node_modules\vue\dist\vue.global.js')
if ($frontendReady) {
    Write-Line '前端依赖已就绪（node_modules\vue\dist）' 'ok'
} elseif (Test-Path -LiteralPath (Join-Path $Root 'workbench\static\vendor\vue\vue.global.js')) {
    # 安装包会随包带一份 vue.global.js，这样目标机器不装 Node.js 也能打开网页。
    $frontendReady = $true
    Write-Line '前端依赖已就绪（安装包自带副本 workbench\static\vendor\vue）' 'ok'
} else {
    Write-Line '缺少 vue.global.js，打开页面会报 "Vue is not defined"' 'warn'
}

$needsPythonInstall = $venvReady -and (-not $webDepsReady -or (-not $Lite -and -not $paddleReady))
$needsFrontendInstall = -not $frontendReady

if (-not $needsPythonInstall -and -not $needsFrontendInstall) {
    Write-Line '依赖齐全，无需安装' 'ok'
} elseif ($CheckOnly) {
    Write-Line '体检模式不安装。去掉 -CheckOnly 即可自动补齐依赖。' 'info'
} else {
    if ($needsPythonInstall) {
        $requirementNames = @('requirements.txt')
        if (-not $Lite -and -not $paddleReady) { $requirementNames += 'requirements-b.txt' }
        foreach ($name in $requirementNames) {
            Write-Line "pip install -r $name ……" 'info'
            Write-Line 'paddle / torch 体积较大，首次可能要十几分钟，请勿关闭窗口' 'info'
            Push-Location $Root
            & $VenvPython -m pip install --disable-pip-version-check -r $name
            $pipExit = $LASTEXITCODE
            Pop-Location
            if ($pipExit -ne 0) {
                Stop-WithHint "依赖安装失败（$name，退出码 $pipExit）" `
                    '可以先用 -Lite 只装网页依赖，或手动重试 pip install。'
            }
            Write-Line "$name 安装完成" 'ok'
        }
    }

    if ($needsFrontendInstall) {
        if (-not (Test-CommandAvailable 'npm')) {
            Stop-WithHint '找不到 npm，前端页面无法加载。' `
                '安装 Node.js 18+：winget install OpenJS.NodeJS.LTS，然后重跑本脚本。'
        }
        Write-Line 'npm install ……（前端只用静态资源，不需要打包构建）' 'info'
        Push-Location $Root
        & npm install --no-audit --no-fund
        $npmExit = $LASTEXITCODE
        Pop-Location
        if ($npmExit -ne 0) {
            Stop-WithHint "npm install 失败（退出码 $npmExit）" '前端依赖缺失时网页会白屏。'
        }
        Write-Line '前端依赖安装完成' 'ok'
    }
}

# ---------------------------------------------------------------------------
# 3. 配置与外部工具
# ---------------------------------------------------------------------------
Write-Step '检查配置与外部工具'
$envFile = Join-Path $Root '.env'
if (Test-Path -LiteralPath $envFile) {
    Write-Line '.env 已存在' 'ok'
    $apiKey = Read-EnvValue 'OPENAI_API_KEY'
    $model = Read-EnvValue 'OPENAI_MODEL'
    $baseUrl = Read-EnvValue 'OPENAI_BASE_URL'

    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        Write-Line 'OPENAI_API_KEY 还是空的：整页识别、上下文选择、修复建议都会失败' 'warn'
    } else {
        Write-Line "OPENAI_API_KEY 已配置（长度 $($apiKey.Length)，未显示内容）" 'ok'
    }
    if ([string]::IsNullOrWhiteSpace($model)) {
        Write-Line 'OPENAI_MODEL 未设置' 'warn'
    } else {
        Write-Line "OPENAI_MODEL = $model" 'ok'
    }
    if ([string]::IsNullOrWhiteSpace($baseUrl)) {
        Write-Line 'OPENAI_BASE_URL 未设置：将请求 OpenAI 官方接口（国内网络通常连不上）' 'warn'
    } else {
        Write-Line "OPENAI_BASE_URL = $baseUrl" 'ok'
    }
} elseif ($CheckOnly) {
    Write-Line '缺少 .env（体检不创建文件）。启动前请复制 .env.example 为 .env 并填写密钥。' 'warn'
} elseif (Test-Path -LiteralPath (Join-Path $Root '.env.example')) {
    Copy-Item -LiteralPath (Join-Path $Root '.env.example') -Destination $envFile
    Write-Line '已从 .env.example 创建 .env —— 请打开它填入 OPENAI_API_KEY（该文件已被 .gitignore 排除）' 'warn'
} else {
    Write-Line '仓库里既没有 .env 也没有 .env.example，无法配置 API。' 'bad'
}

$tectonicExe = Join-Path $Root 'tools\tectonic\tectonic.exe'
if (Test-Path -LiteralPath $tectonicExe) {
    $tectonicVersion = Invoke-Captured -FilePath $tectonicExe -Arguments @('--version')
    if ($tectonicVersion.ExitCode -eq 0) {
        $versionLine = ($tectonicVersion.Output -split "`r?`n" | Where-Object { $_ -match '\S' } |
            Select-Object -First 1)
        Write-Line "Tectonic 就绪：$versionLine" 'ok'
    } else {
        Write-Line 'tools\tectonic\tectonic.exe 存在但无法执行，整页 PDF 编译会失败。' 'warn'
    }
} else {
    Write-Line '缺少 tools\tectonic\tectonic.exe，整页中文 PDF 编译会失败（网页仍可识别和修正 LaTeX）。' 'warn'
    Write-Line '获取：tectonic-typesetting/tectonic 的 Releases 页下载 Windows 版，解压到 tools\tectonic\。' 'info'
}

$modelFound = $false
foreach ($candidate in @(
    @{ Name = 'UniMERNet'; MinMb = 1000 },
    @{ Name = 'PP-FormulaNet-L'; MinMb = 500 }
)) {
    $modelDir = Join-Path $Root "models\$($candidate.Name)"
    if (-not (Test-Path -LiteralPath $modelDir)) { continue }
    $modelBytes = (Get-ChildItem -LiteralPath $modelDir -Recurse -File -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    $modelMb = [Math]::Round(($modelBytes / 1MB), 0)
    if ($modelBytes -ge ($candidate.MinMb * 1MB)) {
        Write-Line "本地公式模型就绪：models\$($candidate.Name)（约 $modelMb MB）" 'ok'
    } else {
        Write-Line "models\$($candidate.Name) 只有 $modelMb MB，可能下载不完整。删除该目录后重跑会自动重下。" 'warn'
    }
    $modelFound = $true
    break
}
if (-not $modelFound) {
    Write-Line '缺少本地公式模型（models\UniMERNet 或 models\PP-FormulaNet-L）：B 侧会返回明确的失败候选（不会崩，但没有识别结果）。' 'warn'
    Write-Line '获取：装好 paddleocr 后首次运行自动下载，或在 .env 里设置 RECOGNIZER_MODEL_DIR 指向已有目录。' 'info'
}

# ---------------------------------------------------------------------------
# 4. 接口契约自检
# ---------------------------------------------------------------------------
Write-Step '运行接口契约自检 test_recognizer.py'
if (-not $venvReady) {
    Write-Line '虚拟环境不可用，跳过自检' 'warn'
} else {
    $selfTest = Invoke-Captured -FilePath $VenvPython -Arguments @('tests/test_recognizer.py')
    Write-Block $selfTest.Output
    if ($selfTest.ExitCode -ne 0) {
        Stop-WithHint "test_recognizer.py 未通过（退出码 $($selfTest.ExitCode)）" `
            '契约自检失败说明环境或接口有问题，先修它再启动服务。'
    }
    Write-Line 'test_recognizer.py 通过' 'ok'
}

if ($CheckOnly) {
    Write-Step '体检结束（-CheckOnly 未启动服务）'
    Write-Line '完整安装并启动：双击 启动工作台.bat，或运行不带 -CheckOnly 的本脚本。' 'info'
    exit 0
}

# ---------------------------------------------------------------------------
# 5. 启动服务
# ---------------------------------------------------------------------------
Write-Step '启动工作台'
if (-not $venvReady) {
    Stop-WithHint '虚拟环境不可用，无法启动服务。' '请先运行不带 -CheckOnly 的本脚本完成安装。'
}

$existing = Get-RunningServerProcess
if ($existing -and (Test-HttpOk $Url)) {
    if ($Restart) {
        Stop-RunningServer
        Start-Sleep -Seconds 1
    } else {
        Write-Line "工作台已在运行：PID $($existing.Id)，$Url（需要重启请用 -Restart）" 'ok'
        if (-not $NoBrowser) { Start-Process $Url }
        exit 0
    }
} elseif ($existing) {
    Write-Line "发现无响应的残留进程（PID $($existing.Id)），先清理" 'warn'
    Stop-RunningServer -Quiet
    Start-Sleep -Seconds 1
}

if (-not (Test-PortFree $Port)) {
    Stop-WithHint "端口 $Port 已被其它程序占用。" "换端口重试：.\scripts\launch.ps1 -Port 8010"
}

$server = Start-Process -FilePath $VenvPython `
    -ArgumentList @('-m', 'uvicorn', 'workbench.app:app', '--host', '127.0.0.1', '--port', "$Port") `
    -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $LogFile -RedirectStandardError "$LogFile.err"
if (-not $server) {
    Stop-WithHint '服务进程启动失败' "完整日志可看 $LogFile"
}
Set-Content -LiteralPath $PidFile -Value $server.Id -Encoding ASCII
Write-Line "服务进程 PID $($server.Id)，日志 .venv\workbench.log" 'info'

if (-not (Wait-ForHttp -Process $server -TargetUrl $Url -Seconds 25)) {
    Write-Line '启动失败：服务在 25 秒内没有响应。' 'bad'
    Show-FailureLog $LogFile
    Show-FailureLog "$LogFile.err"
    Stop-RunningServer -Quiet
    Stop-WithHint '请根据上面的日志排查。' '常见原因：依赖缺失、端口冲突、Tectonic 路径不对。'
}

Write-Line "工作台已就绪：$Url" 'ok'
if (-not $NoBrowser) {
    Start-Process $Url
    Write-Line '已在默认浏览器打开' 'info'
}
Write-Step '完成'
Write-Line '停止服务：双击 关闭工作台.bat，或运行 .\scripts\launch.ps1 -Stop' 'info'
Write-Line '查看状态：.\scripts\launch.ps1 -Status' 'info'
