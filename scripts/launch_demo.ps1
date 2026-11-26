[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$NoBrowser,
    [switch]$Gpu,
    [switch]$Cpu
)

# 画板演示的一键启动：检查环境 -> 缺包才装 -> 起 Streamlit -> 开浏览器。
# 与工作台不同，画板在当前窗口前台运行：窗口关了就停，避免找不到进程。
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Root = Split-Path -Parent $PSScriptRoot
# PaddleX 默认缓存到 %USERPROFILE%\.paddlex；用户名含中文时 C++ 推理会读不到
# inference.json（parse error）。把缓存固定到仓库的 ASCII 路径，避免这个坑。
if (-not $env:PADDLE_PDX_CACHE_HOME) {
    $env:PADDLE_PDX_CACHE_HOME = Join-Path $Root '.paddlex'
}
$CpuPython = Join-Path $Root '.venv\Scripts\python.exe'
$GpuPython = Join-Path $Root '.venv\gpu-venv\Scripts\python.exe'
$VenvPython = $CpuPython
$DemoApp = Join-Path $Root 'demo\app.py'
$DemoRequirements = Join-Path $Root 'demo\requirements-demo.txt'
$Url = "http://127.0.0.1:$Port"

function Write-Line {
    param([string]$Text, [string]$Level = 'info')
    $color = switch ($Level) {
        'ok' { 'Green' }
        'warn' { 'Yellow' }
        'error' { 'Red' }
        default { 'Gray' }
    }
    Write-Host "    $Text" -ForegroundColor $color
}

