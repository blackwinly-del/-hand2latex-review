# 后端问题（上传识别链路）— 已全部修复

> 记录时间：2026-11-25
> 涉及文件：`workbench/app.py`
> 发现方式：真实运行验证（非读代码推断），每条都附了复现步骤和实测结果
> **状态：四个问题已全部修复并复验**（2026-11-25 同日）。用户明确授权后改的 `app.py`；
> `recognizer.py` / `reasoner.py` / `schemas.py` / `reasoning/` / `workbench/full_page.py` / `workbench/fix.py`
> 这些内核文件仍然一行未动。每节末尾的「修复」写明改法和复验结果。
>
> 前三节（①②③）在上传识别和重新编译的路径上，第四节（④）在**任务列表**路径上——
> 它是整理成果时新发现的，性质是性能而不是功能，所以单独放最后。原始诊断保留在下面
> （作为问题依据），改了什么写在每节末尾的「修复」里，方便对照审阅。

---

## ① 上传失败会在 `artifacts/jobs` 留下孤儿目录

**位置**：`workbench/app.py` 的 `_create_document`，第 624、632-637、717-719 行

**现状**：

```python
job_id = uuid.uuid4().hex
directory = _JOBS_ROOT / job_id
directory.mkdir()                      # 624：目录先建出来

for page_number, (suffix, content) in enumerate(uploads, start=1):
    page_directory = directory / f"page_{page_number:02d}"
    page_directory.mkdir()             # 634
    source_path = page_directory / f"source{suffix}"
    source_path.write_bytes(content)   # 636：源图落盘
...
if not documents:                      # 717
    detail = "；".join(f"第 {f['page']} 页：{f['error']}" for f in failures) or "没有可用页面"
    raise RuntimeError(f"整页识别失败（{detail}），请检查服务配置后重试")   # 719
```

建目录、写源图都在前面，而「所有页都失败」的判定在后面抛出，**全程没有 try/except 清理**。

**复现**：向 `POST /api/documents`（字段名 `image`）依次上传以下 4 个文件：

| 文件 | 内容 | 实际返回 |
| --- | --- | --- |
| `fake.png` | 纯文本改名 | 502 `RuntimeError: 整页识别或编译失败...` |
| `empty.png` | 0 字节 | 502 同上 |
| `evil.png` | 只有 PNG 文件头 | 502 同上 |
| `x.PNG` | 大写扩展名 | 502 同上 |

**实测结果**：4 次请求各留下一个 32 位 hex 的目录，里面只有 `page_01/source.png`，
既没有 `main.tex` 也没有 `main.pdf`：

```
16f827ea00ae42d3b1ebbdacc4453269
42e69ce997b04532bb367be731a74fbb
4cd45226125a467aa52d784ac611ca3a
7eb82d5058c242b194201a7aa355f8fb
```

**影响**：
- 这些目录不会被自动清理逻辑区分对待，`GET /api/jobs` 扫到后会当成正常任务返回，
  列表里出现打不开的条目；
- 用户每失败一次就多一条，长期会持续污染 `artifacts/jobs/`。

**建议**：二选一。
- 保守做法：把从 `mkdir` 到识别完成这一段包进 `try/except`，失败时 `shutil.rmtree(directory, ignore_errors=True)` 后重新抛出；
- 更彻底：**先识别，成功后再落盘**。源图先放临时目录（`tempfile.mkdtemp()`），
  全部成功后再 `mkdir` 正式目录并把文件搬过去。这样连写盘都省了，也不会污染任务列表。

**修复**：采用了第一种（保守做法），第二种**明确弃用**——原因是 `_attach_figure_sources`
会把**绝对路径**的 `source_image` 写进 `document.json`，供 `\includegraphics` 使用；
「先写临时目录再搬」会让这个绝对路径指向已删除的临时目录，图形页会静默变成空白。

