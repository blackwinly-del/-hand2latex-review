<#
.SYNOPSIS
    给安装包构建"随包 Python 运行时"：目标机器不用装 Python 也能跑网页工作台。

.DESCRIPTION
    产出一个自包含目录，例如  dist\staging\Hand2LaTeX-1.0.0-win64\runtime\python\python.exe
    做的事：
      1. 下载 python-<版本>-embed-amd64.zip（缓存在 .cache\，已缓存就不重下），
         按 python.org 官方公布的 MD5 校验，对不上就中止（绝不拿没校验过的二进制继续）
      2. 解压到 -TargetDir
      3. 写 python312._pth：加上 Lib\site-packages 与 ..\..（安装包根目录），并启用 import site。
         有了 ..\.. 才能 import workbench；embeddable 版默认忽略 PYTHONPATH，所以只能写在这个文件里。
      4. 用构建机的 pip 把 requirements-app.txt 装进 Lib\site-packages（--target）。
         故意不在随包运行时里装 pip：省 13 MB，也少一个联网步骤。
      5. 用随包 python.exe 真跑一次导入自检，失败就中止。

    为什么用构建机的 pip：wheel 是按 CPython 次版本编译的（cp312 的 .pyd 只能给 3.12 用），
    所以构建机的 Python 次版本必须与随包运行时一致，脚本会先核对，不一致就停下报错。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_python_runtime.ps1 -TargetDir dist\staging\X\runtime\python
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir,

    # 构建机的 python.exe，用来跑 pip --target。默认用仓库的 .venv。
    [string]$BuildPython,

    [string]$CacheDir,

    [string]$PythonVersion = '3.12.10',

    # python.org 公布的 MD5（下载页 "Windows embeddable package (64-bit)" 那一行）。
    # 换 PythonVersion 时必须同时换这个值，否则校验会失败。
    [string]$ExpectedMd5 = 'fe8ef205f2e9c3ba44d0cf9954e1abd3',

    # 依赖清单：只装网页工作台真正会 import 的那些（不含 torch / numpy / Pillow）。
    [string]$Requirements = 'requirements-app.txt'
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not $CacheDir) { $CacheDir = Join-Path $Root '.cache' }
if (-not $BuildPython) { $BuildPython = Join-Path $Root '.venv\Scripts\python.exe' }
if (-not [System.IO.Path]::IsPathRooted($TargetDir)) { $TargetDir = Join-Path $Root $TargetDir }

function Write-Ok { param([string]$Text) Write-Host "    [ok] $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    [注意] $Text" -ForegroundColor Yellow }
function Stop-WithMessage {
    param([string]$Text)
    Write-Host "    [失败] $Text" -ForegroundColor Red
    exit 1
}

# --- 0. 前置核对 -----------------------------------------------------------
if (-not (Test-Path -LiteralPath $BuildPython)) {
    Stop-WithMessage "找不到构建机的 Python：$BuildPython（先跑一次 启动工作台.bat 建好 .venv，或用 -BuildPython 指定）"
}
$requirementsPath = Join-Path $Root $Requirements
if (-not (Test-Path -LiteralPath $requirementsPath)) {
    Stop-WithMessage "找不到依赖清单：$requirementsPath"
}

$minor = & $BuildPython -c 'import sys; print(str(sys.version_info[0]) + chr(46) + str(sys.version_info[1]))'
if ($LASTEXITCODE -ne 0) { Stop-WithMessage "构建机的 Python 跑不起来：$BuildPython" }
$runtimeMinor = ($PythonVersion -split '\.')[0..1] -join '.'
if ($minor -ne $runtimeMinor) {
    Stop-WithMessage "构建机是 Python $minor，随包运行时是 $runtimeMinor：wheel 的 ABI 对不上，装进去会 import 失败。请把构建机的 Python 换成 $runtimeMinor。"
}
Write-Ok "构建机 Python $minor 与随包运行时 $PythonVersion 次版本一致"

# --- 1. 下载并校验 embeddable 包 -------------------------------------------
$zipName = "python-$PythonVersion-embed-amd64.zip"
$zipUrl = "https://www.python.org/ftp/python/$PythonVersion/$zipName"
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null
$zipPath = Join-Path $CacheDir $zipName

if (Test-Path -LiteralPath $zipPath) {
    Write-Ok "缓存里已有 $zipName，跳过下载"
} else {
    Write-Host "    下载 $zipUrl"
    try {
        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 600
    } catch {
        if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
        Stop-WithMessage "下载失败：$($_.Exception.Message)。这台机器连不上 python.org 时，可手动把 $zipName 放进 $CacheDir 再重跑。"
    }
}

$actualMd5 = (Get-FileHash -LiteralPath $zipPath -Algorithm MD5).Hash.ToLowerInvariant()
if ($actualMd5 -ne $ExpectedMd5.ToLowerInvariant()) {
    Stop-WithMessage "MD5 不对，文件可能被截断或被替换过：实际 $actualMd5，python.org 公布 $ExpectedMd5。删掉 $zipPath 重新下载。"
}
$zipMb = [math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB, 1)
Write-Ok "MD5 与 python.org 公布值一致（$zipName，$zipMb MB）"

# --- 2. 解压 ---------------------------------------------------------------
if (Test-Path -LiteralPath $TargetDir) { Remove-Item -LiteralPath $TargetDir -Recurse -Force }
New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $TargetDir -Force
$runtimePython = Join-Path $TargetDir 'python.exe'
if (-not (Test-Path -LiteralPath $runtimePython)) { Stop-WithMessage "解压后找不到 $runtimePython" }
Write-Ok "已解压到 $TargetDir"

