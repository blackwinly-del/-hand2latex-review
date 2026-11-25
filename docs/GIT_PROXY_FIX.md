# Git 访问 GitHub 报 502 / 证书错误的修复记录

> 2026-11-25 排查并修复。以后 `git fetch` / `git push` 再报错，先看这份。

## 结论（TL;DR）

真正的问题**不是代理坏了**，是 **OpenSSL 后端找不到根证书**。一条命令修好：

```bash
git config --global http.sslBackend openssl
git config --global http.sslCAInfo "C:/ProgramData/git-ca/system-roots.pem"
```

证书文件由系统证书库导出（122 张），生成命令见本文末尾。**不需要**关闭证书验证。

## 报错长什么样

三种报错，按出现顺序：

```
fatal: unable to access '...': CONNECT tunnel failed, response 502
fatal: unable to access '...': schannel: next InitializeSecurityContext failed:
  CRYPT_E_NO_REVOCATION_CHECK (0x80092012) - 吊销服务器离线
fatal: unable to access '...': SSL certificate OpenSSL verify result:
  unable to get local issuer certificate (20)
```

## 排查过程与每一步的真实结论

### 1. 先确认 502 到底是谁返回的

这台机器上有**两层代理**，容易看错：

```
git / curl
    ↓
sandbox-cli          127.0.0.1:64242   ← 会话级，端口每次会话都变
    ↓
Steam++ Accelerator  127.0.0.1:26561   ← 系统代理，端口写死在配置里
    ↓
外网
```

用 `openssl s_client -proxy` 分别测两层，结果：

| 目标 | sandbox-cli 64242 | Steam++ 26561 |
| --- | --- | --- |
| `github.com` | 502（**间歇性**，多数时候能通） | 200，但证书被替换 |
| `api.github.com` | 200 | 200 |
| `raw.githubusercontent.com` | 200 | 200 |

**关键点：502 是间歇性的。** 一开始连测 3 次全是 502，隔几分钟再连测 5 次全是 CONNECTED。
所以「502 = 被永久拦截」这个判断是错的——它更像上游偶发失败或限流。
遇到 502 先别急着改配置，**等几十秒重试一次**，很可能自己就好了。

### 2. 别走「配代理」这条路

我最初的做法是给 github.com 单独指定 Steam++：

```bash
git config --global http.https://github.com.proxy http://127.0.0.1:26561
```

502 确实消失了，但立刻换成证书错误。查证书链发现原因：

```
 0 s:CN=github.com
   i:CN=SteamTools Certificate, OU=Technical Department, O=BeyondDimension, C=CN
```

**Steam++ 在做中间人解密**，用它的自签根证书替换了 GitHub 的真实证书。
而它加速的是 Steam 商店，对 GitHub 的中间人解密纯粹是副作用。

用沙箱代理（64242）时证书链是**真实的**：

```
 0 s:CN=github.com
   i:C=GB, O=Sectigo Limited, CN=Sectigo Public Server Authentication CA DV E36
 1 s:...Sectigo Public Server Authentication CA DV E36
   i:...Sectigo Public Server Authentication Root E46
 2 s:...Sectigo Public Server Authentication Root E46
   i:C=US, ... O=The USERTRUST Network, CN=USERTrust ECC Certification Authority
```

所以**不要绕开沙箱代理去走 Steam++**，那会把真实证书换成假的。

### 3. schannel 那条路也走不通

Git for Windows 默认用 schannel（Windows 原生 TLS），报 `CRYPT_E_NO_REVOCATION_CHECK`。
这是因为它要在线查证书吊销状态（OCSP/CRL），而代理链路上查不到。

尝试过并**确认无效**的方式（别再试了）：

| 方式 | 结果 |
| --- | --- |
| `git config http.schannelCheckRevoke false` | 无效。该配置项在此 Git 版本不生效 |
| `git -c http.schannelCheckRevoke=false` | 无效 |
| `http.https://github.com.schannelCheckRevoke=false` | 无效 |
| 环境变量 `GIT_SCHANNEL_CHECK_REVOKE=0` | 无效 |