实现：`_create_document` 里目录建出来之后的整段包进 `try/except BaseException: _discard_job_directory(directory); raise`。
`_discard_job_directory` **只在目录里还没有 `main.tex` 时才删**——万一失败发生在很靠后的位置
（比如 tex 已落盘、compile 才抛错），那个任务至少有代码可看，不该被当垃圾删掉。

复验：`test_batch_upload_all_pages_fail_returns_422_and_cleans_up` 断言失败前后 `artifacts/jobs`
目录集合完全相同；真实 HTTP 上传两张合法 PNG（所有页都失败）后 `GET /api/jobs` 的 `total` 保持 0。
另外核对过：清理逻辑没有误删——原有的 10 个完整任务（各有 `main.tex` + `main.pdf`）全部存活。

---

## ② 上传只校验扩展名，不校验文件头

**位置**：`workbench/app.py:605-612` 的 `_read_image`

```python
def _read_image(image: UploadFile) -> tuple[str, bytes]:
    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in _SUPPORTED_SUFFIXES:          # 607：只看扩展名
        raise HTTPException(status_code=400, detail="仅支持 PNG、JPEG、WebP 图片")
    content = image.file.read(_MAX_IMAGE_BYTES + 1)
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="图片不能超过 20 MB")
    return suffix, content
```

`_SUPPORTED_SUFFIXES` 是 `{".png", ".jpg", ".jpeg", ".webp"}`，只比对文件名后缀。

**复现**：新建一个文本文件 `echo "not an image" > fake.png`，上传。

**实测结果**：通过 `_read_image` 校验，一路走到识别阶段才失败，返回
`502 {"detail":"RuntimeError: 整页识别或编译失败，请检查服务配置后重试"}`。

**影响**：这条 502 文案会把用户引向「检查密钥 / 检查 tectonic 装没装」，而真实原因是
文件根本不是图片。排查方向完全跑偏，且这类请求会消耗一次识别调用的配额（如果是真图片
格式损坏，可能还要等云端返回）。

**建议**：在 `_read_image` 里补 magic bytes 校验，不匹配直接 400：

| 格式 | 文件头 |
| --- | --- |
| PNG | `89 50 4E 47 0D 0A 1A 0A` |
| JPEG | `FF D8 FF` |
| WebP | `52 49 46 46`（RIFF）……第 8-11 字节 `57 45 42 50`（WEBP） |

```python
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
}
# WebP 需要额外看偏移 8 处的 b"WEBP"
```

校验失败返回 400「这不是有效的图片文件」，前端就能准确提示，不用靠 502 去猜。

**修复**：按上面的表补了 `_sniff_image_suffix`，PNG / JPEG / WebP 三种文件头都校验；
WebP 特意同时看 `RIFF`（0-3）**和** `WEBP`（8-11）——只认 RIFF 不够，WAV 也用 RIFF 容器。
另外补了空文件检查（`文件是空的`）。

顺带修了一个相关问题：返回的不再是**文件名后缀**，而是**识别出的真实格式**。
所以一个叫 `.png` 其实是 JPEG 的文件会存成 `source.jpg`，落盘格式和实际内容一致
（以前会存成 `source.png`，某些工具按扩展名解码就会失败）。

复验（解压后的发行包上跑真实 HTTP）：
- 文本改名 `.png` → `400 这不是有效的图片文件（fake.png）：内容是 PNG / JPEG / WebP 之外的格式…`
- 空文件 → `400 文件是空的（empty.png），请重新导出后再上传`
- `.png` 名 + JPEG 内容 → 落盘为 `source.jpg`（`test_jpeg_content_saved_with_true_suffix`）

---

## ③ 同一任务并发编译会互相覆盖，且两个请求都报成功

**位置**：`workbench/app.py:1115-1141` 的 `compile_document`

**现状**：没有按 `job_id` 加锁。两个请求同时到达时，都会读 `main.tex`、各自
`_write_main_tex`、各自调 `compile_tex`，后写的覆盖先写的。

**复现**：对同一个 job 并发发两个 `POST /api/jobs/{id}/compile`，
一个在 tex 末尾加 `%A`，一个加 `%B`。

