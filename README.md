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

### 尚未实现或尚未证明（审阅时请重点看这里）

- **整页转录准确率没有真值集**，因此所有"识别效果"都只是人工观察，不是指标。
  2026-11-17 的 4 张真实页多页评估已跑通（三组结构全过，见第九节），但它只证明结构链路，
  **不证明转录逐字正确**；首次因 402 失败的记录保留在 `artifacts/multipage_real/report_initial_real.json`。
- **模型稳定性只有单次证据**：`page_3` 首次因推理 token 耗尽输出预算返回空内容，放宽后重试才成功，
  没有多次重复运行的稳定性统计。
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
├── tests/                     13 个 unittest 测试模块 + test_recognizer.py 契约自检脚本（`python -m unittest discover -s tests`）
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
│   ├── launch.ps1             一键体检 / 装环境 / 启动 / 重启 / 停止的实际逻辑
│   └── launch_demo.ps1        画板演示的启动逻辑（前台窗口运行，关窗即停）
├── 启动工作台.bat              双击入口（ASCII 内容，中文界面由 launch.ps1 输出）
├── 启动画板.bat                双击打开画板演示（Streamlit，默认 8501 端口）
├── 关闭工作台.bat              双击停止服务
├── README_B.md                B 模块的详细说明与环境变量表
├── requirements.txt           Web 工作台 + C 模块依赖
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
| `GET /api/jobs/{job_id}` | 该 job 的 TeX 源码、源图链接、PDF 链接（`human_review` 恒为 true）；识别块结构合并在这份 TeX 里，接口不单独返回块数组 |
| `GET /api/jobs/{job_id}/pdf` | 下载编译好的 PDF |
| `POST /api/jobs/{job_id}/compile` | 手工改完 TeX 后重新编译 |
| `POST /api/jobs/{job_id}/suggest-fix` | 让模型给出针对某个错误片段的修改建议 |
| `POST /api/jobs/{job_id}/apply-fix` | 人工确认后应用建议（建议过期返回 HTTP 409） |

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
- 用本机 GPU 识别：`启动画板.bat -Gpu`（等价于 `scripts/launch_demo.ps1 -Gpu`）。它会改用
  `.venv\gpu-venv` 并设置 `RECOGNIZER_DEVICE=gpu:0`；GPU 环境缺画板依赖时，按
  `demo/requirements-demo.txt` 安装到该环境。页面会显示当前识别设备。

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

实测同一张 `samples/sample_plus.png`（`RECOGNIZER_DEVICE=gpu:0`）：

| 环境 | 首次（含模型加载） | 第二次（预热后） | 输出 LaTeX |
| --- | --- | --- | --- |
| CPU（`paddlepaddle 3.3.0`） | 30.3 s | 11.7 s | `x^{3}-x^{2}+x^{2}+x-x+3x-3+4` |
| GPU（`paddlepaddle-gpu 3.4.0` cu129） | 12.3 s | 0.62 s | 同上 |

GPU 运行期间 `nvidia-smi` 采样到 35–44% 利用率、约 355 MiB 显存，确认真的在 GPU 上算。
这只是单张样本的单次测量，不构成性能基准。

画板现在可以直接用 GPU 启动：`启动画板.bat -Gpu`。实测浏览器页面显示
“识别设备：GPU（gpu:0）”，Streamlit 进程出现在 `nvidia-smi` 的 compute apps 中。
默认 `.venv` 的 CPU 识别也已恢复：`recognizer.py samples/sample_plus.png` 实测模型加载 9.5 s、
推理 26.02 s，输出与 GPU 相同。整页识别仍然走远端 `deepseek-flash`，本机 GPU 只覆盖
单张公式图（B 的 `recognizer.py`），两者不是同一条链路。

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
```

## 八、测试

```bash
# C + workbench 全量回归（14 个测试模块、159 项，含真实 Tectonic 编译，需要 tools/tectonic）
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

### 9.2 单张手写公式真值与实测准确率（2026-11-20）

12 张裁剪图的真值由用户在 2026-11-03 逐条确认，清单在
`data/handwritten_ground_truth.json`，评估脚本是 `reasoning/handwritten_eval.py`。
口径与 C 的 `evaluate_refinement` 一致：只做 `strip` 后**整串精确匹配**，不做语义等价。

RTX 5070 Laptop、`PP-FormulaNet-L`、`gpu:0` 实测：

| 指标 | 结果 |
| --- | --- |
| 样本数 | 12 |
| raw 精确匹配 | 5 / 12（41.7%） |
| final 精确匹配 | 5 / 12（41.7%） |
| C 改写正确结果为错误 | 0 |
| 规则判定需复核 | 1 / 12 |
| 漏判的错误样本 | 7 / 12 |

7 个错误都是真实识别差异：多出裁剪边界外的编号与根式（sample_6）、漏因子 4（sample_7）、
单撇写成双撇（sample_8）、`o` 写成 `0`（sample_9）、指数与分子写错（sample_10）、
双撇写成 `n`（sample_11）、阶乘 `2!`/`3!` 写成 `21`/`31` 且多一个减号（sample_12）。
`raw` 与 `final` 相同，说明 C 没有擅自改写；规则复核只命中了 1 个结构性错误，**7 个错误
没有被自动标记**——再次说明“没有警告”不等于“抄对了”。

边界：这是公式裁剪图，不是整页；样本只有 12 个，且用于过冲突分析，不能当作泛化准确率或
性能基准。整页转录仍未建立逐字真值。

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
