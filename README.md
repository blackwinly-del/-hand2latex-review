# Hand2LaTeX 手写公式识别与整页排版工作台

把手写图片转成可编译、可复核的 LaTeX / 中文 PDF。整条链路是：

```text
手写图片
  → 识别引擎生成 LaTeX 候选（B：recognizer.py，PP-FormulaNet-L）
  → 规范化、去重、结构检查、上下文选择（C：reasoner.py + reasoning/）
  → 整页识别、错误定位、AI 建议、人工确认后局部修正（workbench/）
  → Tectonic + ctex 编译中文 PDF，预览与导出
```

## 一、当前状态：已验证 vs 尚未证明

这份仓库给审阅者看的是**真实状态**，不是宣传稿。下面两张表请一起看。

### 已经实现并有本地证据

> **关于表中「证据」列的一点更正（2026-11-25）**：标了 `artifacts/...` 的那几行，
> 对应文件**当前不在工作区**，也不在备份里（核对过 `h2l-backups/h2l-work-2026-11-25.zip`）。
> 也就是说这些条目"实现过、跑通过"，但**证据文件没能留下来**，本机无法直接复现。
> 标了 `tests/xxx.py` 的条目不受影响——那些测试现在全部通过（215 个用例，0 错误，15 个按条件跳过）。
> 缺失文件完整清单（11 个）与处理选项见 `docs/成果汇报_2026-11-25.md` 的 7.2 节。

| 能力 | 入口 | 证据 |
| --- | --- | --- |
| 公式图片 → LaTeX 候选列表（5 字段契约） | `recognizer.recognize()` | `tests/test_recognizer.py` |
| 候选规范化、按 `strip` 后完整字符串去重 | `reasoner.refine()` | `tests/test_reasoner.py` |
| 括号 / `\left\right` / `\begin\end` / 命令参数数量结构检查 | `reasoning/validators.py` | `tests/test_validators.py` |
| `0/o` 易混淆字符漏报检测 | `find_ambiguous_glyph_conflicts()` | `tests/test_validators.py` |
| 多模态大模型按编号选候选（只选不改） | `reasoning/context.py` | `tests/test_context.py` |
| KaTeX 渲染可行性检查 | `reasoning/render_check.py` | `tests/test_render_check.py` |
| 错误率 / 误改写率 / 复核率评估口径 | `reasoning/evaluate.py` | `tests/test_evaluate.py` |
| 单页整页识别（中文 + 公式 + 图片占位） | `workbench/full_page.py` | `artifacts/full_page_browser_acceptance.json` |
| 多页上传、按上传顺序合并、页间插入 `\newpage` | `workbench/app.py` `/api/documents/batch` | `artifacts/batch_browser_acceptance.json` |
| 4 张真实手写页的多页结构评估（顺序、分页、编译、页数、忠实空白页） | `workbench/multipage_eval.py` | `artifacts/multipage_real/report.json` |
| 编译失败片段定位 + AI 建议 + 人工确认局部修正 | `/api/jobs/{id}/suggest-fix`、`/apply-fix` | `tests/test_workbench_app.py` |
| Tectonic + ctex 真实中文 PDF 编译与预览、下载 | `workbench/compiler.py` | `tests/test_workbench.py` |
| 显式空白页（`blank_page` → `\null`）忠实排版 | `workbench/full_page.py` | `tests/test_workbench.py` |
| 多页整页识别并行执行（默认 3 路，`WORKBENCH_PAGE_CONCURRENCY` 可调） | `workbench/app.py` | `tests/test_workbench_app.py`；2026-11-23 浏览器实测 2 页（2.0 s + 1.0 s）合计 2036 ms 完成，小于串行的 3000 ms |
| 运行进度登记与轮询（逐页状态、逐页耗时、总耗时） | `GET /api/runs/{run_id}` | `tests/test_workbench_app.py` |
| 系统状态面板，只报可核查事实（版本/提交、Python、密钥是否配置、Tectonic 版本、字体集、前端来源、任务目录） | `GET /api/status` | `tests/test_workbench_app.py` |
| 逐页真实识别信号（`finish_reason`、真实 token 用量、是否接近输出上限、重试次数、块统计、耗时） | `workbench/full_page.py` | `tests/test_workbench.py` |
| TeX 一字未改时复用上一次 PDF，不重跑 Tectonic | `workbench/app.py` | `tests/test_workbench_app.py` |
| 改稿便捷性：`Ctrl+S` 编译、`F2` 跳下一处复核（带"第 N / M 处"计数）、浏览器草稿自动保存与恢复、历史版本回滚 | `workbench/static/index.html` | 2026-11-23 Playwright 实测 |
| 打包成绿色 zip（随包带 Tectonic 与 `vue.global.js`，逐项核对 + 密钥泄漏扫描） | `scripts/package.ps1` | `dist/Hand2LaTeX-1.0.0-win64.zip`，56.8 MB；2026-11-25 解压到独立目录后起服务实测：`/` 返回 200、`/api/jobs` 为空、pid 文件指向 uvicorn 子进程、退出时自动清理 |
| 编译出 setup.exe 安装器（免管理员、装到用户目录、中文安装界面、卸载时问要不要删任务产物） | `scripts/package.ps1 -BuildInstaller` + `installer/hand2latex.iss` | `dist/Hand2LaTeX-1.0.0-win64-setup.exe`，15.5 MB，SHA256 `7BDC80C048D857556142235906065E22BF8D4AE97BF2ACED2BC4985A4C6A8D71`；2026-11-23 静默装机 + 起服务 + 静默卸载实测通过 |
| 真实付费 API 下的并行提速与真实信号采集（3 页真实手写笔记，并发 3 与串行各跑一轮） | `workbench/app.py` + `workbench/full_page.py` | `artifacts/real_api_parallel/summary.json`：82.7 s vs 232.7 s，**实测提速 2.81 倍**；两轮 completion token 合计 91402，`finish_reason` 全为 `stop`，无重试 |

### 尚未实现或尚未证明（审阅时请重点看这里）

- **整页转录准确率没有真值集**，因此所有"识别效果"都只是人工观察，不是指标。
  2026-11-17 的 4 张真实页多页评估已跑通（三组结构全过，见第九节），但它只证明结构链路，
  **不证明转录逐字正确**；首次因 402 失败的记录保留在 `artifacts/multipage_real/report_initial_real.json`。
- **远端整页识别不是确定性的，这一点已有两次真实运行的对照证据**：同样 3 张手写页、同一模型跑两轮，
  块数量与 TeX 长度都不一样（第 2 页 `display_formula` 一轮 16 个、另一轮 8 个；TeX 2799 字符 vs 3052 字符）。
  没有真值集，**无法判断哪一轮更接近原文**，所以"重试这一页"会得到不同结果，每页也都标 `human_review=required`。
  更早的证据：`page_3` 曾因推理 token 耗尽输出预算返回空内容，放宽后重试才成功。
- 跨页**语义**一致性（跨页公式续写、符号统一）未实现；当前只保证合并顺序和分页。
- 手绘图形只输出文字描述占位，不重绘。
- 第二个识别引擎（UniMERNet）只在 `recognizer.py` 里留了槽位，未接入，因此没有跨引擎投票。
- MLP 风险打分仅用于学习演示，`risk_score` 在生产路径恒为 `null`。
- 远端整页识别的多页并行已有**真实 API 实测**：3 页并发 3 用 82.7 s，同样 3 页串行用 232.7 s，提速 2.81 倍
  （三页的开始时刻相差 13 ms 以内，客户端轮询也看到同时 3 页在跑）。但**并行度上限没有压测**，
  没测过 10 页以上的大批量，也没遇到过网关限流，所以"调大并发一定更快"这句话还没有证据；
  本地画板识别仍是单张串行，CPU 推理和 Tectonic 编译都慢。