**实测结果**：

```
A: 200  {"compile":{"success":true,...}}
B: 200  {"compile":{"success":true,...}}
磁盘上 main.tex 末尾 = "%B"
```

两个请求都返回 200 且都声称 `success: true`，但 A 那版内容已经不存在了。
A 拿到的 200 是**假成功**——它以为「我提交的这版已经编译并落盘了」。

**影响**：前端网络重试、或用户连点两下「重新排版」，都可能触发。用户看到的表现是
「点了重新排版，PDF 却变成了别的版本」，而且没有任何错误提示，很难复现和解释。

**建议**：二选一。
- 简单：按 job 加一把锁，和现有 `_RUNS_LOCK`（第 141 行）同样思路，
  用 `dict[str, threading.Lock]` + 一把元锁，或 `defaultdict`；
- 更稳：乐观锁。写之前记录 `main.tex` 的 sha256，写时比对，不一致返回
  `409「源码已被其他操作修改，请重新加载」`。

注意 `compile_document` 前面有一段「代码没变就复用上次结果」的短路逻辑（1123-1131 行），
加锁时要把这段也包进去，否则并发下两个请求会同时判定「需要重新编译」。

**修复**：用了第一种（按 job 加锁）。`_JOB_WRITE_LOCKS: dict[str, threading.Lock]` +
一把 `_JOB_WRITE_LOCKS_GUARD` 元锁做惰性创建——**元锁不能省**：没有它，两个线程可能同时
发现「这个 job 还没锁」而各自 `threading.Lock()` 一个，拿到两把不同的锁，等于没加锁。

按上面那条提醒，**「复用上次编译」的短路判断被移到了锁内**（`_compile_locked`），
否则并发下两个请求会同时判定「需要重新编译」。同样处理的还有另外 4 个写接口：
`restore_original_tex`、`restore_history`、`apply_document_fix`（它的 `baseline_sha256`
比对也在锁内）、`use_source_figures`。

复验：三路并发编译（三份不同内容），三个请求都 200，且**磁盘上的 PDF 内容与 `main.tex`
一致**——判据用的是这个真正重要的事实，而不是「都返回 200 就算过」。
`test_concurrent_compile_does_not_lose_writes` 覆盖了这条。

---

## ④ 任务列表越用越慢（性能缺陷）

**位置**：`workbench/app.py` 的 `_job_metadata`（原第 528 行附近）

**现象**：任务攒多以后打开网页左侧列表明显卡顿。造 300 个任务后实测
`GET /api/jobs` 需要 **2198 ms**。

**根因**：这四行里最后一行的问题——

```python
metadata.setdefault("title", _read_job_title(directory))
metadata.setdefault("page_count", 1)
metadata.setdefault("pages", [])
metadata.setdefault("has_figures", _has_figure_blocks(directory))   # ← 这里
```

`setdefault(key, default)` 的 `default` 参数是**先求值、再传进去**的。所以即使
`job.json` 里早就写好了 `has_figures`，`_has_figure_blocks(directory)` 照样完整执行一遍：
对每个任务 `glob("page_*/document.json")` 并逐个 `json.loads`。任务越多越慢，
和磁盘速度无关，是纯浪费。`_read_job_title` 同理（要读 `main.tex` 全文做正则）。

**修复**：改成「键缺失才算」，逻辑完全等价：

```python
if "title" not in metadata:
    metadata["title"] = _read_job_title(directory)
metadata.setdefault("page_count", 1)
metadata.setdefault("pages", [])
if "has_figures" not in metadata:
    metadata["has_figures"] = _has_figure_blocks(directory)
```

**复验**：300 个任务 **2198 ms → 447 ms（4.9 倍）**。拆开计时，`_has_figure_blocks`
一项就占 2198 ms 里的 **1335 ms（61%）**，与「每个任务都在重新解析 document.json」的判断吻合。

