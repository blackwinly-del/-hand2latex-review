<#
.SYNOPSIS
    把当前仓库打成可以发给别人用的 Windows 安装包。

.DESCRIPTION
    产出两样东西（都放在 dist\ 下）：
      1. Hand2LaTeX-<版本>-win64.zip   —— 绿色包：解压后双击 启动工作台.bat 就能用
      2. Hand2LaTeX-<版本>-win64-setup.exe —— 安装器（需要本机装了 Inno Setup 6，加 -BuildInstaller）

    打包做的事：
      - 按排除清单复制仓库（不带 .env、.venv、node_modules、models、artifacts、dist）
      - 把 vue.global.js 随包带上，这样目标机器不装 Node.js 也能打开网页
      - 写 BUILD_INFO.json（版本、提交号、打包时间），网页"系统状态"里会显示"来源：安装包"
      - 复制 安装说明.txt
      - 逐项核对打包结果（该在的在不在、不该带的有没有带进去），有问题就停下报错

    这个脚本只读仓库、只往 dist\ 写，不会改动源代码，也不会碰 .env。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
    只打 zip 绿色包。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -BuildInstaller
    打 zip，并在找到 Inno Setup 时顺便编出安装器。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -BuildInstaller -Iscc "D:\API\Inno Setup 6\ISCC.exe"
    Inno Setup 装在非默认目录、也没加进 PATH 时，直接指定 ISCC.exe。
#>
[CmdletBinding()]
param(
    [switch]$BuildInstaller,
    [switch]$KeepStaging,
    [string]$Iscc
)

$ErrorActionPreference = 'Stop'
# 日志里有中文：把控制台输出统一到 UTF-8，避免重定向到文件时变成乱码。
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$DistRoot = Join-Path $Root 'dist'
$StagingParent = Join-Path $DistRoot 'staging'

function Write-Step { param([string]$Text) Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok { param([string]$Text) Write-Host "    [ok] $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    [注意] $Text" -ForegroundColor Yellow }
function Write-Bad { param([string]$Text) Write-Host "    [失败] $Text" -ForegroundColor Red }

function Stop-WithMessage {
    param([string]$Text)
    Write-Bad $Text
    exit 1
}

# 排除清单（和 README 第十节的口径一致）：复制仓库时用它，报告未跟踪文件时也用它，
# 免得把本来就不会进包的东西说成"会被带进安装包"。
# /XD 排除目录（robocopy 里写目录名就是"任何层级都排除"），/XF 排除文件。
# tools 在 git 里被忽略，但安装包必须带 tectonic，所以不排除 tools。
$excludeDirs = @(
    '.git',
    '.qoder',
    '.venv',
    '.venv-check',
    'node_modules',
    'models',
    '.paddlex',
    'artifacts',
    'dist',
    '__pycache__',
    '.pytest_cache',
    '.ruff_cache',
    '.qoder-office-docx-locks'
)
$excludeFiles = @('.env', '*.pyc', '*.pyo', 'workbench.log', 'workbench.pid')

function Test-ExcludedPath {
    param([string]$RelativePath)
    $parts = $RelativePath -split '/'
    foreach ($part in $parts) { if ($excludeDirs -contains $part) { return $true } }
    $leaf = $parts[-1]
    # -like 对不含通配符的模式等同于相等比较，所以字面名和 *.pyc 这种都能一起处理。
    foreach ($pattern in $excludeFiles) {
        if ($leaf -like $pattern) { return $true }
    }
    return $false
}

# ---------------------------------------------------------------------------
# 1. 版本与提交号
# ---------------------------------------------------------------------------
Write-Step '读取版本信息'
$versionFile = Join-Path $Root 'workbench\version.py'
if (-not (Test-Path -LiteralPath $versionFile)) { Stop-WithMessage "找不到 $versionFile" }
$versionMatch = [regex]::Match((Get-Content -LiteralPath $versionFile -Raw), 'VERSION\s*=\s*"([^"]+)"')
if (-not $versionMatch.Success) { Stop-WithMessage 'workbench\version.py 里读不到 VERSION' }
$Version = $versionMatch.Groups[1].Value
Write-Ok "版本号 $Version（来自 workbench\version.py）"

$Commit = $null
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Push-Location $Root
    $Commit = (& git rev-parse --short HEAD 2>$null)
    # 分开看：已跟踪文件的改动会让"提交号对不上"，未跟踪文件只是会多带进包里。
    $dirtyTracked = (& git status --porcelain --untracked-files=no 2>$null)
    $untracked = (& git ls-files --others --exclude-standard 2>$null)
    Pop-Location
    if ($LASTEXITCODE -ne 0 -or -not $Commit) { $Commit = $null }
    if ($Commit) {
        Write-Ok "提交号 $Commit"
        if ($dirtyTracked) {
            Write-Warn '已跟踪的文件还有未提交的改动：安装包里会带上这些改动，但 BUILD_INFO 里的提交号对不上'
        }
        if ($untracked) {
            # 只报真的会进包的：排除清单里的目录/文件不会进包，说了反而误导。
            $bundled = @($untracked | Where-Object { -not (Test-ExcludedPath $_) })
            if ($bundled.Count -gt 0) {
                Write-Warn "有 $($bundled.Count) 个未跟踪文件（不在 git 里）也会被复制进安装包，例如：$($bundled[0])"
            }
        }
    }
} else {
    Write-Warn '找不到 git，BUILD_INFO.json 里不写提交号'
}

