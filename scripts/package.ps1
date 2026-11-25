<#
.SYNOPSIS
    把当前仓库打成可以发给别人用的 Windows 安装包。

.DESCRIPTION
    产出两样东西（都放在 dist\ 下）：
      1. Hand2LaTeX-<版本>-win64.zip   —— 绿色包：解压后双击 启动工作台.bat 就能用
      2. Hand2LaTeX-<版本>-win64-setup.exe —— 安装器（需要本机装了 Inno Setup 6，加 -BuildInstaller）

    打包做的事：
      - 按排除清单复制仓库（不带 .env、.venv、.cache、node_modules、models、artifacts、dist）
      - 把 vue.global.js 随包带上，这样目标机器不装 Node.js 也能打开网页
      - 构建随包 Python 运行时（embeddable 3.12 + 预装 requirements-app.txt），
        这样目标机器不装 Python 也能跑；只想要瘦包就加 -NoPython
      - 写 BUILD_INFO.json（版本、提交号、打包时间、有没有带运行时），
        网页"系统状态"里会显示"来源：安装包"
      - 复制 安装说明.txt
      - 逐项核对打包结果（该在的在不在、不该带的有没有带进去），有问题就停下报错

    这个脚本只读仓库、只往 dist\ 与 .cache\ 写，不会改动源代码，也不会碰 .env。
    构建随包运行时要联网（python.org 下载 embeddable 包 + PyPI 装依赖），
    下载缓存放在 .cache\，第二次打包就不用重下。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
    打带 Python 运行时的 zip 绿色包（约 65 MB）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -NoPython
    打不带运行时的瘦包（约 20 MB），对方要自己装 Python 3.10 / 3.11 / 3.12。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -BuildInstaller
    打 zip，并在找到 Inno Setup 时顺便编出安装器。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -BuildInstaller -Iscc "D:\API\Inno Setup 6\ISCC.exe"
    Inno Setup 装在非默认目录、也没加进 PATH 时，直接指定 ISCC.exe。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1 -IncludeDemoJob c3d4e5f60718293a4b5c6d7e8f901234
    打一个带演示任务的包：把 artifacts\jobs\<id> 一起带上，对方解压打开就有真实任务可看，
    不用配密钥、不用等识别。id 是工作台左侧任务列表里那一串十六进制。
    不传这个参数时会反过来检查"包里的任务产物必须为空"，避免把自己的实验数据发出去。