function Write-Step {
    param([string]$Text)
    Write-Host ''
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Stop-WithHint {
    param([string]$Message, [string]$Hint)
    Write-Line $Message 'error'
    if ($Hint) { Write-Line $Hint 'warn' }
    exit 1
}

# 用默认浏览器打开地址。不用 Start-Process：环境里同时存在只有大小写不同的同名变量
# （代理软件常这么设，例如 HTTPS_PROXY 与 https_proxy）时，PowerShell 5.1 的
# Start-Process 会抛"已添加项。字典中的关键字..."。.NET 的 Process.Start 走 ShellExecute，
# 不读那个环境字典。返回 $true/$false，让调用方决定要不要打印"已打开"。
function Open-Url {
    param([string]$TargetUrl)
    try {
        $opened = [System.Diagnostics.Process]::Start($TargetUrl)
        if ($opened) { $opened.Dispose() }
        return $true
    } catch {
        Write-Line "没能自动打开浏览器：$($_.Exception.Message)" 'warn'
        Write-Line "请自己复制这个地址：$TargetUrl" 'info'
        return $false
    }
}

function Test-DemoHealthy {
    try {
        $response = Invoke-WebRequest -Uri "$Url/healthz" -TimeoutSec 3 -UseBasicParsing
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

# 注意：这里只能用 find_spec 探测。streamlit_drawable_canvas 在脱离 Streamlit
# 运行时的裸 import 下会抛 asset_dir 异常，真 import 会把好环境误判成缺包。
function Test-DemoDeps {
    $probe = Join-Path $Root '.venv\probe_demo_deps.py'
    $lines = @(
        'import importlib.util, sys',
        'missing = [m for m in ("streamlit", "streamlit_drawable_canvas", "openai", "dotenv") if importlib.util.find_spec(m) is None]',
        'print("; ".join(missing))',
        'sys.exit(1 if missing else 0)'
    )
    Set-Content -LiteralPath $probe -Value ($lines -join "`r`n") -Encoding ASCII
    try {
        $output = & $VenvPython $probe 2>&1
        return [pscustomobject]@{ Ok = ($LASTEXITCODE -eq 0); Missing = "$output" }
    } finally {
        Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue
    }
}

Write-Step '检查虚拟环境'
# 本机默认用 GPU；找不到 GPU 环境时自动退回 CPU。显式 -Cpu 可强制 CPU，
# 显式 -Gpu 时若环境缺失则直接报错，避免“以为在用 GPU”却悄悄跑了 CPU。
$WantGpu = -not $Cpu
if ($Gpu) { $WantGpu = $true }
$useGpu = $false
if ($WantGpu -and (Test-Path -LiteralPath $GpuPython)) {
    $VenvPython = $GpuPython
    $env:RECOGNIZER_DEVICE = 'gpu:0'
    $useGpu = $true
    Write-Line '使用 GPU 环境（RECOGNIZER_DEVICE=gpu:0）' 'ok'
} elseif ($Gpu) {
    Stop-WithHint '明确指定了 -Gpu，但没有找到 .venv\gpu-venv。' `
        '请按 README 6.4 建好 GPU 环境；或改用 -Cpu 启动。'
} else {
    $VenvPython = $CpuPython
    $env:RECOGNIZER_DEVICE = 'cpu'
    if ($WantGpu) {
        Write-Line '没有找到 .venv\gpu-venv，自动退回 CPU。' 'warn'
    } else {
        Write-Line '按 -Cpu 使用 CPU 环境。' 'ok'
    }
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Stop-WithHint '没有找到 .venv 虚拟环境，画板需要先装好项目环境。' `
        '请先双击 启动工作台.bat 选 [2] 准备并启动，它会建好 .venv。'
}
if (-not (Test-Path -LiteralPath $DemoApp)) {
    Stop-WithHint '没有找到 demo\app.py。' '画板演示在新版本代码里，请先 git pull 同步仓库。'
}
Write-Line '虚拟环境就绪' 'ok'

# 本机若已准备 UniMERNet 权重则优先使用：同一份 12 样本真值上实测 8/12，
# 高于 PP-FormulaNet-L 的 5/12。用户显式设置 RECOGNIZER_MODEL 时不覆盖。
if (-not $env:RECOGNIZER_MODEL) {
    $UniDir = Join-Path $Root 'models\UniMERNet'
    if (Test-Path -LiteralPath (Join-Path $UniDir 'inference.json')) {
        $env:RECOGNIZER_MODEL = 'UniMERNet'
        if (-not $env:RECOGNIZER_MODEL_DIR) { $env:RECOGNIZER_MODEL_DIR = $UniDir }
        Write-Line '识别模型：UniMERNet（实测更准；设 RECOGNIZER_MODEL 可切换）' 'ok'
    }
}

Write-Step '检查画板依赖（streamlit + drawable-canvas）'
$deps = Test-DemoDeps
if (-not $deps.Ok) {
    if ($useGpu) {
        Write-Line "GPU 环境缺少依赖：$($deps.Missing)，安装 demo/requirements-demo.txt" 'warn'
    } else {
        Write-Line "缺少依赖：$($deps.Missing)，开始安装 demo/requirements-demo.txt" 'warn'
    }
    & $VenvPython -m pip install --disable-pip-version-check -r $DemoRequirements
    if ($LASTEXITCODE -ne 0) {
        Stop-WithHint '画板依赖安装失败。' '可手动查看上方的 pip 报错；GPU 环境还需确认 paddlepaddle-gpu 未被覆盖。'
    }
    $deps = Test-DemoDeps
    if (-not $deps.Ok) {
        Stop-WithHint "装完仍缺：$($deps.Missing)" '请检查 pip 输出里的报错。'
    }
}
Write-Line '画板依赖就绪' 'ok'

if (Test-DemoHealthy) {
    Write-Step '画板已经在运行'
    Write-Line "地址 $Url，无需重复启动" 'ok'
    if (-not $NoBrowser) { $null = Open-Url $Url }
    exit 0
}

function Test-PortFree {
    param([int]$PortNumber)
    # 不用 TcpListener 的 Start()/Stop() 来判断端口占用：那种判据依赖
    # Windows 的端口重用语义（.NET 的 TcpListener.ExclusiveAddressUse 默认为 False，
    # 不会设 SO_EXCLUSIVEADDRUSE），当占用方自己也设了 SO_REUSEADDR 时，
    # 探测方仍可能绑成功，于是把已被占用的端口报成"空闲"，
    # 随后 Streamlit 自己 bind 失败，用户只看到一句"启动失败"。
    # 直接主动连一次更可靠：能连上就说明确实有人在监听。
    # 与 scripts/launch.ps1 里的同名函数保持一致——那边修过这个问题，这边曾漏改。
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connect = $client.BeginConnect([System.Net.IPAddress]::Loopback, $PortNumber, $null, $null)
        if ($connect.AsyncWaitHandle.WaitOne(300, $false) -and $client.Connected) {
            return $false   # 有人在监听 => 端口不空闲
        }
        return $true
    } catch {
        return $true
    } finally {
        try { $client.Close() } catch { }
    }
}

Write-Step '检查端口'
if (Test-PortFree -PortNumber $Port) {
    Write-Line "端口 $Port 可用" 'ok'
} else {
    Stop-WithHint "端口 $Port 被别的程序占用，且不是画板服务。" `
        "可以换一个端口：.\scripts\launch_demo.ps1 -Port $($Port + 1)"
}

Write-Step '启动画板（前台运行）'
# 不用 Start-Process：环境里同时存在只有大小写不同的同名变量（代理软件常这么设，
# 例如 HTTPS_PROXY 与 https_proxy）时，PowerShell 5.1 的 Start-Process 会抛
# "已添加项。字典中的关键字..."。直接用 .NET 的 Process.Start 不读环境字典。
# UseShellExecute=$false + CreateNoWindow=$false 等价于原来的 -NoNewWindow：
# 子进程沿用当前控制台，Streamlit 的输出照常打在这个窗口，Ctrl+C 也能停。
$demoInfo = New-Object System.Diagnostics.ProcessStartInfo
$demoInfo.FileName = $VenvPython
$demoInfo.Arguments = '-m streamlit run demo/app.py --server.headless true --server.port ' + $Port + ' --server.address 127.0.0.1'
$demoInfo.WorkingDirectory = $Root
$demoInfo.UseShellExecute = $false
$demoInfo.CreateNoWindow = $false
$server = [System.Diagnostics.Process]::Start($demoInfo)

$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    if ($server.HasExited) { break }
    if (Test-DemoHealthy) { $ready = $true; break }
    Start-Sleep -Milliseconds 750
}
if (-not $ready) {
    Stop-WithHint '画板在 30 秒内没有就绪。' '请看本窗口上方的 Streamlit 报错；也可以手动运行 ./.venv/Scripts/python.exe -m streamlit run demo/app.py'
}

Write-Line "画板已就绪：$Url" 'ok'
if (-not $NoBrowser) { $null = Open-Url $Url }
Write-Line '在左侧画板写字，停笔约 1 秒自动识别；第一次识别要加载本地模型，较慢属正常。'
Write-Line '本窗口开着画板才在运行，关闭窗口或按 Ctrl+C 即停止。' 'warn'

Wait-Process -Id $server.Id
Write-Line '画板已停止。' 'ok'