- 安装器只做过**静默安装 / 静默卸载**的验证（装到临时目录、跑通、卸干净）；带界面的安装向导
  （选目录、勾桌面快捷方式、卸载时问要不要删 `artifacts`）**没有人工点过一遍**，只做了代码审阅。
  安装包里不含 Python，目标机器没有 Python 3.10~3.12 时仍然跑不起来。
- 状态面板、进度条、逐页信号和改稿便捷性的**浏览器验收是在 mock 识别 + mock 编译下做的**；
  真实 API 只跑过服务端链路（上传→并行识别→信号落盘→编译→编译复用），没有同时在浏览器里点一遍。
  真实运行里 `near_token_budget` 六页全为 `false`（最高一页用了输出预算的 84%），所以"接近预算"这条告警
  **只有 mock 证据，真实触发过一次都没有**。

## 二、项目结构

```text
.
├── recognizer.py              B：图片 → LaTeX 候选列表（不调大模型、不校验结构）
├── reasoner.py                C：候选 → 规范化 / 去重 / 结构检查 / 上下文选择，生产入口 refine()
├── schemas.py                 A / B / C 三人共享的数据契约（改动需三人同意）
│
├── reasoning/                 C 模块内部实现
│   ├── CONTRACT.md            C 公共契约讨论稿 v0.3（1—12 节已实现，13—16 节含提案）
│   ├── TEAM_LOG.md            项目决策 / 改动 / 审核 / 测试的真实流水日志
│   ├── context.py             OpenAI 兼容的多模态上下文候选选择
│   ├── validators.py          结构检查 + 易混淆字符冲突检测
│   ├── evaluate.py            评估指标（错误率、误改写率、复核率等）
│   ├── render_check.py        KaTeX 渲染可行性检查（Node 子进程）
│   ├── context_benchmark.py   上下文选择基准，读写 artifacts/ 下的 JSON
│   ├── features.py            MLP 结构化特征提取（教学用）
│   ├── risk_mlp.py            固定权重的 MLP 前向（教学用）
│   └── train_risk.py          教学用训练循环
│
├── workbench/                 FastAPI 网页工作台
│   ├── app.py                 单页 / 多页上传、编译、建议修正、应用修正、PDF 下载
│   ├── full_page.py           整页识别、LaTeX 文档生成、多页合并
│   ├── compiler.py            Tectonic + ctex 编译，PDF 页数与空白页判定
│   ├── fix.py                 编译错误片段定位、建议与会话校验（防止过期建议覆盖）
│   ├── multipage_eval.py      可恢复的真实多页评估器（带响应缓存）
│   ├── version.py             版本号（打包脚本从这里读，也写进 BUILD_INFO.json）
│   └── static/index.html      Vue 3 前端单页
│
├── tests/                     14 个 unittest 测试模块（180 项）+ test_recognizer.py 契约自检脚本（`python -m unittest discover -s tests`）
├── data/
│   ├── handwritten/           12 张真实手写公式样本 sample_1 ~ sample_12
│   ├── pdf_pages/             真实笔记分页图 page_1 ~ page_5（多页评估素材）
│   └── multipage_samples.json 多页评估用例清单（合并顺序 / 倒序 / 尾部空白页）
├── samples/                   单张打印体测试图
├── docs/
│   ├── Hand2LaTeX_功能演示文档.docx   中文演示稿（含真实截图证据）
│   └── assets/                演示文档引用的图片
├── artifacts/                 真实运行产物（评估 JSON、验收 JSON、编译样例）
├── scripts/
│   ├── launch.ps1             一键体检 / 装环境 / 启动 / 重启 / 停止的实际逻辑（安装包里有随包运行时时跳过建 venv 与装依赖）
│   ├── launch_demo.ps1        画板演示的启动逻辑（前台窗口运行，关窗即停）
│   ├── build_python_runtime.ps1 构建随包 Python 运行时（下载 embeddable 包并按官方 MD5 校验、预装依赖、导入自检）
│   └── package.ps1            打包成 dist/ 下的绿色 zip（可选 -BuildInstaller 编 setup.exe、-NoPython 打瘦包）
├── installer/
│   ├── 安装说明.txt            给最终用户看的中文说明（会随包分发）
│   ├── hand2latex.iss         Inno Setup 6 脚本（2026-11-23 用 ISCC 6.7.3 编译并实装验证过）
│   └── languages/
│       └── ChineseSimplified.isl  官方简体中文安装界面消息（Inno Setup 安装器不自带，随仓库带一份）
├── 启动工作台.bat              双击入口（ASCII 内容，中文界面由 launch.ps1 输出）
├── 启动画板.bat                双击打开画板演示（Streamlit，默认 8501 端口）
├── 关闭工作台.bat              双击停止服务
├── README_B.md                B 模块的详细说明与环境变量表
├── requirements.txt           Web 工作台 + C 模块依赖
├── requirements-app.txt       随包 Python 运行时只装这一份（不含 torch / numpy / Pillow，理由写在文件里）
└── requirements-b.txt         PP-FormulaNet-L 本地推理依赖（paddlepaddle / paddleocr）
```

## 三、环境要求

| 项目 | 要求 |
| --- | --- |
| Python | **3.10 / 3.11 / 3.12**。PaddlePaddle 不支持 3.13。⚠️ `requirements.txt` 里 `numpy==2.3.5` 仅支持 3.11+；如需在 3.10 上运行，需自行把 numpy 降到 2.2.x。 |
| Node.js | 18+，前端 Vue 与 KaTeX 渲染检查都从 `node_modules` 读取 |
| 操作系统 | 开发在 Windows 完成；Linux/macOS 需要自行替换 Tectonic 可执行文件 |
| Tectonic | 0.17.0，放在 `tools/tectonic/tectonic.exe`（该目录被 `.gitignore` 排除，需自备） |
| 中文字体 | ctex 默认用 `fontset=windows`，需要系统装有 SimHei/SimSun 等 CJK 字体。**没有预装中文字体的环境**（Linux/macOS/CI runner）可设环境变量 `LATEX_FONTSET=fandol`，改用随 Tectonic TeX bundle 分发的开源 Fandol 字体，无需系统字体。合法值：`windows` / `mac` / `adobe` / `ubuntu` / `fandol` / `none`。 |
| 模型权重 | PP-FormulaNet-L 约 695 MB，放 `models/PP-FormulaNet-L/`（同样被排除，首次运行可自动下载） |
| 多模态 API | 任意 OpenAI 兼容接口，需支持图片输入 |

上表是**从源码开发**时的要求。用 `scripts/package.ps1` 打出来的安装包不需要目标机器装 Python、
Node.js 或 Tectonic：Python 3.12 运行时（embeddable + 预装 `requirements-app.txt`）、`vue.global.js`
和 `tectonic.exe` 都随包带。**只有画板演示与 B 侧本地识别不在覆盖范围内**——它们要 paddle / torch
和约 3 GB 模型，仍然得按本节和第四节装完整环境。

## 四、安装

```bash
# 1. 虚拟环境（务必先建 venv 再装包）
python -m venv .venv
./.venv/Scripts/python.exe -m pip install --upgrade pip   # Linux/macOS 用 ./.venv/bin/python

# 2. Web 工作台与 C 模块
./.venv/Scripts/python.exe -m pip install -r requirements.txt

# 3. B 模块本地识别引擎（不需要真模型可跳过，用 RECOGNIZER_BACKEND=mock 联调）
./.venv/Scripts/python.exe -m pip install -r requirements-b.txt

# 4. 前端依赖（vue 的 dist 目录被工作台静态挂载，缺了页面打不开）
npm install

# 5. Tectonic
#    官方安装脚本：https://tectonic.new  然后把可执行文件放到 tools/tectonic/tectonic.exe
```