#>
[CmdletBinding()]
param(
    [switch]$BuildInstaller,
    [switch]$KeepStaging,
    [string]$Iscc,
    # 默认随包带一份 Python（embeddable + 预装依赖），目标机器不用装 Python。
    # 加 -NoPython 只打不带运行时的瘦包（约 20 MB），但对方必须自己装 Python 3.10~3.12。
    [switch]$NoPython,
    # 打一个"演示包"：把手选的 artifacts\jobs\<id> 一起带上，对方解压打开就能看到
    # 完整三栏效果，不用自己准备图片、不用花 API 费用。
    [string[]]$IncludeDemoJob,
    # 强制重新下载并构建随包 Python 运行时。默认复用仓库里 runtime\python（若存在），
    # 因为那正是本机验证过能跑的那一份。
    [switch]$RebuildRuntime
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
    '.cache',
    'runtime',
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
# 从 zip 解压出来的源码目录没有 .git：这时候不该崩，只是记不到提交号。
$isRepo = (Test-Path -LiteralPath (Join-Path $Root '.git'))
if ($git -and $isRepo) {
    Push-Location $Root
    # 2>$null 在这里不够：git 往 stderr 写 fatal 时，$ErrorActionPreference='Stop'
    # 会把它当终止错误。用 try/catch 兜住，非仓库目录直接跳过。
    try {
        $Commit = (& git rev-parse --short HEAD 2>$null)
        # 分开看：已跟踪文件的改动会让"提交号对不上"，未跟踪文件只是会多带进包里。
        $dirtyTracked = (& git status --porcelain --untracked-files=no 2>$null)
        $untracked = (& git ls-files --others --exclude-standard 2>$null)
    } catch {
        $Commit = $null
        $dirtyTracked = $null
        $untracked = $null
    }
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
} elseif (-not $isRepo) {
    Write-Warn '这个目录不是 git 仓库（可能是从 zip 解压的源码）：BUILD_INFO 里记不到提交号，其余流程照常'
} else {
    Write-Warn '找不到 git，BUILD_INFO.json 里不写提交号'
}

$PackageName = "Hand2LaTeX-$Version-win64"
$Staging = Join-Path $StagingParent $PackageName
# 随包 Python 运行时的版本与官方 MD5，实际下载与校验在 scripts\build_python_runtime.ps1 里做。
$RuntimePythonVersion = '3.12.10'

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
$vueTarget = Join-Path $vueTargetDir 'vue.global.js'
# 从安装包解出来的源码目录通常没有 node_modules，但 vendor 里已经有一份可用的副本
# （robocopy 已经把它复制到 staging 了）。有副本就直接用，不必再 npm install。
if (-not (Test-Path -LiteralPath $vueSource) -and (Test-Path -LiteralPath $vueTarget)) {
    Write-Ok 'node_modules 不存在，但仓库里已有 vendor 副本：直接沿用'
    $vueSource = $vueTarget
}
if (-not (Test-Path -LiteralPath $vueSource)) {
    Stop-WithMessage "找不到 vue.global.js：先运行 npm install，或从安装包里取一份放到 workbench\static\vendor\vue\"
}
New-Item -ItemType Directory -Path $vueTargetDir -Force | Out-Null
if ($vueSource -ne $vueTarget) {
    Copy-Item -LiteralPath $vueSource -Destination $vueTarget -Force
}
Write-Ok '已随包带上 vue.global.js（网页不再依赖 node_modules）'

# ---------------------------------------------------------------------------
# 3.1 可选：把演示任务一起带上
# artifacts 默认整目录排除（里面有真实识别产物、可能含用户手写照片），
# 只有显式 -IncludeDemoJob 指定的任务目录才会进包。
# ---------------------------------------------------------------------------
if ($IncludeDemoJob) {
    Write-Step '复制演示任务'
    $demoRoot = Join-Path $Staging 'artifacts\jobs'
    New-Item -ItemType Directory -Path $demoRoot -Force | Out-Null
    foreach ($jobId in $IncludeDemoJob) {
        if ($jobId -notmatch '^[0-9a-f]{32}$') {
            Stop-WithMessage "演示任务号格式不对：$jobId（任务号是 artifacts\jobs 下 32 位十六进制的目录名）"
        }
        $source = Join-Path $Root "artifacts\jobs\$jobId"
        if (-not (Test-Path -LiteralPath $source)) {
            Stop-WithMessage "找不到演示任务：$source（先用工作台跑一遍，确认任务目录存在）"
        }
        $target = Join-Path $demoRoot $jobId
        # 只带文件，不带 __pycache__ 之类的中间产物。
        Copy-Item -LiteralPath $source -Destination $target -Recurse -Force
        # 用 ForEach-Object 显式传 -LiteralPath，而不是把对象管道给 Remove-Item：
        # 管道绑定时 -Path 走的是位置参数，某些环境的安全钩子会判成"缺少路径操作数"直接拦掉。
        Get-ChildItem -Path $target -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
        Write-Ok "已带上演示任务 $jobId"
    }
}

# ---------------------------------------------------------------------------
# 4. BUILD_INFO.json 与安装说明
# ---------------------------------------------------------------------------
Write-Step '写入构建信息'
$needs = @('.env 里的 OPENAI_API_KEY（安装后自己填，安装包里不含任何密钥）')
$bundled = @(
    'tools\tectonic\tectonic.exe（PDF 编译器，已随包带上）',
    'workbench\static\vendor\vue\vue.global.js（网页前端，已随包带上）'
)
$notBundled = @(
    'models\（本地公式模型约 3 GB，只有"画板"用得到；需要时按 安装说明.txt 下载）',
    '.env（密钥文件，绝不随包分发）'
)
if ($NoPython) {
    $needs = @('Python 3.10 / 3.11 / 3.12（这个包没带运行时，首次启动会自动建虚拟环境并装依赖，需要联网）') + $needs
    $notBundled = @('runtime\python\（本次用 -NoPython 打的瘦包，不含 Python 运行时）') + $notBundled
} else {
    $bundled = @("runtime\python\python.exe（Python $RuntimePythonVersion 运行时 + 网页工作台依赖，目标机器不用装 Python）") + $bundled
}
$buildInfo = [ordered]@{
    version    = $Version
    commit     = $Commit
    built_at   = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    built_on   = [System.Environment]::OSVersion.VersionString
    source     = '安装包'
    entry      = '启动工作台.bat'
    python_runtime = [ordered]@{
        bundled = (-not $NoPython)
        version = if ($NoPython) { $null } else { $RuntimePythonVersion }
        covers  = '只覆盖网页工作台；画板演示与本地公式识别仍需完整环境（见 安装说明.txt）'
    }
    needs      = $needs
    bundled    = $bundled
    not_bundled = $notBundled
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

# 与解压工具无关的保险：再放一份纯 ASCII 名字的入口。
# 有些解压工具不认 zip 的 UTF-8 文件名标志位（Info-ZIP 的 unzip 就是），
# 中文名解出来是一片乱码，用户连哪个是启动脚本都认不出。
# 三个英文名与中文名同内容，名字全乱时至少还有得选。
# make_package_zip.py 会核对这六个入口都在，缺一个就让打包失败——所以这里必须真的写出来，
# 不能只写在文档里。
$asciiEntries = @{
    'start.bat'   = '启动工作台.bat'
    'stop.bat'    = '关闭工作台.bat'
    'INSTALL.txt' = '安装说明.txt'
}
foreach ($asciiName in $asciiEntries.Keys) {
    $source = Join-Path $Staging $asciiEntries[$asciiName]
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $Staging $asciiName) -Force
    } else {
        Write-Warn "暂存目录里没有 $($asciiEntries[$asciiName])，跳过同名英文入口 $asciiName"
    }
}
Write-Ok '已放入英文名入口 start.bat / stop.bat / INSTALL.txt（解压工具把中文名弄乱时的兜底）'