$PackageName = "Hand2LaTeX-$Version-win64"
$Staging = Join-Path $StagingParent $PackageName

# ---------------------------------------------------------------------------
# 2. 复制仓库（排除清单和 README 第十节的口径一致）
# ---------------------------------------------------------------------------
Write-Step "复制文件到临时目录 dist\staging\$PackageName"
if (Test-Path -LiteralPath $Staging) { Remove-Item -LiteralPath $Staging -Recurse -Force }
New-Item -ItemType Directory -Path $Staging -Force | Out-Null

$robocopyArgs = @($Root, $Staging, '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/R:1', '/W:1')
$robocopyArgs += '/XD'
$robocopyArgs += $excludeDirs
$robocopyArgs += '/XF'
$robocopyArgs += $excludeFiles
& robocopy @robocopyArgs | Out-Null
# robocopy 的退出码 0-7 都算成功（1 = 有文件被复制），8 及以上才是真出错。
if ($LASTEXITCODE -ge 8) { Stop-WithMessage "robocopy 复制失败（退出码 $LASTEXITCODE）" }
Write-Ok "复制完成（robocopy 退出码 $LASTEXITCODE）"

# ---------------------------------------------------------------------------
# 3. 随包带上 vue.global.js（目标机器可以不装 Node.js）
# ---------------------------------------------------------------------------
Write-Step '准备前端资源'
$vueSource = Join-Path $Root 'node_modules\vue\dist\vue.global.js'
$vueTargetDir = Join-Path $Staging 'workbench\static\vendor\vue'
if (-not (Test-Path -LiteralPath $vueSource)) {
    Stop-WithMessage "找不到 $vueSource：先运行 npm install，再打包"
}
New-Item -ItemType Directory -Path $vueTargetDir -Force | Out-Null
Copy-Item -LiteralPath $vueSource -Destination (Join-Path $vueTargetDir 'vue.global.js') -Force
Write-Ok '已随包带上 vue.global.js（网页不再依赖 node_modules）'

# ---------------------------------------------------------------------------
# 4. BUILD_INFO.json 与安装说明
# ---------------------------------------------------------------------------
Write-Step '写入构建信息'
$buildInfo = [ordered]@{
    version    = $Version
    commit     = $Commit
    built_at   = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    built_on   = [System.Environment]::OSVersion.VersionString
    source     = '安装包'
    entry      = '启动工作台.bat'
    needs      = @(
        'Python 3.10 / 3.11 / 3.12（首次启动会自动建虚拟环境并装依赖，需要联网）',
        '.env 里的 OPENAI_API_KEY（安装后自己填，安装包里不含任何密钥）'
    )
    bundled    = @(
        'tools\tectonic\tectonic.exe（PDF 编译器，已随包带上）',
        'workbench\static\vendor\vue\vue.global.js（网页前端，已随包带上）'
    )
    not_bundled = @(
        'models\（本地公式模型约 3 GB，只有"画板"用得到；需要时按 安装说明.txt 下载）',
        '.env（密钥文件，绝不随包分发）'
    )
}
$buildInfoPath = Join-Path $Staging 'BUILD_INFO.json'
# PowerShell 5.1 的 Set-Content -Encoding UTF8 会写 BOM，网页那边 json 解析就会失败，
# 于是这里用 .NET 显式写成"无 BOM 的 UTF-8"。
$buildInfoJson = $buildInfo | ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($buildInfoPath, $buildInfoJson, (New-Object System.Text.UTF8Encoding($false)))
Write-Ok "已写入 BUILD_INFO.json（版本 $Version，提交号 $(if ($Commit) { $Commit } else { '无' })）"