国内网络下载 Paddle 模型失败时：

```bash
export PADDLE_PDX_MODEL_SOURCE=BOS      # PowerShell: $env:PADDLE_PDX_MODEL_SOURCE = "BOS"
```

## 五、配置

```bash
cp .env.example .env
```

`.env` 已被 `.gitignore` 排除，**不要把密钥提交上去**。

| 变量 | 说明 |
| --- | --- |
| `OPENAI_API_KEY` | 必填，多模态上下文选择与整页识别都用它 |
| `OPENAI_MODEL` | 支持图片输入的模型名 |
| `OPENAI_BASE_URL` | OpenAI 兼容网关地址，官方接口留空 |
| `OPENAI_TIMEOUT_SECONDS` | 上下文选择超时，默认 30 |
| `FULLPAGE_TIMEOUT_SECONDS` | 整页识别超时，默认 120 |
| `FULLPAGE_MAX_TOKENS` | 整页识别输出上限，默认 24000 |
| `WORKBENCH_PAGE_CONCURRENCY` | 多页整页识别的并行页数，默认 3，取值范围 1~10（再和实际页数取小）；调大更快，但更容易撞网关限流 |
| `WORKBENCH_JOB_MAX_AGE_DAYS` | 过期任务保留天数，默认 7，填 0 表示永不清理 |
| `RECOGNIZER_MODEL` | 代码默认 `PP-FormulaNet-L`，可换 `PP-FormulaNet_plus-L` / `UniMERNet`；本机 `.env` 已设 `UniMERNet` |
| `RECOGNIZER_MODEL_DIR` | 代码默认 `models/<模型名>`；本机 `.env` 指向 `D:/latex/models/UniMERNet` |
| `RECOGNIZER_DEVICE` | 代码默认 `cpu`；本机 `.env` 已设 `gpu:0`，画板启动脚本默认 GPU |
| `RECOGNIZER_BACKEND` | 填 `mock` 返回明确失败候选，仅用于联调失败回退，**不能当作真实识别结果** |

完整 B 侧变量表见 [README_B.md](README_B.md)。

## 六、运行 Web 工作台

上传之后是三栏界面，给不懂 LaTeX 的人也能用：

- **左栏原图**：点某一页，中间代码自动跳到那一页对应的位置（按 `\newpage` 锚点，跳过空行）。
  每页下面显示「N 处待复核」；「标为已核对」按钮用来记录你已经核对过哪几页。
- **中栏代码**：带行号和语法高亮，可直接编辑。编译报错的行标红，**可能需要人工复核的行标黄**。
- **右栏「问题与复核」**：最上面是人工复核清单，只列三种能验证的信号：
  1. 编译器明确报告的缺字/编码问题（带行号，例如 `main.tex:8 Missing character ... U+2208`）；
  2. 已知转写伪影：中文里的 `$` 被转义成 `\$`，说明原文的行内公式被当成了普通文字；
  3. 正文里直接写的数学符号（∈、≤ 等）没有用 LaTeX 写法，换字体后可能缺字。
  下面才是编译错误/警告列表，每条配中文大白话解释，点击跳到对应行。

整页转写现在会原样保留成对的 `$...$` / `$$...$$`，并把正文中的常见 Unicode 数学符号
（∈、≤、∑、π 等）转成 LaTeX 命令；只有落单的 `$`（例如价格）才按普通字符转义。
复核清单仍保留，用于历史任务或远端模型返回其他异常写法时提醒人工。

这些标记覆盖的是"编译器和确定性规则能发现"的问题。**没有标记不等于抄对了**：
识别内容是否忠实只能靠人对照原图判断，界面不显示置信度，也不编造风险分数。

任务与复核管理（2026-11-21 补齐）：

- 上传区可打开最近任务，支持按标题/任务号搜索和分页；当前任务写入地址栏 `#job=<job_id>`，
  **刷新、后退、前进都会按地址恢复**。每页“标为已核对”按任务保存在浏览器 localStorage，刷新不丢。
- 可下载当前 `.tex` 和最初识别原稿；“恢复识别原稿”会在确认后覆盖当前修改并重新编译。
- 某页识别失败时，该页显示“重试这一页”：只重新识别失败页，成功页复用已保存的
  `document.json`，不重复调用模型。早期任务若没有这些结构文件，会明确提示整批重传。
- **图形页保留原图**：一页基本就是一张图（一个 `figure` 块，其余是与图注重叠的短标签）时，
  PDF 直接嵌入原始页面图片，跳过重复的标签文字；图文混排页仍保留“未重新绘制”的描述框。
  老任务可点“图形页改用原图”重建，只读已有结构，不调用识别模型。

状态与可信度信号（2026-11-23 补齐）：

- **顶部状态条**：页面加载时读 `GET /api/status`，用圆点显示每一项是好是坏；点“查看详情”看具体值
  （版本与提交号、Python 与平台、云端识别配置、Tectonic 路径与版本、ctex 字体集、本地识别模型、
  并行页数、前端 `vue.global.js` 来自哪里、任务目录与占用空间）。**只显示密钥长度，不显示密钥本身。**
- **识别进行中的实时进度**：每页一行，显示排队/识别中/成功/失败和已用时间；多页是并行发出的，
  所以总耗时接近最慢的那一页，不是各页相加。
- **每页的“识别过程记录”**：只放模型真实返回的东西——`finish_reason`、真实 token 用量、
  输出是否接近上限（≥95% 时标红提示可能截断）、是否重试过及重试次数、各类块的数量、这一页耗时。
  界面同时明说：**系统不给“识别可信度分数”**，因为无法验证，不给假数字。
- **编译复用**：TeX 一字未改就点编译时，直接复用上一份 PDF 并提示“没有再跑一遍 Tectonic”。

改稿便捷性（2026-11-23 补齐）：

- `Ctrl+S` 编译当前代码；`F2` 跳到下一处待复核，界面上会写“正在看第 N / M 处待复核（第 X 行）”，看完回到第一处。
- 编辑内容每 1.2 秒自动存进浏览器 localStorage；和服务器版本不一致时，顶部给出“恢复我的修改 / 丢弃，用服务器版本”。
- “历史版本”标签列出每次写入留下的快照，点一下就回滚（每次写 `main.tex` 都会存一份 `history/<uuid>.tex`，所以这是真的撤销）。

### 6.1 一键启动（Windows，推荐先试这个）

双击仓库根目录的 [启动工作台.bat](启动工作台.bat)，按菜单选：

```text
[1] 体检        只检查环境，不安装、不启动
[2] 打开工作台  桌面窗口（推荐，日常就用它）
[3] 在浏览器打开 网页版，适合排查问题
[4] 重启服务    改完代码后用这个
[5] 查看状态    看服务是否还在运行
[6] 停止服务
```

#### 桌面窗口模式（`-Desktop`）

选 `[2]` 会开一个**独立的桌面窗口**：没有地址栏、没有标签页、没有书签栏，
任务栏里是一个单独的应用图标，关掉窗口服务就一起停。

实现方式是 `python -m workbench.desktop`（见 `workbench/desktop.py`）：

- **优先用系统自带的 Edge 的 `--app` 模式**（Windows 10/11 一定装有 Edge）。
  零安装、零体积，不用为"一个窗口"塞进几十 MB 的框架。
