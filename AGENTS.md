# AGENTS.md — 接手这个仓库前必须先读

## 0. 最重要的一条：内核正在被别人改，别碰

**`recognizer.py`、`reasoner.py`、`schemas.py`、`reasoning/` 属于"内核"，当前由另一位同事在改。**
如果你是被派来做前端的（界面、交互、桌面壳、样式、打包启动体验），那你的边界到这里就结束了。

### 硬约束（不要用"顺手优化"绕过）

| 你可以改 | 你不可以改 |
| --- | --- |
| `workbench/static/**`（整个前端） | `recognizer.py`（B 层识别引擎） |
| `workbench/desktop.py` 及桌面启动相关脚本 | `reasoner.py`（C 层 refine） |
| `scripts/launch*.ps1` 里**只涉及启动方式**的部分 | `schemas.py`（跨层数据结构） |
| `README.md` / `docs/` 里**只讲界面与用法**的章节 | `reasoning/**`（C 层规则、契约、校验） |
| `tests/` 里**只测前端/接口契约**的新文件 | `workbench/full_page.py`、`workbench/fix.py`（识别编排与修复提示词） |

理由：这些文件里正在发生真实的算法改动（候选选择、`0/o` 混淆检测、MLP、结构校验）。
两边同时改同一个文件，冲突不是"合并一下"那么简单——会把别人没跑完的实验一起提交上去。

### 如果确实必须动内核

不要直接改。先在对话里说明**为什么要改、改哪一行、影响谁**，等对方确认。
内核文件的当前指纹（改动前后请核对，对不上说明这段代码已经不是你以为的样子）：

```
recognizer.py             d4fab5ffb65e5642e179894f5c1d93979d93b84f68dd663b9ad34a91ae96d321
reasoner.py               47580f7e58fb1c7637993b9118e34bc8b3be55daf589a9b373ca6481d2846ea2
schemas.py                cd3763eae4a5592c6d82017c4988eb8efec668ad2d1005a38aae0b2a04f1203b
reasoning/validators.py   97a4371d5db05c3c5286d7963dc5f8bd01cfb8f0c7a23facc47a5af9f9f70e1e
reasoning/context.py      9bcfc60bc29957490090ad0b604f67a5bd3e3800d6c9f66254dba68dd39d6468
reasoning/render_check.py 8e4b4c9556e54c9d238371b5b37fd2a8dda099346c25b1d33f9eb45f63938a80
workbench/full_page.py    d3f8d4f9269a63b93af2d5caefe5a44788e33eec7755704de166f748ced2509e
workbench/fix.py          ed7610feadaab55470e5a9801daf0c66d9b50bf57564149f568f246898aa4c6e
```

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

## 4. 文档在哪

- `reasoning/CONTRACT.md` — C 层公共契约（**内核同事维护，别改**）
- `reasoning/TEAM_LOG.md` — 团队实际做过什么、验证到哪一步（有证据边界说明）
- `README.md` — 用户视角的完整说明
- `README_B.md` — B 层（本地识别）的说明
