# 从 Windows 证书库导出根证书，供 git 的 OpenSSL 后端使用
#
# 用法（在仓库根目录）：
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\export-git-ca.ps1
#   powershell -ExecutionPolicy Bypass -NoProfile -File scripts\export-git-ca.ps1 -OutFile D:\ca.pem
#
# 背景见 docs/GIT_PROXY_FIX.md。为什么会需要这个文件：
#   Git for Windows 默认的 schannel 后端要在线上查证书吊销状态（OCSP/CRL），
#   经代理时查不到，直接报 CRYPT_E_NO_REVOCATION_CHECK。切到 OpenSSL 后端能绕开
#   这个检查，但 OpenSSL 需要一份根证书包，而 Python 的 certifi 不含
#   USERTrust ECC CA 这一支 —— GitHub 的证书链恰好需要它。系统证书库是全的。
param(
    [string]$OutFile = "C:\ProgramData\git-ca\system-roots.pem",
    [switch]$AlsoConfigureGit
)

$ErrorActionPreference = 'Stop'

$sb = New-Object System.Text.StringBuilder
$count = 0
$stores = @(
    'Cert:\LocalMachine\Root',
    'Cert:\LocalMachine\CA',
    'Cert:\CurrentUser\Root',
    'Cert:\CurrentUser\CA'
)

foreach ($store in $stores) {
    if (-not (Test-Path $store)) { continue }
    Get-ChildItem -Path $store -ErrorAction SilentlyContinue | ForEach-Object {
        $b64 = [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
        [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----')
        [void]$sb.AppendLine($b64)
        [void]$sb.AppendLine('-----END CERTIFICATE-----')
        $count++
    }
}

if ($count -eq 0) {
    throw "没有从证书库读到任何证书，检查是否以足够权限运行"
}

$dir = Split-Path -Parent $OutFile
if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# 必须写 UTF-8 无 BOM：PEM 解析器遇到 BOM 会认为第一段不是 "-----BEGIN"
[System.IO.File]::WriteAllText($OutFile, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))

$sizeKb = [math]::Round((Get-Item $OutFile).Length / 1KB)
Write-Host "已导出 $count 张证书到 $OutFile（$sizeKb KB）"

# 路径含中文会让某些 OpenSSL 调用失败，这里显式提示一下
if ($OutFile -match '[^\x00-\x7F]') {
    Write-Warning "输出路径含非 ASCII 字符。部分 OpenSSL 调用会读不到，建议放到 C:\ProgramData\ 下"
}

if ($AlsoConfigureGit) {
    $posix = $OutFile -replace '\\', '/'
    git config --global http.sslBackend openssl
    git config --global http.sslCAInfo $posix
    Write-Host "已写入 git 全局配置："
    Write-Host "  http.sslBackend = openssl"
    Write-Host "  http.sslCAInfo  = $posix"
}

Write-Host ""
$posixForHint = $OutFile -replace '\\', '/'
Write-Host "下一步（若未加 -AlsoConfigureGit）："
Write-Host "  git config --global http.sslBackend openssl"
Write-Host "  git config --global http.sslCAInfo '$posixForHint'"
Write-Host "  git ls-remote --heads origin    # 验证"