- **装了 pywebview 就优先用它**，能得到真正的原生窗口句柄和最小尺寸限制。
  它只是可选增强，没装不影响使用。
- 窗口使用**独立的用户数据目录**（`%LOCALAPPDATA%\Hand2LaTeX\window-profile`），
  不会往你日常浏览器里塞标签页，也不会带上你平时登录的账号。
- 端口默认 8760，被占用会自动往后找，不会因为端口冲突打不开。

也可以直接用命令行：

```powershell
python -m workbench.desktop                 # 开窗口
python -m workbench.desktop --port 8800     # 指定端口
python -m workbench.desktop --headless-seconds 600   # 只起服务不开窗口（自动化验收用）
```

**还没验证到的**：只在 Windows 11 上实测过 Edge 窗口模式；
macOS / Linux 上会走 pywebview 或退化成默认浏览器打开，这两条路径**没有实测证据**。

它按顺序做这些事，每一步都是幂等的（已就绪就跳过，可反复运行）：

1. 找或建 `.venv`，只接受 Python 3.10 / 3.11 / 3.12（PaddlePaddle 不支持 3.13）；
2. 缺包才 `pip install -r requirements.txt` / `requirements-b.txt`，缺前端才 `npm install`；
3. 没有 `.env` 就从 `.env.example` 复制一份，并检查 `OPENAI_API_KEY` / `OPENAI_MODEL` /
   `OPENAI_BASE_URL` 是否填了（**只显示是否配置和长度，不打印密钥**）；
4. 检查 `tools/tectonic/tectonic.exe` 与 `models/PP-FormulaNet-L` 是否就位；
5. 跑 `tests/test_recognizer.py` 契约自检，不过就不启动；
6. 起 uvicorn，轮询 `/` 直到返回 200 才打开浏览器。

服务在后台运行，PID 和日志分别写在 `.venv/workbench.pid` 和 `.venv/workbench.log`。
也可以跳过菜单直接调用底层脚本：

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -CheckOnly   # 只体检
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1              # 装 + 启 + 开浏览器
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -Restart     # 改完代码重启
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -Status      # 查状态
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -Stop        # 停止（同 关闭工作台.bat）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -Lite        # 只装网页依赖，跳过大包
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/launch.ps1 -NoBrowser   # 启动但不自动开浏览器
```

体检结果分三档：绿色是已就绪，黄色是缺东西但工作台仍能起来（例如没有 Tectonic 就编译不了
PDF），红色是直接退出并给出修复命令。端口被占用时它会拒绝启动并提示换端口，而不是去杀别人的进程。
`-Stop` 和 `-Restart` 只认命令行里确实带 `workbench.app` 的进程：Windows 会复用 PID，
如果 `.venv/workbench.pid` 指向的已经不是工作台（例如那台号被别的程序占了），它只会提示并忽略，
绝不误杀。

### 6.2 手动启动

```bash
./.venv/Scripts/python.exe -m uvicorn workbench.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 <http://127.0.0.1:8000>。

主要接口：

| 方法与路径 | 作用 |
| --- | --- |
| `POST /api/documents` | 上传 1 张图，识别 + 编译（表单字段名 `image`） |
| `POST /api/documents/batch` | 上传多张图，按上传顺序合并成一份 PDF（同字段名 `image`） |
| `GET /api/jobs` | 最近任务列表，支持 `q` 搜索和 `limit`/`offset` 分页（标题、页数、失败页数、更新时间） |
| `GET /api/jobs/{job_id}` | 该 job 的 TeX 源码、源图链接、编译结果（`human_review` 恒为 true）；识别块结构合并在这份 TeX 里，接口不单独返回块数组 |
| `GET /api/jobs/{job_id}/pdf` | 下载编译好的 PDF |
| `GET /api/jobs/{job_id}/tex` | 下载当前 TeX |
| `GET /api/jobs/{job_id}/original` | 下载最初识别原稿 |
| `POST /api/jobs/{job_id}/restore-original` | 恢复原稿并重新编译 |
| `POST /api/jobs/{job_id}/pages/{page}/retry` | 只重试失败页，成功页复用已保存结构 |
| `POST /api/jobs/{job_id}/figures/use-source` | 图形主导页改用原始页面图，不调用识别模型 |
| `POST /api/jobs/{job_id}/compile` | 手工改完 TeX 后重新编译 |
| `POST /api/jobs/{job_id}/suggest-fix` | 让模型给出针对某个错误片段的修改建议 |
| `POST /api/jobs/{job_id}/apply-fix` | 人工确认后应用建议（建议过期返回 HTTP 409） |
| `POST /api/jobs/{job_id}/review` | 保存「哪几页已对照原图核对过」，写进 `job.json` 的 `reviewed_pages` |

`/review` 这个接口是 2026-11-25 加的。此前核对进度只存在浏览器 localStorage
（键名 `hand2latex:reviewed:<job_id>`），换机器、换浏览器、清一次缓存就全没了，
而且不会有任何提示。任务在服务端、进度在浏览器，这个状态的寿命比它描述的东西
还短——做多页笔记的人是"今天核 8 页、明天接着核剩下 2 页"，本来就不该受这个限制。

接口细节：请求体 `{"pages": {"1": true, "2": false}}`；只存 `true` 的页，
传 `false` 是删除该页的键（这样 `job.json` 里只看键就知道进度，不会随页数增长）；
页号超出该任务实际页数返回 400（说明前端状态串了，不能悄悄写进去）；
写操作与 `apply-fix`、`restore-history`、`retry` 共用每任务写锁，因为这些接口
都会整份重写 `job.json`。`GET /api/jobs/{job_id}` 会一并返回 `reviewed_pages`。

浏览器里的 localStorage 仍然保留：断网或后端是旧版时，界面还能用本机记录，
不会因为接口不可用就卡住。打开任务时以服务端为准，服务端没有记录才退回本机缓存
（不做并集——本机多出来的那几个对勾其实没保存，并进去会让用户以为续得上）。

**编译诊断（`compile.diagnostics`）**：`POST /compile`、`GET /api/jobs/{id}` 的
`compile` 里新增这个数组，每条含 `severity`、`line`、`message`、`file`、`snippet`、
`code`、`codes`、`hint`、`located_by`、`context`（出错行前后各两行源码）。
老的 `errors` 字段保持原样不动，前端读到 `diagnostics` 就用、读不到就退回扫日志。

这个字段解决的是三件具体的事，都是实测出来的：

1. **warning 类问题原来一条都进不了 `errors`**。`parse_compile_errors` 的正则带
   `(?!warning:)`，而 `Missing character`（符号在当前字体里不存在）是 warning、
   返回码 0、PDF 照常生成——页面看着正常，某个符号悄悄变成空白。这是最需要提示
   用户去核对的一类问题，却完全不在返回结果里。
2. **消息体经常在下一行**。实测日志长这样：

   ```
   warning: b.tex:4: 
   Missing character: There is no ... (U+20BB7) in font ...;!
   ```

   冒号后面是空的，真正原因在下一行。只按行做正则会拿到空消息，用户看到一行
   没有任何信息的红字。
3. **同一条警告因 rerun 打两遍，同一行多个缺字各打一条**。前者按内容去重；
   后者合并成一条「这一行有 N 个字符在当前字体里不存在：U+8FD9、U+91CC……」——
   实测一页中文能出十几条几乎一样的信息，排成一列完全分不清哪条是哪条。
   合并只对 warning 做，error 一条都不合并（每条的成因不同，合并会抹掉信息）。