**回归测试**：`test_job_metadata_does_not_recompute_has_figures_when_present`，
用 `mock.patch("workbench.app._has_figure_blocks")` 断言「键已存在时一次都不该被调用」，
并**反向断言「键缺失时应该调用一次」**——只测前者的话，把这个函数改成永不调用也能通过，
那就把功能测没了。

**为什么这条值得单独记**：它不是「某个功能不好用」，而是**每次打开网页都在付费**，
而且随使用时长线性恶化。用户不会报这个 bug，只会觉得「这软件有点卡」。

**还剩什么没做**：447 ms 里剩下的是每任务 4 次 `is_file()` + 1 次 `job.json` 解析 + 1 次
`stat`（实测单任务约 1.4 ms 纯系统调用，300 个正好约 420 ms）。要进一步降到 50 ms 量级，
需要在进程内维护 `{job_id: (mtime, summary)}` 缓存、只在 `st_mtime` 变化时重读。
这次没做，因为它需要一个「缓存失效」的正确性论证，不适合和缺陷修复混在一个改动里。

---

## 附：这一轮改了什么（完整清单）

三个后端功能问题修完后，用户明确要求「如果能改请帮我用力完善一下，优化界面」，
后来又要求「把成果整理一下」——整理时又发现了第四节那个性能问题。因此这一轮的改动范围是：

| 文件 | 改动 |
| --- | --- |
| `workbench/app.py` | 三个功能问题的修复：`_discard_job_directory` 孤儿目录清理、`_sniff_image_suffix` 文件头校验、`_job_write_lock` 每任务写锁；`_AllPagesFailed` → 422 而不是 502（502 表示服务配置坏了，全部页识别失败属于这次上传不成立，报 502 会把人引去查密钥）。**加上性能修复**：`_job_metadata` 不再用 `setdefault(key, 昂贵函数())`，300 个任务时 `/api/jobs` 从 2198 ms 降到 447 ms。 |
| `workbench/desktop.py` | `_port_available` 在 Windows 上用 `SO_REUSEADDR` 会把**已被占用**的端口判成空闲，导致 uvicorn bind 失败、用户白等几十秒；改用 `SO_EXCLUSIVEADDRUSE`。另外补了 pid 文件读写：桌面模式原本不写 pid，`关闭工作台.bat` 停不掉服务，用户以为关了其实还在跑，再双击又多一个进程。写的是**子进程 uvicorn 的 pid**，因为 `launch.ps1` 的 `Get-RunningServerProcess` 会校验命令行含 `workbench.app`。 |
| `scripts/launch.ps1` | `Test-PortFree` 的 `TcpListener.Start()` 在 Windows 上有同样的误判，改成 `TcpClient.BeginConnect` 主动连一下。 |
| `workbench/static/index.html` | 界面优化，见 `docs/UI_CHANGES_2026-11-25.md`。 |
| `tests/test_workbench_app.py` | 适配文件头校验（假图片数据换成合法 PNG）；新增 5 个回归测试（4 个功能 + 1 个性能）；**加了 `tearDown` 清理**——这些测试走真实接口，落盘位置就是产品在用的 `artifacts/jobs`，以前每跑一次就在用户侧栏里多出几条「测试笔记」「第一页」。套件从 29 个用例增至 30 个，`test_workbench_app` + `test_workbench` 合计 **63/63 通过**。 |
| `scripts/package.ps1` | 汇报文档此前只存在于 zip 内部、源码树里没有源文件，既进不了版本管理也容易漏打；改为自动取 `docs\成果汇报_*.md` 最新一份，并把「包里有汇报文档」加入打包后的核对清单（漏了直接报错）。 |

内核文件（`recognizer.py`、`reasoner.py`、`schemas.py`、`reasoning/`、`workbench/full_page.py`、
`workbench/fix.py`）**一行未动**，遵守 `AGENTS.md` 的边界。
（`scripts/check_kernel.py` 报的 `recognizer.py` / `full_page.py` 与基线不一致，那是内核同事在改，不是本轮改动。）