$notesSource = Join-Path $Root 'installer\安装说明.txt'
if (Test-Path -LiteralPath $notesSource) {
    Copy-Item -LiteralPath $notesSource -Destination (Join-Path $Staging '安装说明.txt') -Force
    Write-Ok '已放入 安装说明.txt'
} else {
    Write-Warn '仓库里没有 installer\安装说明.txt，安装包不含使用说明'
}

# ---------------------------------------------------------------------------
# 5. 逐项核对打包结果
# ---------------------------------------------------------------------------
Write-Step '核对打包结果（只报实际查到的事实）'
$problems = @()

function Test-StagedFile {
    param([string]$Relative, [string]$What)
    $path = Join-Path $Staging $Relative
    if (Test-Path -LiteralPath $path) {
        $sizeKb = [math]::Round((Get-Item -LiteralPath $path).Length / 1KB)
        Write-Ok "$What 在（$Relative，$sizeKb KB）"
    } else {
        Write-Bad "$What 不在（$Relative）"
        $script:problems += "缺少 $Relative"
    }
}

function Test-StagedAbsent {
    param([string]$Relative, [string]$What)
    $path = Join-Path $Staging $Relative
    if (Test-Path -LiteralPath $path) {
        Write-Bad "$What 被带进了安装包（$Relative）"
        $script:problems += "$Relative 不该出现在安装包里"
    } else {
        Write-Ok "$What 没被带进去（$Relative）"
    }
}

Test-StagedFile '启动工作台.bat' '一键启动脚本'
Test-StagedFile '关闭工作台.bat' '一键关闭脚本'
Test-StagedFile 'tools\tectonic\tectonic.exe' 'PDF 编译器'
Test-StagedFile 'workbench\app.py' '工作台后端'
Test-StagedFile 'workbench\static\index.html' '工作台页面'
Test-StagedFile 'workbench\static\vendor\vue\vue.global.js' 'Vue 前端'
Test-StagedFile 'scripts\launch.ps1' '启动器主逻辑'
Test-StagedFile 'requirements.txt' 'Python 依赖清单'
Test-StagedFile '.env.example' 'API 配置模板'
Test-StagedFile 'BUILD_INFO.json' '构建信息'
Test-StagedAbsent '.env' 'API 密钥文件'
Test-StagedAbsent '.venv' '本机虚拟环境'
Test-StagedAbsent 'node_modules' 'npm 依赖目录'
Test-StagedAbsent 'models' '本地公式模型（3 GB）'
Test-StagedAbsent 'artifacts' '本机跑出来的任务产物'
Test-StagedAbsent '.git' 'git 历史'

$keyValue = $null
$envFile = Join-Path $Root '.env'
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in (Get-Content -LiteralPath $envFile)) {
        if ($line -match '^\s*OPENAI_API_KEY\s*=\s*(.+)$') { $keyValue = $Matches[1].Trim(); break }
    }
}
if ($keyValue -and $keyValue.Length -ge 8) {
    # 逐个文本文件比对密钥原文，命中就说明打包范围有问题，必须停下。
    $textExtensions = @('.py', '.ps1', '.txt', '.md', '.json', '.html', '.js', '.bat', '.tex', '.yaml', '.yml', '.toml', '.cfg', '')
    $textFiles = Get-ChildItem -LiteralPath $Staging -Recurse -File |
        Where-Object { $textExtensions -contains $_.Extension.ToLower() }
    $hits = @($textFiles | Select-String -SimpleMatch -Pattern $keyValue -List | ForEach-Object { $_.Path })
    if ($hits.Count) {
        Write-Bad "在安装包里发现了本机 API 密钥：$($hits -join '、')"
        $problems += '安装包内含 API 密钥'
    } else {
        Write-Ok "安装包里没有出现本机的 OPENAI_API_KEY（核对了 $($textFiles.Count) 个文本文件）"
    }
} else {
    Write-Warn '本机 .env 里没有可核对的 OPENAI_API_KEY，这一项没法核对'
}

if ($problems.Count) {
    Write-Host ''
    Stop-WithMessage ("核对没通过，共 {0} 项：{1}" -f $problems.Count, ($problems -join '；'))
}