行号来源分三种，`located_by` 会标出来：`snippet`（用引擎回显的源码片段在
`main.tex` 里唯一反查到的）、`reported`（编译器直接给的）、`subfile`（子文件
里的相对行号）。第三种不能拿去跳转——多页任务会把每页写成 `page_N.tex` 再
`\input` 进来，`page_1:2` 的 `2` 是子文件的第 2 行，按它跳 `main.tex` 会跳到
完全无关的位置（通常是第 2 行的 `\documentclass`）。

一次上传消耗的 API 量不小（每页一次整页识别），演示前先确认账户余额。

### 6.3 画板演示（Streamlit，鼠标写字即时识别）

双击 [启动画板.bat](启动画板.bat)，浏览器会打开 <http://127.0.0.1:8501>：
在左侧画板用鼠标写公式，停笔约 1 秒，右侧自动给出 LaTeX。识别走本地 PP-FormulaNet-L，
**不消耗多模态 API**；第一次识别要加载模型，较慢属正常。

- 画板在**前台窗口**运行：窗口开着服务才在，关窗或按 Ctrl+C 即停止（与工作台的后台方式不同）。
- 已经在跑时再次双击只会打开浏览器，不会重复启动。
- 缺 `streamlit` / `streamlit-drawable-canvas` 时自动按 `demo/requirements-demo.txt` 安装。
  依赖探测用 `find_spec`，不做裸 import——该组件脱离 Streamlit 运行时 import 会误报
  `asset_dir` 错误，真 import 会把好环境误判成缺包。
- 端口被占用可换：`启动画板.bat -Port 8502`（等价于 `scripts/launch_demo.ps1 -Port 8502`）。
- **默认用本机 GPU**：直接双击 `启动画板.bat` 就会优先使用 `.venv\gpu-venv` 并设置
  `RECOGNIZER_DEVICE=gpu:0`；本机 `.env` 也配置为 `UniMERNet` + `gpu:0`。找不到 GPU 环境时
  自动退回 CPU；`-Cpu` 强制 CPU，`-Gpu` 在 GPU 环境缺失时直接报错。GPU 环境缺画板依赖时，
  按 `demo/requirements-demo.txt` 安装到该环境。页面会显示当前模型和设备。
- 识别模型：存在 `models/UniMERNet` 时启动脚本优先用它（12 样本实测 8/12，高于
  PP-FormulaNet-L 的 5/12，见 9.2）；显式设置 `RECOGNIZER_MODEL` 可切换，页面会显示模型名。

### 6.4 本地公式识别用 GPU（实测，2026-11-19～20）

只影响**本地 PP-FormulaNet-L** 这条链路（画板演示、`recognizer.py`）。Web 工作台的整页识别走远端
`deepseek-flash`，GPU 帮不上忙。

本机是 RTX 5070 Laptop（8 GB，驱动 592.82，计算能力 12.0），Paddle 官方 cu126 轮子不含
Blackwell 内核，需要 **cu129** 构建：

```bat
py -3.12 -m venv .venv\gpu-venv
.venv\gpu-venv\Scripts\pip install paddlepaddle-gpu==3.4.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu129/
.venv\gpu-venv\Scripts\pip install paddleocr==3.7.0 tokenizers ftfy
.venv\gpu-venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
```

两个环境坑（都已复现并处理）：

1. **torch 必须比 paddle 先完成加载**。paddle 先加载会污染 DLL 搜索路径，之后依赖链再
   `import torch` 时找不到 `torch\lib\shm.dll`（WinError 127）。`recognizer.py` 现在在 Windows
   上加载模型前会自动先导入 torch（`_formula_recognition_class`），画板、命令行和评估脚本
   都不用再手动写导入顺序；默认 `.venv` 的真实识别也已实测恢复。
2. `paddleocr==3.7.0` 的公式后处理还缺 `tokenizers` 和 `ftfy`，缺了会在建 predictor 时
   只报笼统的 "A dependency error occurred"。
3. PaddleX 默认缓存到 `%USERPROFILE%\.paddlex`；用户名含中文时 C++ 推理会读不到
   `inference.json`（`json.exception.parse_error.101`）。画板启动脚本已把
   `PADDLE_PDX_CACHE_HOME` 固定到仓库的 `.paddlex`（ASCII 路径）；手动 CLI 可同样设置，
   或把模型复制到项目内的 `models/<模型名>`。

实测同一张 `samples/sample_plus.png`（`RECOGNIZER_DEVICE=gpu:0`）：

| 环境 | 首次（含模型加载） | 第二次（预热后） | 输出 LaTeX |
| --- | --- | --- | --- |
| CPU（`paddlepaddle 3.3.0`） | 30.3 s | 11.7 s | `x^{3}-x^{2}+x^{2}+x-x+3x-3+4` |
| GPU（`paddlepaddle-gpu 3.4.0` cu129） | 12.3 s | 0.62 s | 同上 |

GPU 运行期间 `nvidia-smi` 采样到 35–44% 利用率、约 355 MiB 显存，确认真的在 GPU 上算。
这只是单张样本的单次测量，不构成性能基准。

换用 UniMERNet（本机 12 样本实测更准，见 9.2）：

```bash
# 首次会下载约 1.6 GB 权重；缓存路径保持 ASCII
RECOGNIZER_MODEL=UniMERNet RECOGNIZER_DEVICE=gpu:0 PADDLE_PDX_CACHE_HOME=D:/latex/.paddlex \
  ./.venv/gpu-venv/Scripts/python.exe recognizer.py samples/sample_plus.png
# 下载后把权重放到 models/UniMERNet，画板启动脚本就会优先使用它
```

画板默认就用 GPU 启动（`启动画板.bat`，`-Cpu` 可强制 CPU）。实测浏览器页面显示
“识别模型：UniMERNet · 设备：GPU（gpu:0）”，Streamlit 进程出现在 `nvidia-smi` 的 compute apps 中。
默认 `.venv` 的 CPU 识别也已恢复：`recognizer.py samples/sample_plus.png` 实测模型加载 9.5 s、
推理 26.02 s，输出与 GPU 相同。整页识别仍然走远端 `deepseek-flash`，本机 GPU 只覆盖
单张公式图（B 的 `recognizer.py`），两者不是同一条链路。

### 6.5 打包成安装包（发给不用 git 的人）

```bash
# 默认：打绿色 zip，随包带 Python 运行时（约 65 MB）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1

# 只想打瘦包（约 20 MB，对方要自己装 Python 3.10~3.12）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1 -NoPython

# 打 zip，并顺便编出 setup.exe（本机装了 Inno Setup 6 才行）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1 -BuildInstaller

# Inno Setup 装在非默认目录、也没进 PATH 时，直接指定 ISCC.exe
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1 -BuildInstaller -Iscc "D:\API\Inno Setup 6\ISCC.exe"

# 保留 dist/staging 里的解压态目录，方便自己先跑一遍看看
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1 -KeepStaging

# 把某个已跑通的任务打进包，对方解压打开就有真实效果可看（推荐发给队友时用）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/package.ps1 `
  -IncludeDemoJob c3d4e5f60718293a4b5c6d7e8f901234
```

**发给队友时建议带 `-IncludeDemoJob`。** 否则对方打开是一个空工作台，得先自己有
`OPENAI_API_KEY`、自己拍一张手写图上传，才能看到界面长什么样。带上演示任务后，
解压双击就有完整的三栏内容（原图 / LaTeX / PDF 预览）。

反过来，**不传这个参数时打包脚本会检查"包里的任务产物必须为空"**，
避免把自己的实验数据一起发出去——这是一道保险，不是可有可无的核对。

包里的任务 id 是 `artifacts/jobs/<id>` 的目录名，也可以直接在工作台左侧点开某个任务，
从浏览器地址栏末尾的 `#job=<id>` 拿到那串 32 位十六进制。

