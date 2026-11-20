[CmdletBinding()]
param(
    [int]$Port = 8501,
    [switch]$NoBrowser,
    [switch]$Gpu
)

# 画板演示的一键启动：检查环境 -> 缺包才装 -> 起 Streamlit -> 开浏览器。
# 与工作台不同，画板在当前窗口前台运行：窗口关了就停，避免找不到进程。
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
$Root = Split-Path -Parent $PSScriptRoot
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
if ($Gpu) {
    if (-not (Test-Path -LiteralPath $GpuPython)) {
        Stop-WithHint '没有找到 GPU 虚拟环境 .venv\gpu-venv。' `
            '请按 README 6.4 建好 GPU 环境，或不加 -Gpu 用 CPU 启动。'
    }
    $VenvPython = $GpuPython
    $env:RECOGNIZER_DEVICE = 'gpu:0'
    Write-Line '使用 GPU 环境（RECOGNIZER_DEVICE=gpu:0）' 'ok'
}
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Stop-WithHint '没有找到 .venv 虚拟环境，画板需要先装好项目环境。' `
        '请先双击 启动工作台.bat 选 [2] 准备并启动，它会建好 .venv。'
}
if (-not (Test-Path -LiteralPath $DemoApp)) {
    Stop-WithHint '没有找到 demo\app.py。' '画板演示在新版本代码里，请先 git pull 同步仓库。'
}
Write-Line '虚拟环境就绪' 'ok'

Write-Step '检查画板依赖（streamlit + drawable-canvas）'
$deps = Test-DemoDeps
if (-not $deps.Ok) {
    if ($Gpu) {
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
    if (-not $NoBrowser) { Start-Process $Url }
    exit 0
}

Write-Step '检查端口'
$listener = $null
try {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    Write-Line "端口 $Port 可用" 'ok'
} catch {
    Stop-WithHint "端口 $Port 被别的程序占用，且不是画板服务。" `
        "可以换一个端口：.\scripts\launch_demo.ps1 -Port $($Port + 1)"
} finally {
    if ($listener) { $listener.Stop() }
}

Write-Step '启动画板（前台运行）'
$server = Start-Process -FilePath $VenvPython `
    -ArgumentList @('-m','streamlit','run','demo/app.py','--server.headless','true','--server.port',"$Port",'--server.address','127.0.0.1') `
    -WorkingDirectory $Root -NoNewWindow -PassThru

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
if (-not $NoBrowser) { Start-Process $Url }
Write-Line '在左侧画板写字，停笔约 1 秒自动识别；第一次识别要加载本地模型，较慢属正常。'
Write-Line '本窗口开着画板才在运行，关闭窗口或按 Ctrl+C 即停止。' 'warn'

Wait-Process -Id $server.Id
Write-Line '画板已停止。' 'ok'
