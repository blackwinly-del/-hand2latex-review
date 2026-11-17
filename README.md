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

| 能力 | 入口 | 证据 |
| --- | --- | --- |
| 公式图片 → LaTeX 候选列表（5 字段契约） | `recognizer.recognize()` | `test_recognizer.py` |
| 候选规范化、按 `strip` 后完整字符串去重 | `reasoner.refine()` | `tests/test_reasoner.py` |
| 括号 / `\left\right` / `\begin\end` / 命令参数数量结构检查 | `reasoning/validators.py` | `tests/test_validators.py` |
| `0/o` 易混淆字符漏报检测 | `find_ambiguous_glyph_conflicts()` | `tests/test_validators.py` |
| 多模态大模型按编号选候选（只选不改） | `reasoning/context.py` | `tests/test_context.py` |
| KaTeX 渲染可行性检查 | `reasoning/render_check.py` | `tests/test_render_check.py` |
| 错误率 / 误改写率 / 复核率评估口径 | `reasoning/evaluate.py` | `tests/test_evaluate.py` |
| 单页整页识别（中文 + 公式 + 图片占位） | `workbench/full_page.py` | `artifacts/full_page_browser_acceptance.json` |
| 多页上传、按上传顺序合并、页间插入 `\newpage` | `workbench/app.py` `/api/documents/batch` | `artifacts/batch_browser_acceptance.json` |
| 编译失败片段定位 + AI 建议 + 人工确认局部修正 | `/api/jobs/{id}/suggest-fix`、`/apply-fix` | `tests/test_workbench_app.py` |
| Tectonic + ctex 真实中文 PDF 编译与预览、下载 | `workbench/compiler.py` | `tests/test_workbench.py` |
| 显式空白页（`blank_page` → `\null`）忠实排版 | `workbench/full_page.py` | `tests/test_workbench.py` |

### 尚未实现或尚未证明（审阅时请重点看这里）

- **整页转录准确率没有真值集**，因此所有"识别效果"都只是人工观察，不是指标。
- **扩充后的真实多页评估没跑通**：4 次真实请求全部返回 HTTP 402 `Insufficient Balance`，
  细节见 `artifacts/multipage_real/report_initial_real.json`。充值后用下面的命令重试即可。
- 跨页**语义**一致性（跨页公式续写、符号统一）未实现；当前只保证合并顺序和分页。
- 手绘图形只输出文字描述占位，不重绘。
- 第二个识别引擎（UniMERNet）只在 `recognizer.py` 里留了槽位，未接入，因此没有跨引擎投票。
- MLP 风险打分仅用于学习演示，`risk_score` 在生产路径恒为 `null`。
- 没有做部署、并发和性能优化；CPU 推理和 Tectonic 编译都比较慢。

## 二、项目结构

```text
.
├── recognizer.py              B：图片 → LaTeX 候选列表（不调大模型、不校验结构）
├── reasoner.py                C：候选 → 规范化 / 去重 / 结构检查 / 上下文选择，生产入口 refine()
├── schemas.py                 A / B / C 三人共享的数据契约（改动需三人同意）
├── test_recognizer.py         B 的接口自测（mock 后端，秒出）+ --real 真模型冒烟
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
│   └── static/index.html      Vue 3 前端单页
│
├── tests/                     13 个 unittest 测试模块（`python -m unittest discover -s tests`）
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
│   └── launch.ps1             一键体检 / 装环境 / 启动 / 重启 / 停止的实际逻辑
├── 启动工作台.bat              双击入口（ASCII 内容，中文界面由 launch.ps1 输出）
├── 关闭工作台.bat              双击停止服务
├── README_B.md                B 模块的详细说明与环境变量表
├── requirements.txt           Web 工作台 + C 模块依赖
└── requirements-b.txt         PP-FormulaNet-L 本地推理依赖（paddlepaddle / paddleocr）
```

## 三、环境要求

| 项目 | 要求 |
| --- | --- |
| Python | **3.10 / 3.11 / 3.12**。PaddlePaddle 不支持 3.13。 |
| Node.js | 18+，前端 Vue 与 KaTeX 渲染检查都从 `node_modules` 读取 |
| 操作系统 | 开发在 Windows 完成；Linux/macOS 需要自行替换 Tectonic 可执行文件 |
| Tectonic | 0.17.0，放在 `tools/tectonic/tectonic.exe`（该目录被 `.gitignore` 排除，需自备） |
| 中文字体 | ctex 编译需要系统里装有 CJK 字体 |
| 模型权重 | PP-FormulaNet-L 约 695 MB，放 `models/PP-FormulaNet-L/`（同样被排除，首次运行可自动下载） |
| 多模态 API | 任意 OpenAI 兼容接口，需支持图片输入 |

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
| `RECOGNIZER_MODEL` | 默认 `PP-FormulaNet-L`，可换 `PP-FormulaNet_plus-L` |
| `RECOGNIZER_MODEL_DIR` | 默认 `models/PP-FormulaNet-L` |
| `RECOGNIZER_DEVICE` | `cpu`，有显卡填 `gpu:0` |
| `RECOGNIZER_BACKEND` | 填 `mock` 返回明确失败候选，仅用于联调失败回退，**不能当作真实识别结果** |