# 汇报文档必须放在包的最外层，对方解压第一眼就能看到。
# 以前这份文档没有源码树里的位置：它是手工拷进 staging 的，所以既进不了版本管理，
# 下次打包也很容易被忘掉——2026-11-25 那一版就是这样漏掉性能修复说明的。
# 现在源文件固定在 docs\成果汇报_<日期>.md，由脚本按文件名通配最新一份带出去。
$reportCandidates = @(Get-ChildItem -LiteralPath (Join-Path $Root 'docs') -Filter '成果汇报_*.md' -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending)
if ($reportCandidates.Count -gt 0) {
    $reportSource = $reportCandidates[0]
    Copy-Item -LiteralPath $reportSource.FullName -Destination (Join-Path $Staging '成果汇报_先看这个.md') -Force
    Write-Ok "已放入 成果汇报_先看这个.md（来自 docs\$($reportSource.Name)）"
    if ($reportCandidates.Count -gt 1) {
        Write-Warn "docs\ 下有 $($reportCandidates.Count) 份成果汇报，取了最新的一份（$($reportSource.Name)）；旧的建议归档到 docs\archive\"
    }
} else {
    Write-Warn 'docs\ 下没有 成果汇报_*.md，安装包不含汇报文档'
}

# ---------------------------------------------------------------------------
# 4.5 随包 Python 运行时（目标机器不用装 Python）
# ---------------------------------------------------------------------------
$runtimeDir = Join-Path $Staging 'runtime\python'
if ($NoPython) {
    Write-Step '跳过随包 Python 运行时（-NoPython）'
    Write-Warn '这个包不含 Python，对方必须自己装 Python 3.10 / 3.11 / 3.12，首次启动还要联网装依赖'
} elseif ((Test-Path -LiteralPath (Join-Path $Root 'runtime\python\python.exe')) -and -not $RebuildRuntime) {
    # 仓库里已经有一份装好依赖的运行时，直接复制比重新下载+装 pip 快得多，
    # 而且能保证"打出来的包"和"本机跑通的"是同一份环境。
    Write-Step '复用仓库已有的 Python 运行时'
    Copy-Item -LiteralPath (Join-Path $Root 'runtime\python') -Destination $runtimeDir -Recurse -Force
    Get-ChildItem -Path $runtimeDir -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    $runtimeMb = [math]::Round(((Get-ChildItem -LiteralPath $runtimeDir -Recurse -File | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Ok "已复用运行时（$runtimeMb MB）。要重新构建请加 -RebuildRuntime"
} else {
    Write-Step "构建随包 Python 运行时（$RuntimePythonVersion）"
    $runtimeScript = Join-Path $Root 'scripts\build_python_runtime.ps1'
    if (-not (Test-Path -LiteralPath $runtimeScript)) { Stop-WithMessage "找不到 $runtimeScript" }
    # 这一步会联网下载 embeddable 包（有缓存就不下）并从 PyPI 装依赖，比较慢。
    & $runtimeScript -TargetDir $runtimeDir -PythonVersion $RuntimePythonVersion
    if ($LASTEXITCODE -ne 0) { Stop-WithMessage "随包 Python 运行时构建失败（退出码 $LASTEXITCODE）" }
    $runtimeMb = [math]::Round(((Get-ChildItem -LiteralPath $runtimeDir -Recurse -File | Measure-Object -Property Length -Sum).Sum) / 1MB, 1)
    Write-Ok "随包运行时就绪（$runtimeMb MB）"
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
Test-StagedFile 'requirements-app.txt' '网页工作台依赖清单（随包运行时装的是这一份）'
Test-StagedFile '成果汇报_先看这个.md' '成果汇报（对方解压第一眼要看的）'
Test-StagedFile '安装说明.txt' '使用说明'
# 三个英文名入口是"解压工具把中文名弄乱"时的兜底，缺了就等于没有兜底。
Test-StagedFile 'start.bat' '英文名启动入口（乱码兜底）'
Test-StagedFile 'stop.bat' '英文名关闭入口（乱码兜底）'
Test-StagedFile 'INSTALL.txt' '英文名说明（乱码兜底）'
Test-StagedAbsent '.env' 'API 密钥文件'
Test-StagedAbsent '.venv' '本机虚拟环境'
Test-StagedAbsent '.cache' '打包用的下载缓存'
Test-StagedAbsent 'node_modules' 'npm 依赖目录'
Test-StagedAbsent 'models' '本地公式模型（3 GB）'
if ($IncludeDemoJob) {
    # 带了演示任务时 artifacts 本来就在包里，判据换成"只该有指定的那几个任务"。
    $stagedJobs = Join-Path $Staging 'artifacts\jobs'
    $found = @()
    if (Test-Path -LiteralPath $stagedJobs) {
        $found = @(Get-ChildItem -LiteralPath $stagedJobs -Directory | Select-Object -ExpandProperty Name)
    }
    $extra = @($found | Where-Object { $IncludeDemoJob -notcontains $_ })
    if ($extra.Count -gt 0) {
        Write-Bad "安装包的 artifacts\jobs 里有多余任务：$($extra -join ', ')"
        $script:problems += "artifacts\jobs 里有多余任务"
    } else {
        Write-Ok "任务产物 只含指定的演示任务（$($IncludeDemoJob -join ', ')）"
    }
} else {
    Test-StagedAbsent 'artifacts' '本机跑出来的任务产物'
}
Test-StagedAbsent '.git' 'git 历史'
if ($NoPython) {
    Test-StagedAbsent 'runtime' 'Python 运行时（本次 -NoPython）'
} else {
    Test-StagedFile 'runtime\python\python.exe' '随包 Python 运行时'
    Test-StagedFile 'runtime\python\Lib\site-packages\fastapi\__init__.py' '随包运行时里的 fastapi'
    Test-StagedFile 'runtime\python\Lib\site-packages\uvicorn\__init__.py' '随包运行时里的 uvicorn'
}

$keyValue = $null
$envFile = Join-Path $Root '.env'
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in (Get-Content -LiteralPath $envFile)) {
        if ($line -match '^\s*OPENAI_API_KEY\s*=\s*(.+)$') { $keyValue = $Matches[1].Trim(); break }
    }
}
if ($keyValue -and $keyValue.Length -ge 8) {
    # 逐个文本文件比对密钥原文，命中就说明打包范围有问题，必须停下。
    # 随包 Python 运行时与 tools 里是第三方文件，不是我们写的，也不可能是密钥的来源，
    # 排除掉是为了不让这一步跑几分钟；排除范围会如实打印出来。
    $textExtensions = @('.py', '.ps1', '.txt', '.md', '.json', '.html', '.js', '.bat', '.tex', '.yaml', '.yml', '.toml', '.cfg', '')
    $textFiles = Get-ChildItem -LiteralPath $Staging -Recurse -File |
        Where-Object {
            $textExtensions -contains $_.Extension.ToLower() -and
            $_.FullName -notlike '*\runtime\*' -and $_.FullName -notlike '*\tools\*'
        }
    $hits = @($textFiles | Select-String -SimpleMatch -Pattern $keyValue -List | ForEach-Object { $_.Path })
    if ($hits.Count) {
        Write-Bad "在安装包里发现了本机 API 密钥：$($hits -join '、')"
        $problems += '安装包内含 API 密钥'
    } else {
        Write-Ok "安装包里没有出现本机的 OPENAI_API_KEY（核对了 $($textFiles.Count) 个我们自己打包的文本文件；随包运行时与 tools 的第三方文件不在核对范围）"
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
#
# 用 Python 的 zipfile 而不是 Compress-Archive：后者在 Windows PowerShell 5.1 下
# 用 GBK 写中文文件名、却不置 zip 的 UTF-8 标志位，解压后 `启动工作台.bat` 会变成
# `Õà¦Úù¡ÕÀÑõ¢£ÕŦ.bat`，用户根本认不出哪个是启动脚本。
#
# 用 make_package_zip.py 而不是 make_zip.py：前者打完会当场核对条目名
# （没有反斜杠分隔符、非 ASCII 条目都带 UTF-8 标志位、六个入口文件齐全），
# 不通过就以非 0 退出。make_zip.py 只压不验——以前这里调的是它，
# 而 tests/test_packaging.py 锁的却是 make_package_zip.py，
# 结果是"被测的那个从来不是被用的那个"，zip 里的名字问题在真实打包路径上无人把关。
$zipScript = Join-Path $PSScriptRoot 'make_package_zip.py'
if (-not (Test-Path -LiteralPath $zipScript)) { Stop-WithMessage "找不到 $zipScript" }
# 用暂存目录里那份随包 Python：它一定存在（除非 -NoPython），且能在目标机器上跑。
$zipPython = Join-Path $Staging 'runtime\python\python.exe'
if (-not (Test-Path -LiteralPath $zipPython)) {
    $zipPython = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $zipPython) { Stop-WithMessage '打包 zip 需要一个 Python 解释器，但既没有随包运行时也找不到系统 python' }
# make_package_zip.py 把核对结果打成一行 JSON（避免中文在控制台变乱码），退出码非 0 表示核对没通过。
$zipReport = & $zipPython $zipScript $Staging $zipPath
$zipExit = $LASTEXITCODE
if ($zipExit -ne 0) {
    Write-Host $zipReport -ForegroundColor Red
    Stop-WithMessage "打包 zip 失败或核对没通过（退出码 $zipExit）"
}
try {
    $zipInfo = $zipReport | ConvertFrom-Json
    Write-Ok ("zip 核对通过：{0} 个条目，其中 {1} 个非 ASCII 名全部带 UTF-8 标志位；六个入口齐全、无反斜杠分隔符" -f `
        $zipInfo.entries, $zipInfo.non_ascii_entries)
} catch {
    Write-Warn "zip 已生成，但核对报告解析失败：$zipReport"
}
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
if ($NoPython) {
    Write-Host '    Python：这个包没带运行时（-NoPython），对方要自己装 Python 3.10 / 3.11 / 3.12。'
} else {
    Write-Host "    Python：已随包带上 $RuntimePythonVersion 运行时（$runtimeMb MB），对方不用装 Python。"
}
if ($setupHash) {
    Write-Host "    安装器：dist\Hand2LaTeX-$Version-win64-setup.exe（$setupMb MB）"
    Write-Host "    SHA256：$setupHash"
}
Write-Host '    用法：解压到任意可写目录（别放 Program Files），双击 启动工作台.bat，按 安装说明.txt 填 .env 里的密钥。'