随包 Python 运行时由 [scripts/build_python_runtime.ps1](scripts/build_python_runtime.ps1) 构建，
默认 Python 3.12.10 embeddable：从 python.org 下载（缓存在 `.cache/`，第二次不重下）、
**按官方下载页公布的 MD5 校验，对不上就中止**、解压到 `runtime/python/`、改 `python312._pth`
（加 `Lib\site-packages` 与 `..\..`，并启用 `import site`——embeddable 版会忽略 `PYTHONPATH`，
只能写在这个文件里）、然后用构建机的 pip `--target` 装 `requirements-app.txt`，最后用随包
`python.exe` 真跑一次 `import workbench.app` 自检。构建机的 Python 次版本必须与运行时一致
（都是 3.12），否则装进去的 `.pyd` ABI 对不上，脚本会先核对再动手。
运行时约 111 MB（其中 pymupdf 自带 MuPDF 二进制 54 MB、openai 26 MB）。
**构建这一步要联网**（python.org + PyPI）；目标机器不需要联网装依赖。

`-BuildInstaller` 找 ISCC 的顺序：`-Iscc` 参数 → PATH 里的 `iscc` → 三个默认安装目录 →
注册表卸载项里的 `InstallLocation`（本机就装在 `D:\API\Inno Setup 6`，靠这一步才找到）。
安装界面用的简体中文消息文件随仓库带在 `installer/languages/ChineseSimplified.isl`，
因为 Inno Setup 官方安装器**不含**简体中文，不这样做编出来就是英文向导。
安装器里"没检测到 Python"的提示只在瘦包（`-NoPython`）时才会出现——ISPP 在编译期先看
暂存目录里有没有 `runtime\python\python.exe`，带了就不弹。

脚本只读仓库、只往 `dist/` 和 `.cache/` 写，不改源码也不碰 `.env`。它做的事：按第十节的排除清单复制仓库 →
把 `node_modules/vue/dist/vue.global.js` 复制进包里（目标机器**不需要装 Node.js**）→
构建随包 Python 运行时（目标机器**不需要装 Python**，加 `-NoPython` 可跳过）→ 写
`BUILD_INFO.json`（无 BOM 的 UTF-8；网页状态里因此显示“来源：安装包”、打包时的提交号、有没有带运行时）→
放入 `installer/安装说明.txt` → 逐项核对该在的在、不该带的没带 → 扫描我们自己打包的文本文件确认本机的
`OPENAI_API_KEY` 值没有混进包里（扫到就中止）→ 压成 zip 并打印 SHA256。zip 里是一个
`Hand2LaTeX-<版本>-win64` 顶层文件夹，"解压到当前文件夹"也不会把文件撒得到处都是。

2026-11-25 实测产出（当前工作区打的包；目录不是 git 仓库，所以 `BUILD_INFO.json` 里 `commit` 为空）：

- `dist/Hand2LaTeX-1.0.0-win64.zip`，56.8 MB（3047 个条目）。
  解压到独立目录、从解压目录起服务（8877 端口）实测：`/` 返回 200、`/api/status` 报 `build.source = 安装包`、
  `/api/jobs` 返回空列表（新装无残留任务）、`runtime\workbench.pid` 写入的 pid 命令行含 `workbench.app`（能被
  `launch.ps1` 的 `Get-RunningServerProcess` 认出）、`taskkill` 后 pid 文件自动清理。
  同一份解压包上用真实 HTTP 复验后端的三个修复：文本改名 `.png` → 400、空文件 → 400、
  两页都识别失败 → 422 且任务数保持 0（不留孤儿目录）；无头浏览器打开首页 Vue 正常挂载，失败面板逐页显示
  `OPENAI_API_KEY is not configured`（包里不带 `.env`，如实报未配置），`pageErrors` 为空。
  包的正确性证明是上面这些实测行为，不是哈希：`README.md` 自己就在包里，改一个字哈希就变，
  所以这里不记固定值。要校验拿到手的包，取包里的 `BUILD_INFO.json` 看版本与构建时间，或直接解压跑一遍。
- `dist/Hand2LaTeX-1.0.0-win64-setup.exe`，15.5 MB，SHA256 `7BDC80C048D857556142235906065E22BF8D4AE97BF2ACED2BC4985A4C6A8D71`。
  （这个安装器是 2026-11-23 在提交 `8ea79e6` 上打的，**不包含** 11-25 的后端修复与界面改动；要用最新代码请用上面的绿色包，或重跑 `-BuildInstaller`。）
  用 ISCC 6.7.3 编译（`Successful compile`，约 17 s）。静默装到临时目录（退出码 0）后核对：启动/关闭脚本、
  `安装说明.txt`、`BUILD_INFO.json`、`tools\tectonic\tectonic.exe`、随包 `vue.global.js`、`unins000.exe` 都在；
  从安装目录起服务（8015 端口），`/api/status` 报告 `build.source = 安装包`、`commit = 8ea79e6`、
  前端与 Tectonic 路径都在安装目录内、任务目录也在安装目录内、云端识别如实报未配置。
  静默卸载（`/VERYSILENT`）退出码 0：程序文件、`.venv`、各层 `__pycache__`、开始菜单组、注册表卸载项全部清掉，
  事先放进去的 `artifacts\jobs\keepme.txt` **按设计保留**；`[Run]` 两条都带 `skipifsilent`，静默安装不会自动启动工作台。
- 验证过程中真找到并修掉两个缺陷：① 卸载阶段的弹框判断误用了 `WizardSilent`（安装阶段专用），
  静默卸载直接以退出码 1 失败，日志写明 `Cannot call "WizardSilent" function during Uninstall`，改用 `UninstallSilent`；
  ② `[UninstallDelete]` 只删了顶层 `__pycache__`，`workbench\` 和 `reasoning\` 下的没删，卸载后留垃圾。
- 没验证的：带界面的安装向导（选目录、勾桌面图标、卸载时问要不要删 `artifacts`）**没有人工点过**，只做了代码审阅；
  也没在没装过 Python 依赖的干净机器上跑过首次启动。
- 上面两个 SHA256 只对**那一次构建**有效：`README.md` 和 `reasoning/TEAM_LOG.md` 本身也在包里，
  所以改完文档再打一次包，哈希必然变（`BUILD_INFO.json` 里的构建时间也会变）。要核对就拿包里的
  `BUILD_INFO.json` 看版本与构建时间，别指望哈希长期不变。

## 七、命令行单模块运行

```bash
# B：单张公式图识别（--thorough 走多视角，慢 3~5 倍）
./.venv/Scripts/python.exe recognizer.py samples/sample_plus.png
./.venv/Scripts/python.exe recognizer.py data/handwritten/sample_1.png --thorough

# B：接口契约自测（mock 后端，不需要装 paddle）
./.venv/Scripts/python.exe tests/test_recognizer.py

# C：上下文选择基准，默认读写 artifacts/context_conflict_samples.json
./.venv/Scripts/python.exe -m reasoning.context_benchmark

# C：12 个用户确认过的手写公式真值，精确匹配准确率（CPU）
./.venv/Scripts/python.exe -m reasoning.handwritten_eval \
  --output artifacts/handwritten_eval_cpu.json

# 同一份真值用 GPU 识别
RECOGNIZER_DEVICE=gpu:0 ./.venv/gpu-venv/Scripts/python.exe -m reasoning.handwritten_eval \
  --output artifacts/handwritten_eval_gpu.json