**顺带排掉一个坑**：`GIT_SSL_NO_VERIFY` 这个环境变量，只要**存在**就关闭证书验证，
不管值是 `false`、`0` 还是空串。我一度设成 `false` 以为没关验证，实际是关的。
这是个真实的安全隐患，已确认撤销、没有留在环境里。

### 4. 真正的解：切 OpenSSL + 给对根证书

```bash
git config --global http.sslBackend openssl
```

立刻换成 `unable to get local issuer certificate (20)`。这好办——OpenSSL 只是缺根证书。

我先用 Python 的 certifi 包导出（223 KB），仍然失败：**certifi 里没有
`USERTrust ECC Certification Authority`** 这一支，而 GitHub 的证书链正好需要它。

正解是**从 Windows 证书库导出**，因为系统里已经有完整的一套：

```powershell
$out = "C:\ProgramData\git-ca\system-roots.pem"
$sb = New-Object System.Text.StringBuilder
foreach ($store in @('Cert:\LocalMachine\Root','Cert:\LocalMachine\CA',
                     'Cert:\CurrentUser\Root','Cert:\CurrentUser\CA')) {
    Get-ChildItem -Path $store -ErrorAction SilentlyContinue | ForEach-Object {
        [void]$sb.AppendLine('-----BEGIN CERTIFICATE-----')
        [void]$sb.AppendLine([Convert]::ToBase64String($_.RawData,'InsertLineBreaks'))
        [void]$sb.AppendLine('-----END CERTIFICATE-----')
    }
}
[System.IO.File]::WriteAllText($out, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
```

122 张证书、212 KB。配置后立即通过。

**路径必须用纯 ASCII。** 放在 `C:\Users\袁昊然\` 下曾失败过一次，
换到 `C:\ProgramData\git-ca\` 才稳定——中文用户名路径在某些 OpenSSL 调用里会出问题。

## 最终生效的配置

只有两项，都在全局 `.gitconfig` 里：

```
http.sslbackend = openssl
http.sslcainfo  = C:/ProgramData/git-ca/system-roots.pem
```

**没有**设置：`GIT_SSL_NO_VERIFY`、`http.schannelCheckRevoke`、任何 proxy 覆盖。
证书验证保持开启。

## 验证方式

```bash
git ls-remote --heads origin    # 应列出 4 个分支，无任何报错
git fetch origin                # 应成功
git push --dry-run origin main  # 应显示 up-to-date 或待推送列表
```

刚才实测：连续 3 次 `ls-remote` 稳定返回 4 个分支，`fetch` 退出码 0，
`push --dry-run` 正常。

## 如果以后又报错

按这个顺序查，别跳步：

1. **502** → 先等 30 秒重试。它是间歇性的，多半自己好。连续 5 次都 502 才继续往下。
2. 还 502 → 确认 `sandbox-cli` 进程在（任务管理器搜 `sandbox-cli`），
   它重启后端口会变（`64242` → 新端口），环境变量会自动更新，不用手动改。
3. **证书错误** → 检查这两项配置还在不在：`git config --global --get-regexp "sslBackend|sslCAInfo"`。
   证书文件可能被清理，重新跑上面的 PowerShell 导出即可。
4. **`CRYPT_E_NO_REVOCATION_CHECK`** → 说明 `sslBackend` 又变回 schannel 了，改回 openssl。

## 附：Steam++ 的两个事实

- 端口 `26561` **写死**在 `%LOCALAPPDATA%\Steam++\Plugins\Accelerator\Settings\ProxySettings.json`
  的 `SystemProxyPortId` 字段，不会变。
- `ProgramStartupRunProxy = false`，**不会开机自启**。因此不能指望它作为 git 的长期代理依赖——
  这也是最终方案没有走 Steam++ 的原因之一。

## 附：本次推送用过的账号凭据

推送时用的 token 属于 `wonhoyeon123`，对该仓库有 `push` 权限。
token 未写入任何配置文件（当时是 URL 内嵌传参，未落盘），临时文件已删除。
`git remote -v` 里是干净的公开 URL，不含凭据。
