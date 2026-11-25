# AGENTS.md — 接手这个仓库前必须先读

## 0. 最重要的一条：内核正在被别人改，别碰

**`recognizer.py`、`reasoner.py`、`schemas.py`、`reasoning/` 属于"内核"，当前由另一位同事在改。**
如果你是被派来做前端的（界面、交互、桌面壳、样式、打包启动体验），那你的边界到这里就结束了。

### 硬约束（不要用"顺手优化"绕过）

| 你可以改 | 你不可以改 |
| --- | --- |
| `workbench/static/**`（整个前端） | `recognizer.py`（B 层识别引擎） |
| `workbench/desktop.py` 及桌面启动相关脚本 | `reasoner.py`（C 层 refine） |
| `scripts/launch*.ps1`、`package.ps1`、`make_zip.py`、`check_kernel.py` | `schemas.py`（跨层数据结构） |
| `README.md` / `docs/` 里**只讲界面与用法**的章节 | `reasoning/**`（C 层规则、契约、校验） |
| `tests/` 里**只测前端/接口契约**的新文件 | `workbench/full_page.py`、`workbench/fix.py`（识别编排与修复提示词） |

理由：这些文件里正在发生真实的算法改动（候选选择、`0/o` 混淆检测、MLP、结构校验）。
两边同时改同一个文件，冲突不是"合并一下"那么简单——会把别人没跑完的实验一起提交上去。

### 如果确实必须动内核

不要直接改。先在对话里说明**为什么要改、改哪一行、影响谁**，等对方确认。

### 怎么确认内核有没有被动过

动手前先跑一遍：

```powershell
python scripts/check_kernel.py
```

全绿 = 内核跟基线一致，你只改前端就不会碰到别人的活。
飘红 = 有内核文件跟基线不同，**先停下来问**，不要自己判断"应该是小事"。

> **不要用 `sha256sum` / `Get-FileHash` 直接算。** Windows 上 Git 默认
> `core.autocrlf=true`，同一个提交 checkout 出来可能是 CRLF 也可能是 LF，
> 直接算哈希会有几个文件"永远对不上"，看着像代码被改了，其实一个字没动。
> `check_kernel.py` 会先把行尾统一成 LF 再比，结论才可信。

基线由脚本里的 `KERNEL_BASELINE_COMMIT` 指定——直接取那个提交里**真实存在的文件内容**
来算指纹，不再手抄哈希。看到飘红时的正确反应是**问**，不是把文件改回基线——
如果内核同事确实推进了一版，基线该由他更新，你改回去等于把他的工作抹掉。

> **2026-11-25 修过一处**：早先的写法是把 8 个哈希手抄进 `BASELINE`，结果抄错了两个
> （`recognizer.py`、`workbench/full_page.py` 抄的是 hand2latex-review 上的旧内核，
> 而入库的是 11-25 备份的新内核）。从建库那一刻起这两个文件就一直飘红——
> 不是内核被改，是基线录错了。现在改成从基线提交计算，`tests/test_check_kernel.py`
> 锁住了"兜底值与仓库文件自洽""兜底值与基线提交一致""改动能被检出"三件事，
> 同类的抄错不会再发生。
>
> 要推进基线（内核同事真的改了一版），改 `KERNEL_BASELINE_COMMIT` 与脚本里的兜底值
> **两处一起**，然后跑一遍 `tests/test_check_kernel.py` 确认自洽。不要逐个去抄哈希。

## 1. 前端只许通过 HTTP 接口跟内核说话

界面**不 import** 任何内核模块，一律走 `workbench/app.py` 暴露的 JSON 接口。
这样内核怎么改，界面都不用跟着改；内核那边换实现，界面最多是某个字段暂时空着。

前端当前依赖的接口（改这些接口的**响应字段**等于改契约，要同步告知）：