# 换 UniMERNet（本机 12 样本实测 8/12）
RECOGNIZER_MODEL=UniMERNet RECOGNIZER_DEVICE=gpu:0 \
  ./.venv/gpu-venv/Scripts/python.exe -m reasoning.handwritten_eval \
  --output artifacts/handwritten_eval_unimernet_gpu.json

# --thorough 会开多视角；出现多个候选时 C 会调用上下文选择 API（付费）
```

## 八、测试

```bash
# C + workbench 全量回归（14 个测试模块、180 项，含真实 Tectonic 编译，需要 tools/tectonic）
./.venv/Scripts/python.exe -m unittest discover -s tests -v

# 单个模块
./.venv/Scripts/python.exe -m unittest tests.test_workbench -v
```

测试不发付费 API 请求（外部调用被 patch 掉），但**依赖本地 Tectonic**：
`tests/test_workbench.py` 会真实编译中文 PDF 并校验页数与尾部空白页。
缺少 Tectonic 时相关用例会失败，这是环境问题，不是产品缺陷。

## 九、多页真实评估

清单在 `data/multipage_samples.json`，包含三个用例：按序合并、倒序合并、尾部空白页。
评估口径只看**结构**（合并顺序、`\newpage` 数量、标记是否落在期望页段、编译成功、PDF 页数、
尾部空白页确实空白），**不评整页转录准确性**——整页仍没有逐字真值。单张公式裁剪图另有
12 条用户确认过的真值，见 9.2。

```bash
# 真实请求（消耗 API）
./.venv/Scripts/python.exe -m workbench.multipage_eval \
  --manifest data/multipage_samples.json \
  --output artifacts/multipage_real

# API 失败后，余额恢复时只重试失败的页
./.venv/Scripts/python.exe -m workbench.multipage_eval \
  --manifest data/multipage_samples.json \
  --output artifacts/multipage_real --retry-failed

# 离线回放已缓存的响应，零 API 调用
./.venv/Scripts/python.exe -m workbench.multipage_eval \
  --manifest data/multipage_samples.json \
  --output artifacts/multipage_real --offline
```

每页响应按图片 SHA256 落盘，中断可续跑。当前仓库里的
`artifacts/multipage_real/report.json` 是 **2026-11-17 的真实请求结果**：
`execution_mode=real_api_and_cache`，三组用例结构全部通过，PDF 页数分别为 4 / 3 / 2，
末页空白用例 `trailing_blank_pdf_is_blank=true`。`report_initial_real.json` 保留首次真实请求
因 402 全部失败的历史记录，不要把它当成当前状态。

**推理模型的输出预算要单独留意**：`deepseek-flash` 的 `max_tokens` 会把推理 token 算进去，
`page_3` 在默认 24000 下返回空内容、`finish_reason=length`，提高到 40000 后同页成功
（79.4 秒，16 个块）。遇到同样的空响应可以这样重试，只重发失败的页：

```bash
FULLPAGE_MAX_TOKENS=40000 FULLPAGE_TIMEOUT_SECONDS=300 \
./.venv/Scripts/python.exe -m workbench.multipage_eval \
  --manifest data/multipage_samples.json \
  --output artifacts/multipage_real --retry-failed