# --- 3. 写 ._pth -----------------------------------------------------------
# embeddable 版靠这个文件决定 sys.path，而且会忽略 PYTHONPATH 环境变量。
# ..\.. 是安装包根目录（runtime\python 的上两级），这样 import workbench 才找得到。
$pthFiles = Get-ChildItem -LiteralPath $TargetDir -Filter 'python*._pth'
if ($pthFiles.Count -ne 1) { Stop-WithMessage "预期只有一个 python*._pth，实际找到 $($pthFiles.Count) 个" }
$pthPath = $pthFiles[0].FullName
$sitePackages = 'Lib\site-packages'
New-Item -ItemType Directory -Path (Join-Path $TargetDir $sitePackages) -Force | Out-Null
# 保留原文件里的 stdlib 条目（python3XX.zip 和 .），只追加我们要的两条与 import site。
$originalLines = Get-Content -LiteralPath $pthPath |
    Where-Object { $_.Trim() -and -not $_.TrimStart().StartsWith('#') }
$pthLines = @($originalLines) + @(
    $sitePackages,
    '..\..',
    '',
    '# Bundled runtime: enable site so pip-installed packages import,',
    '# and add the package root (two levels up) so "import workbench" works.',
    'import site'
)
# 这个文件只写 ASCII：它是 CPython 的启动路径配置，不放中文注释免得踩编码坑。
[System.IO.File]::WriteAllText($pthPath, ($pthLines -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Ok "已写 $($pthFiles[0].Name)（原有条目 + $sitePackages + ..\.. + import site）"

# --- 4. 装依赖 -------------------------------------------------------------
Write-Host "    安装 $Requirements 到 $sitePackages（用构建机的 pip --target）"
$targetPath = Join-Path $TargetDir $sitePackages
# pip 会把进度和提示写到 stderr；在 ErrorActionPreference=Stop 下那会被当成致命错误，
# 所以这两处原生调用临时放宽，靠退出码判断成败。
$previousEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$pipOutput = & $BuildPython -m pip install --target $targetPath --no-warn-script-location `
    --disable-pip-version-check --progress-bar off --upgrade -r $requirementsPath 2>&1
$pipExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap
if ($pipExit -ne 0) {
    Write-Host (($pipOutput | Select-Object -Last 25) -join "`n")
    Stop-WithMessage "pip 安装失败（退出码 $pipExit）。网络受限时先手动跑一次 pip 确认可用，再重跑本脚本。"
}
$installed = ($pipOutput | Where-Object { $_ -match '^Successfully installed' }) -join ' '
if ($installed) { Write-Ok $installed.Substring(0, [Math]::Min(160, $installed.Length)) } else { Write-Ok '依赖安装完成（pip 未报告新装包，可能都已就位）' }

# --- 5. 用随包运行时自检 ----------------------------------------------------
# 单独调用本脚本时目标目录外面没有 workbench，那就只自检依赖；
# 由 package.ps1 在暂存目录里调用时，..\.. 就是包根，连应用一起 import 一遍。
$packageRoot = Split-Path -Parent (Split-Path -Parent $TargetDir)
$probeLines = @('import sys, fastapi, uvicorn, openai, pymupdf, dotenv, multipart, httpx')
if (Test-Path -LiteralPath (Join-Path $packageRoot 'workbench\app.py')) {
    $probeLines += 'import workbench.app  # noqa: F401  真的把整个应用 import 一遍，缺什么立刻暴露'
    Write-Ok "目标目录外层就是包根（$packageRoot），自检会连 workbench.app 一起 import"
} else {
    Write-Warn "外层没有 workbench\app.py（$packageRoot），这次只自检依赖包"
}
$probeLines += 'print(sys.version.split()[0], "|", "pymupdf", pymupdf.__version__, "|", "fastapi", fastapi.__version__)'
$probePath = Join-Path $env:TEMP 'h2l_runtime_probe.py'
[System.IO.File]::WriteAllText($probePath, ($probeLines -join "`r`n") + "`r`n", (New-Object System.Text.UTF8Encoding($false)))
Push-Location $packageRoot
$previousEap2 = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$probeOutput = & $runtimePython $probePath 2>&1
$probeExit = $LASTEXITCODE
$ErrorActionPreference = $previousEap2
Pop-Location
Remove-Item -LiteralPath $probePath -Force -ErrorAction SilentlyContinue
if ($probeExit -ne 0) {
    Write-Host ($probeOutput -join "`n")
    Stop-WithMessage "随包运行时导入自检失败（退出码 $probeExit）"
}
Write-Ok "随包运行时自检通过：$($probeOutput -join ' ')"

# import workbench.app 会顺手建出 artifacts\jobs（app.py 在导入时就 mkdir），
# 那是本机运行产物、不该进安装包，所以只把这次自检建出来的空目录删掉。
$probeArtifacts = Join-Path $packageRoot 'artifacts'
if (Test-Path -LiteralPath $probeArtifacts) {
    $leftoverFiles = @(Get-ChildItem -LiteralPath $probeArtifacts -Recurse -File -ErrorAction SilentlyContinue)
    if ($leftoverFiles.Count -eq 0) {
        Remove-Item -LiteralPath $probeArtifacts -Recurse -Force
        Write-Ok '已清掉自检顺带建出来的空 artifacts 目录（本机运行产物不进包）'
    } else {
        Write-Warn "artifacts 目录里有 $($leftoverFiles.Count) 个文件，不是自检建出来的空目录，没动它"
    }
}

$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $TargetDir -Recurse -File | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
Write-Ok "随包运行时就绪：$TargetDir（$sizeMb MB）"
Write-Warn '这个运行时只覆盖网页工作台。画板演示（Streamlit + 本地公式识别）仍需 requirements.txt / requirements-b.txt 的完整环境。'