完整 B 侧变量表见 [README_B.md](README_B.md)。

## 六、运行 Web 工作台

### 6.1 一键启动（Windows，推荐先试这个）

双击仓库根目录的 [启动工作台.bat](启动工作台.bat)，按菜单选：

```text
[1] 体检        只检查环境，不安装、不启动
[2] 准备并启动  首次装环境 / 日常启动都用它
[3] 重启服务    改完代码后用这个
[4] 查看状态    看服务是否还在运行
[5] 停止服务
```

它按顺序做这些事，每一步都是幂等的（已就绪就跳过，可反复运行）：

1. 找或建 `.venv`，只接受 Python 3.10 / 3.11 / 3.12（PaddlePaddle 不支持 3.13）；
2. 缺包才 `pip install -r requirements.txt` / `requirements-b.txt`，缺前端才 `npm install`；
3. 没有 `.env` 就从 `.env.example` 复制一份，并检查 `OPENAI_API_KEY` / `OPENAI_MODEL` /
   `OPENAI_BASE_URL` 是否填了（**只显示是否配置和长度，不打印密钥**）；
4. 检查 `tools/tectonic/tectonic.exe` 与 `models/PP-FormulaNet-L` 是否就位；
5. 跑 `test_recognizer.py` 契约自检，不过就不启动；
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
| `GET /api/jobs/{job_id}` | 任务状态、TeX 源码、块结构 |
| `GET /api/jobs/{job_id}/pdf` | 下载编译好的 PDF |
| `POST /api/jobs/{job_id}/compile` | 手工改完 TeX 后重新编译 |
| `POST /api/jobs/{job_id}/suggest-fix` | 让模型给出针对某个错误片段的修改建议 |
| `POST /api/jobs/{job_id}/apply-fix` | 人工确认后应用建议（建议过期返回 HTTP 409） |

一次上传消耗的 API 量不小（每页一次整页识别），演示前先确认账户余额。

## 七、命令行单模块运行

```bash
# B：单张公式图识别（--thorough 走多视角，慢 3~5 倍）
./.venv/Scripts/python.exe recognizer.py samples/sample_plus.png
./.venv/Scripts/python.exe recognizer.py data/handwritten/sample_1.png --thorough

# B：接口契约自测（mock 后端，不需要装 paddle）
./.venv/Scripts/python.exe test_recognizer.py

# C：上下文选择基准，默认读写 artifacts/context_conflict_samples.json
./.venv/Scripts/python.exe -m reasoning.context_benchmark
```

## 八、测试

```bash
# C + workbench 全量回归（13 个模块，含真实 Tectonic 编译，需要 tools/tectonic）
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
尾部空白页确实空白），**不评转录准确性**——因为没有人工真值集。

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
`artifacts/multipage_real/report.json` 是**离线回放**结果，
`report_initial_real.json` 是首次真实请求因 402 全部失败的记录，两者都不代表多页评估已通过。

## 十、打包时故意没有包含的东西

`.gitignore` 排除了以下内容，克隆后需自行准备：

- `.env`（密钥）
- `.venv/`、`node_modules/`
- `models/`（PP-FormulaNet-L 权重，约 695 MB）
- `tools/`（Tectonic 可执行文件）
- `artifacts/jobs/`（上传产生的临时任务目录）
- `dist/`（本地审阅用 ZIP）
- `data/pdf_pages/page_1.png`（笔记封面页，被显式排除；`page_2` ~ `page_5` 已保留为多页评估素材）

## 十一、协作约定（给参与开发的审阅者）

- `schemas.py` 是 A / B / C 三人共同确认的公共契约，**不要单方面改字段**。
  契约讨论稿见 [reasoning/CONTRACT.md](reasoning/CONTRACT.md)（v0.3）。
- 目标是**忠实转录**：不能因为公式在数学上不成立、写法不规范或结构不干净就擅自"改正"。
  转录忠实度、可渲染性、结构合法性、数学正确性是四个不同维度，必须分开。
- 上下文选择**只允许按编号从已有候选里挑**，不许生成、补全或简化 LaTeX。
- 不许编造置信度。`score` 在没有真实值时必须是 `null`；同一模型跑 5 个视角不等于 5 份独立证据。
- 保留 `raw_latex` 与全部 `changes`，静默覆盖原始结果是不可接受的。
- API 调用失败必须回退到人工复核，而不是返回一个看起来成功的结果。
- `TEAM_LOG.md` 只记录**实际发生**的事，计划不写成完成。