# ---------------------------------------------------------------------------
# 6. 压成 zip
# ---------------------------------------------------------------------------
Write-Step '压缩成 zip'
New-Item -ItemType Directory -Path $DistRoot -Force | Out-Null
$zipPath = Join-Path $DistRoot "$PackageName.zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
# 压缩整个暂存目录（不是目录里的 *），这样解压出来是一个 Hand2LaTeX-<版本>-win64 文件夹，
# 用户"解压到当前文件夹"时不会把几百个文件撒得到处都是。
Compress-Archive -Path $Staging -DestinationPath $zipPath -CompressionLevel Optimal
$zipMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
Write-Ok "已生成 dist\$PackageName.zip（$zipMb MB）"
Write-Ok "SHA256 $zipHash"

# ---------------------------------------------------------------------------
# 7. 可选：编 Inno Setup 安装器
# ---------------------------------------------------------------------------
$setupMb = $null
$setupHash = $null
if ($BuildInstaller) {
    Write-Step '编译安装器（Inno Setup）'
    $issPath = Join-Path $Root 'installer\hand2latex.iss'
    if (-not (Test-Path -LiteralPath $issPath)) { Stop-WithMessage "找不到 $issPath" }
    $iscc = $null
    if ($Iscc) {
        if (-not (Test-Path -LiteralPath $Iscc)) { Stop-WithMessage "指定的 ISCC.exe 不存在：$Iscc" }
        $iscc = $Iscc
    }
    if (-not $iscc) {
        $command = Get-Command iscc -ErrorAction SilentlyContinue
        if ($command) { $iscc = $command.Source }
    }
    if (-not $iscc) {
        foreach ($candidate in @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )) {
            if ($candidate -and (Test-Path -LiteralPath $candidate)) { $iscc = $candidate; break }
        }
    }
    if (-not $iscc) {
        # 安装时可以自选目录（本机就装在 D:\API\Inno Setup 6），所以再问一次注册表。
        foreach ($hive in @('HKCU:', 'HKLM:')) {
            $key = Join-Path $hive 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1'
            $location = (Get-ItemProperty -Path $key -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation
            if ($location) {
                $candidate = Join-Path $location 'ISCC.exe'
                if (Test-Path -LiteralPath $candidate) { $iscc = $candidate; break }
            }
        }
    }
    if (-not $iscc) {
        Write-Warn '这台机器上没有 Inno Setup 6，安装器没有编出来（zip 绿色包已经好了）。'
        Write-Warn '安装：winget install JRSoftware.InnoSetup；GitHub 连不上时可从镜像下载官方安装器，'
        Write-Warn '并用 winget show --id JRSoftware.InnoSetup 里的 SHA256 核对后再运行。'
        Write-Warn '装在非默认目录时，用 -Iscc "路径\ISCC.exe" 直接指定。'
    } else {
        Write-Ok "用 $iscc 编译"
        # 临时目录要留给安装器用，所以清理动作放到这一步之后。
        & $iscc "/DAppVersion=$Version" "/DSourceDir=$Staging" "/DOutputDir=$DistRoot" $issPath
        if ($LASTEXITCODE -ne 0) { Stop-WithMessage "Inno Setup 编译失败（退出码 $LASTEXITCODE）" }
        $setupPath = Join-Path $DistRoot "Hand2LaTeX-$Version-win64-setup.exe"
        if (Test-Path -LiteralPath $setupPath) {
            $setupMb = [math]::Round((Get-Item -LiteralPath $setupPath).Length / 1MB, 1)
            $setupHash = (Get-FileHash -LiteralPath $setupPath -Algorithm SHA256).Hash
            Write-Ok "已生成 dist\Hand2LaTeX-$Version-win64-setup.exe（$setupMb MB）"
            Write-Ok "SHA256 $setupHash"
        } else {
            Write-Warn "Inno Setup 退出码 0，但没找到预期的 $setupPath"
        }
    }
}

if (-not $KeepStaging) {
    Remove-Item -LiteralPath $Staging -Recurse -Force
    Write-Ok '已清理临时目录（想留着看就加 -KeepStaging）'
}

Write-Host ''
Write-Host '打包完成。' -ForegroundColor Green
Write-Host "    绿色包：dist\$PackageName.zip（$zipMb MB）"
Write-Host "    SHA256：$zipHash"
if ($setupHash) {
    Write-Host "    安装器：dist\Hand2LaTeX-$Version-win64-setup.exe（$setupMb MB）"
    Write-Host "    SHA256：$setupHash"
}
Write-Host '    用法：解压到任意可写目录（别放 Program Files），双击 启动工作台.bat，按 安装说明.txt 填 .env 里的密钥。'