```

结构通过仍然**不等于转录正确**，本次 `transcription_accuracy` 依旧是
`not_evaluated_without_full_page_truth`，识别出的中文与公式需要人工对原图核对。

**整页真值（2026-11-25 新增，正在等人工核对）**：上面说的"没有整页真值"这件事
已经动工了。`data/pdf_pages_ground_truth.json` 里放了 `page_2`–`page_5` 四页的
逐行转录草稿，评估器是 `workbench/full_page_eval.py`：

```bash
python -m workbench.full_page_eval            # 只看门禁状态，不算准确率
```

**现在跑它只会告诉你"还不能算"，不会给你一个数字——这是故意的。**

草稿是模型读图写出来的。手写整页转录的错误往往成体系（同一个字总被认错、
`\frac` 的分子分母总对调），而模型读图时会和它自己的转录犯**同样的错**。
拿这种草稿当真值去评，两边一起错，准确率会显示 100%，而实际是错的。
这比没有指标更危险：它给的是一个看起来很好的假数字。

所以评估器里有一条硬门禁：`review_status` 不是 `user_confirmed` 就直接抛
`GroundTruthNotConfirmed`，退出码 2。要让它开始工作，需要有人对着原图
把 `page_2`–`page_5` 的 `lines` 逐行核对、清空 `uncertainty`、把
`human_review` 改成 `confirmed`，最后把顶层 `review_status` 改成
`user_confirmed`。草稿里已经标出了每页读不准的位置（每页 2–4 处），
核对时优先看那些。

补这张真值表之后要改的地方：`tests/test_full_page_eval.py` 里
`test_real_manifest_is_currently_unconfirmed` 会失败——那时不要改测试迁就现状，
把它改成断言 `confirmed`，并同步更新本节文字。

### 9.2 单张手写公式真值与实测准确率（2026-11-20）

> **证据文件状态（2026-11-25 核对）**：本节表格引用的
> `artifacts/handwritten_eval_*.json` 报告**不在当前工作区**，也不在
> `h2l-backups/h2l-work-2026-11-25.zip` 备份里（即不是某次改动弄丢的）。
> 下面这些数字是**当时在 RTX 5070 Laptop 上跑出来的历史结果**，本机无法直接复现。
> 真值集本身还在（`data/handwritten_ground_truth.json`，12 条，用户逐条确认），
> 评估脚本也在，装上对应模型并配好密钥后可重跑：
> `python -m reasoning.handwritten_eval --output artifacts/handwritten_eval_xxx.json`。
> 完整缺失清单与处理选项见 `docs/成果汇报_2026-11-25.md` 的 7.2 节。

12 张裁剪图的真值由用户在 2026-11-03 逐条确认，清单在
`data/handwritten_ground_truth.json`，评估脚本是 `reasoning/handwritten_eval.py`。
口径与 C 的 `evaluate_refinement` 一致：只做 `strip` 后**整串精确匹配**，不做语义等价。

同一批样本在 RTX 5070 Laptop、`gpu:0` 上对比（除另注外均为单视角）：

| 识别配置 | final 精确匹配 | 报告 |
| --- | --- | --- |
| `PP-FormulaNet-L`（旧默认） | 5 / 12（41.7%） | `artifacts/handwritten_eval_gpu.json` |
| `PP-FormulaNet_plus-L` | 7 / 12（58.3%） | `artifacts/handwritten_eval_plus_gpu.json` |
| `UniMERNet`（画板现在优先使用） | 8 / 12（66.7%） | `artifacts/handwritten_eval_unimernet_gpu.json` |
| `UniMERNet` 多视角 + C 上下文选择 | 7 / 12（58.3%） | `artifacts/handwritten_eval_unimernet_thorough_gpu.json` |

提升来自换模型，不是把错误结果“改对”：UniMERNet 认对了 sample_12 的阶乘，并保持
sample_5/8/9 正确；所有配置 `raw` 与 `final` 相同，C 没有擅自改写。
多视角候选池里最好能有 9/12，但 C 的上下文选择实际把 sample_3 选成“补了括号”的版本、
把 sample_11 选成 `2^x`，所以**不拿多视角 + 选择器凑数**，画板默认走 UniMERNet 单视角。

UniMERNet 单视角仍错 4 条：sample_6（裁剪里含“(3)原式”，真值只取公式本体）、
sample_7（漏因子 4）、sample_10（三撇与 `-24`）、sample_11（双撇写成单撇）。
sample_6/7/10 在已试模型的多视角候选里都没有正确答案；zoom2/3、加白边、锐化、对比度增强
也没有救回。`LaTeX_OCR_rec` 在 sample_10 上输出无关公式，未采用。
规则复核只能发现结构问题，**这些看错仍然只能靠人工对原图发现**。

边界：这是公式裁剪图，不是整页；样本只有 12 个，且用于过冲突分析和本轮选型，不能当作
泛化准确率或性能基准。整页转录仍未建立逐字真值。

### 9.3 真实 API 下的并行提速与重复识别差异（2026-11-24）

> **证据文件状态（2026-11-25 核对）**：本节引用的 `artifacts/real_api_parallel/`
> （`run_concurrency_3.json`、`run_concurrency_1.json`、`summary.json`）**不在当前
> 工作区**，也不在备份里。下表的数字是**历史实测结果**，本机当前无法复现——
> 而且这台机器的 `.env` 里 `OPENAI_API_KEY` 是空的，重跑必然得到不同数字，
> 拿它当同一份证据反而更糟。要重新生成需先配好密钥，再按本节方法跑并发 3 / 串行 1 两轮。
> 完整缺失清单见 `docs/成果汇报_2026-11-25.md` 的 7.2 节。

用 `data/pdf_pages/page_2~4`（3 张真实手写笔记页）走**产品真实链路**（`POST /api/documents/batch` →
并行识别 → 信号落盘 → Tectonic 编译），`deepseek-flash`，并发 3 与串行各跑一轮。
证据在 `artifacts/real_api_parallel/`（`run_concurrency_3.json`、`run_concurrency_1.json`、`summary.json`）。

| 项 | 并发 3 | 串行 1 |
| --- | --- | --- |
| 客户端实测总耗时 | 82.7 s | 232.7 s |
| 三页各自耗时 | 65.3 / 71.3 / 77.3 s | 77.6 / 122.4 / 28.9 s |
| 三页开始时刻（相对 run 起点） | 8 / 12 / 13 ms | 3 / 77600 / 200047 ms |
| 客户端看到的同时在跑页数 | 3 | 1 |
| completion tokens | 16354 / 18211 / 10892 | 18959 / 20232 / 6754 |
| `finish_reason` / `attempts` | 全 `stop` / 全 1 | 全 `stop` / 全 1 |
| 编译 | 成功，再编译 `reused=true` | 成功，再编译 `reused=true` |

**实测提速 2.81 倍**（232.7 ÷ 82.7）。开始时刻相差 13 ms 以内、客户端同时看到 3 页在跑，
这两条一起证明是真并行，不是把串行时间摊薄。

同时暴露的两件真事：

1. **同一批图跑两轮，结果不一样**：TeX 2799 字符 vs 3052 字符；第 2 页 `display_formula` 一轮 16 个、
   另一轮 8 个。没有真值集，无法判断哪一轮更准，所以"重试这一页"必然给出不同结果，
   每页标 `human_review=required` 是必要的而不是保守。
2. **3 张原图编出 4 页 PDF**：TeX 里 `\newpage` 是 2 个（正确），第三页内容在 LaTeX 里自然溢出到第 4 个
   PDF 页。所以"PDF 页数 ≠ 原图页数"是正常现象，**不能**拿来当复核信号；真正的缺口是 PDF 窗格
   目前只是一个 `iframe`，点原图页只跳代码不跳 PDF，要做映射得在编译时记录每个 `\newpage` 落在第几页。

边界：只跑了 3 页、每轮一次，**没有压测并行度上限，也没遇到限流**；`near_token_budget` 六页全为 `false`
（最高一页用了 24000 预算的 84%），这条告警仍只有 mock 证据。两轮 completion 合计 91402 token。
另：本机 `NO_PROXY=[::1],::1` 会让 httpx 抛 `InvalidURL`，测试脚本需 `trust_env=False`；
产品里的 OpenAI 调用不受影响（本次真实识别即为证据）。

## 十、打包时故意没有包含的东西

`.gitignore` 排除了以下内容，克隆后需自行准备：

- `.env`（密钥）
- `.venv/`、`node_modules/`
- `models/`（本地公式模型：PP-FormulaNet-L 约 695 MB，UniMERNet 约 1.6 GB，本机整个目录 3.0 GB）
- `tools/`（Tectonic 可执行文件）
- `artifacts/jobs/`（上传产生的临时任务目录）
- `dist/`（本地审阅用 ZIP）
- `data/pdf_pages/page_1.png`（笔记封面页，被显式排除；`page_2` ~ `page_5` 已保留为多页评估素材）

`scripts/package.ps1` 的排除清单和上面基本一致（`.git`、`.qoder`、`.venv`、`.venv-check`、`.cache`、
`runtime`、`node_modules`、`models`、`.paddlex`、`artifacts`、`dist`、各种缓存目录，以及 `.env`、`*.pyc`、
`workbench.log`、`workbench.pid`），但**三处故意不同**：`tools/tectonic/tectonic.exe`、一份 `vue.global.js`
和一份 Python 运行时（`runtime/python/`，由 `scripts/build_python_runtime.ps1` 现场构建）会随包带上，
这样对方不用装 Tectonic、不用装 Node.js、也不用装 Python；`.env` 和 `models/` 绝不随包分发。
`.cache/` 是打包时的下载缓存（embeddable Python 安装包），只在构建机上有，不进包。
打包脚本会在压缩前扫描包内我们自己打包的文本文件，一旦发现本机 `OPENAI_API_KEY` 的值就中止
（随包运行时与 `tools/` 里是第三方文件，不在扫描范围，脚本会把这句话打印出来）。

## 十一、协作约定（给参与开发的审阅者）

### 11.0 先看这条：内核正在被改动，界面与内核分开推进

**`recognizer.py`、`reasoner.py`、`schemas.py`、`reasoning/`、`workbench/full_page.py`、`workbench/fix.py`
属于"识别内核"，目前由另一位同事在改。** 做界面（前端、桌面窗口、启动体验）的人**不要动这些文件**，
原因很直接：这些文件里正跑着候选选择、`0/o` 混淆检测、结构校验等实验性改动，
两边同时改同一个文件，冲突不是"合并一下"就能解决的——会把别人没跑完的实验一起提交上去。

界面与内核之间**只通过 HTTP 接口通信**（`workbench/app.py` 暴露的 JSON 接口），
界面不 import 任何内核模块。这样内核怎么改，界面都不用跟着改。

完整边界、可改文件清单与接口契约见仓库根目录的 **[AGENTS.md](AGENTS.md)**。
动手前跑一句 `python scripts/check_kernel.py`：全绿说明内核没被动过，可以放心只改前端。
（不要直接 `sha256sum`——Windows 上 `core.autocrlf` 会让行尾在 CRLF/LF 之间变，
直接算哈希会误报"代码被改了"；脚本会先统一行尾再比。）

### 11.1 通用约定

- `schemas.py` 是 A / B / C 三人共同确认的公共契约，**不要单方面改字段**。
  契约讨论稿见 [reasoning/CONTRACT.md](reasoning/CONTRACT.md)（v0.3）。
- 目标是**忠实转录**：不能因为公式在数学上不成立、写法不规范或结构不干净就擅自"改正"。
  转录忠实度、可渲染性、结构合法性、数学正确性是四个不同维度，必须分开。
- 上下文选择**只允许按编号从已有候选里挑**，不许生成、补全或简化 LaTeX。
- 不许编造置信度。`score` 在没有真实值时必须是 `null`；同一模型跑 5 个视角不等于 5 份独立证据。
- 保留 `raw_latex` 与全部 `changes`，静默覆盖原始结果是不可接受的。
- API 调用失败必须回退到人工复核，而不是返回一个看起来成功的结果。
- `TEAM_LOG.md` 只记录**实际发生**的事，计划不写成完成。