| 接口 | 前端用它干什么 |
| --- | --- |
| `GET /api/status` | 顶部状态条：密钥有没有配、编译器在不在、字体、并发页数、任务占用 |
| `GET /api/jobs?limit&offset&q` | 左侧任务列表（分页 + 搜索） |
| `GET /api/jobs/{id}` | 打开某个任务，拿到 tex / pages / compile |
| `GET /api/jobs/{id}/pdf` | 右侧 PDF 预览 |
| `GET /api/jobs/{id}/tex` `/original` | 下载当前稿 / 识别原稿 |
| `GET /api/jobs/{id}/pages/{n}/source` | 左侧原图 |
| `POST /api/documents` `/api/documents/batch` | 上传识别（字段名必须是 `image`，可带 `run_id`） |
| `GET /api/runs/{run_id}` | 上传过程中的逐页进度（轮询） |
| `POST /api/jobs/{id}/compile` | 重新排版 |
| `POST /api/jobs/{id}/pages/{n}/retry` | 某页识别失败后重试 |
| `POST /api/jobs/{id}/suggest-fix` `/apply-fix` | AI 修复建议 |
| `GET/POST /api/jobs/{id}/history` `/restore-history` `/restore-original` | 历史版本 |
| `POST /api/jobs/{id}/figures/use-source` | 图形页改用原图 |

**界面不许自己发明"识别置信度百分比"。** 内核不给这种数，界面也不许算。
能展示的只有内核真实返回的东西：编译报错、缺字警告、`human_review`、逐页耗时、token 用量。

## 2. 界面改动要遵守的产品口径

- **不承诺"识别准确"**。文案只能说"识别结果仍需对照原图核对"，不能说"已自动校正"。
- **付费动作要问**。重新识别一页、调用 AI 修复都是花钱的，点之前必须明确确认。
- **错误要说人话**。把 LaTeX 报错翻译成人能懂的一句，但**原文要保留**，让人能核对。
- **别做假进度**。没有逐页进度就直说"正在合并排版"，不要转圈假装有百分比。

## 3. 本地怎么跑起来

```powershell
# 依赖
python -m pip install -r requirements-app.txt

# 起服务（默认 8000）
python -m uvicorn workbench.app:app --host 127.0.0.1 --port 8000

# 浏览器打开 http://127.0.0.1:8000
```

没有 `OPENAI_API_KEY` 时：界面能打开、能看已有任务、能改代码、能编译，
但**上传识别和 AI 修复会如实报"未配置密钥"**——这是预期行为，不是 bug。

## 4. 怎么把成果发给别人看

**不要让对方装 Python、也不要让对方 clone 仓库。** 直接发 zip 安装包，对方解压双击就能跑。

```powershell
# 在自己机器上打包（首次会下载 Python 运行时，之后复用）
powershell -ExecutionPolicy Bypass -File scripts\package.ps1 -IncludeDemoJob c3d4e5f60718293a4b5c6d7e8f901234
```

产物在 `dist\Hand2LaTeX-1.0.0-win64.zip`（约 57 MB）。对方解压后：

1. 双击 `启动工作台.bat` — 后台起服务并自动弹出独立桌面窗口
2. 窗口关掉后服务还留着，双击 `关闭工作台.bat` 收尾

`-IncludeDemoJob` 会把一个已经跑通的任务打进包里，对方打开就能看到真实效果，
不用先配密钥、不用先等识别。**不传这个参数时打包脚本会检查"任务产物为空"**，
避免把自己的实验数据一起发出去。

> 打包用的是 `scripts/make_zip.py` 而不是 `Compress-Archive`。
> 后者写中文文件名时不打 UTF-8 标记位，对方解压出来会看到
> `Õà¦Úù¡ÕÀÑõ¢£ÕŦ.bat` 这种乱码文件名——这是真踩过的坑，别改回去。

## 5. 文档在哪

- `reasoning/CONTRACT.md` — C 层公共契约（**内核同事维护，别改**）
- `reasoning/TEAM_LOG.md` — 团队实际做过什么、验证到哪一步（有证据边界说明）
- `docs/UI_CHANGES_2026-11-25.md` — 这轮界面重做改了什么、为什么改
- `docs/BACKEND_ISSUES_2026-11-25.md` — 后端上传识别链路的已知问题（孤儿目录 /
  只校验扩展名 / 并发编译覆盖），**归后端同事处理**，附复现步骤与实测结果
- `README.md` — 用户视角的完整说明
- `README_B.md` — B 层（本地识别）的说明
