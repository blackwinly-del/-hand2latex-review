# 任务 B：recognizer.py 使用说明

B 只做一件事：**图片 → LaTeX 候选列表**。输出字段已对齐 `CONTRACT.md` v0.2。
对外只有一个函数：

```python
from recognizer import recognize

candidates = recognize("samples/hw_01.png")
# [{
#     "engine": "pp_formulanet_l",
#     "latex": "\\frac{x^{2}}{2}",
#     "score": None,
#     "latency_ms": 1234.5,
#     "error": None,
# }]
```

## 一、职责边界（不许越界）

| B 做 | B 不做 |
| --- | --- |
| 加载 PP-FormulaNet-L，跑推理 | 校验括号/树结构是否合法（C 的事） |
| 永远返回 `list[dict]`，失败也返回 | 给候选打分、排序、挑最好的（C 的事） |
| 多引擎 / 多视角把候选池扩出来 | 判断两个公式是否语义等价（C 的事） |
| 模型没给分数就填 `None` | 编造置信度（多视角命中数也不许当分数） |
| 实测并上报 `latency_ms` | 用延迟影响候选选择（C 不用它排序） |
| 只 import `schemas.py` | import A / C 的任何代码 |

错误约定（契约 §2.2）：任何失败（文件不存在、图片损坏、模型崩了）都返回

```json
{"engine": "pp_formulanet_l", "latex": "", "score": null, "latency_ms": 0.0, "error": "原因"}
```

`latex` 必须是空字符串，原因只放在 `error` 里。**绝不再把报错文本塞进 `latex`**——
那样 C 会把它当成合法公式，括号还查得过去，最后以 `need_review=false` 的"成功"结果返回给用户。

## 一点五、与 v0.1 的差异（本次按契约改掉的）

| 项目 | 改前 | 改后 |
| --- | --- | --- |
| 候选字段 | 3 个（engine/latex/score） | 5 个，新增 `latency_ms`、`error` |
| 失败表达 | `latex="[ERROR] ..."` | `latex=""` + `error="原因"`，已删 `ERROR_PREFIX` |
| 首尾空白 | B 自己 strip | **B 不 strip**，交给 C 清理并记 `trim_outer_whitespace` |
| 去重口径 | 抹掉全部空白后比较 | 只 `strip` 后比较，`x ^ 2` 与 `x^2` 算两条 |
| changes 字段 | `{from, to, reason}` | `{rule, before, after, ...}`（按 rule 区分） |
| refine 返回 | 无 `risk_score` | 新增 `risk_score`（MLP 未接入，恒为 `null`） |
| 图片格式 | 无 `.gif` | 补上 `.gif`，与契约 §2.1 一致 |

## 二、安装（一次性）

**注意：PaddlePaddle 不支持 Python 3.13，必须用 3.10 / 3.11 / 3.12。**

```bash
conda create -n formula python=3.11
conda activate formula
pip install -r requirements-b.txt

# 国内网络下载模型慢/失败时，改用百度模型源：
#   Windows PowerShell:  $env:PADDLE_PDX_MODEL_SOURCE = "BOS"
#   Git Bash:            export PADDLE_PDX_MODEL_SOURCE=BOS
```

首次运行会自动下载 PP-FormulaNet-L 权重（约 695 MB），只需一次。

## 三、运行与自测

```bash
# 1. 接口契约自测（不需要装 paddle，mock 后端，秒出，共 24 项）
python tests/test_recognizer.py

# 2. 真模型冒烟（需要先装好 paddle，并先跑 python samples/_gen_sample.py 生成测试图）
python tests/test_recognizer.py --real

# 3. 单独跑一张图
python recognizer.py samples/sample_plus.png               # 单视角，快
python recognizer.py samples/sample_plus.png --thorough    # 多视角，扩候选池，慢 3~5 倍
#    或换成你自己的手写公式照片：python recognizer.py D:/photos/hw_01.png
```

全部 ✅ 才算 B 的基础版完成。

## 四、环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `RECOGNIZER_MODEL` | `PP-FormulaNet-L` | 换 `PP-FormulaNet_plus-L` / `_plus-M` 中文公式更强 |
| `RECOGNIZER_MODEL_DIR` | 未设置 | 可选模型目录；默认优先使用项目内 `models/PP-FormulaNet-L` |
| `RECOGNIZER_DEVICE` | `cpu` | 有显卡填 `gpu:0` |
| `RECOGNIZER_BACKEND` | `paddle` | 填 `mock` 返回明确失败候选，仅用于联调失败回退，不得当作真实识别结果 |
| `RECOGNIZER_ENGINES` | `pp_formulanet_l` | 以后加第二模型改成 `pp_formulanet_l,unimernet` |
| `RECOGNIZER_VIEWS` | `off` | 设 `on` 则默认多视角（慢 3~5 倍），一般用 `thorough=True` 按需触发 |
| `RECOGNIZER_MAX_CANDIDATES` | `6` | 去重后候选数上限，防止 C 的仲裁 token 爆炸 |
| `RECOGNIZER_LOG_JSONL` | 未设置 | 设成文件路径则每次识别追加一行 JSON，供 C 做测试集统计 |

## 四点五、为什么要能给出"多个候选"（结构感知那层的落点）

TAMER（AAAI 2025）的核心是"联合优化序列预测 + 树结构预测，**推理时用树结构评分筛选输出**"。
B 不换模型架构，所以"树结构评分"这件事 B 做不了（那是 C 的活），但**筛选的前提是池子里有货**。
PaddleOCR 的封装不暴露 n-best / beam search，B 只有两条不换模型的路：

1. **异构引擎**（推荐）：再加 UniMERNet。不同架构的模型错误才不相关，投票才真正有价值。
2. **同模型多视角**（`thorough=True`）：原图 / 放大 1.5× / ±2° / 二值化各跑一次。
   这纯属启发式，收益尚未验证，**默认关闭**；而且它的候选高度相关，不能当独立证据。

因此 B 做了三件配套的事：

- **去重**：按契约 §2.2，只 `strip` 后按完整字符串比较，**不折叠内部空白**。
  ` x^2 ` 与 `x^2` 算同一条；`x ^ 2` 与 `x^2` 算两条（语义等价判断属于 C 的树结构分析）。
  这样同一模型跑 5 次不会让 C 误以为"5 份证据一致"。
- **候选池洁净**：个别视角失败不写入候选池（失败候选 `error != null`，C 会跳过），
  只在全部失败时合并成一条汇总失败候选。纯空白结果也不进池。
- **可复现**：视角表固定、贪心解码、无随机数。同一张图两次结果必须一致，
  否则 C 用测试集做"有无 reasoner 的错误率对比"就是噪声。

⚠️ **B 仍然不打分**：`score` 恒为 `None`。多视角命中次数只写进 `RECOGNIZER_LOG_JSONL`，
绝不塞进接口——一次模型跑 5 遍不是 5 份独立证据，把命中数当置信度就是自欺欺人。

### 给 C 的建议：树结构评分怎么轻量落地

括号配对只是表层检查，真正的做法是把 LaTeX 解析成语法树再判断：

1. 用**栈**扫描 token：`{` 入栈、`}` 出栈；`\left` 与 `\right` 单独配对；
   `\begin{x}` / `\end{x}` 必须同名且正确嵌套。
2. 遇到 `\frac`，栈上必须有**恰好 2 个**子节点；`\sqrt` 1 或 2 个；`^` / `_` 各 1 个。
   数量不对 → 结构非法（这比数括号准得多，能抓出 `\frac{x}{y}{z}` 这种括号合法但结构错的输出）。
3. 语法树合法 + 只有 1 个候选 → 直接放行；多个候选且**来自不同 engine** → 交给多模态 AI 选编号；
   同一 engine 的候选一致**不算独立证据**（用 `schemas.independent_engines()` 判断）。

## 五、与 A / C 的连接点

- **A → B**：A 只传图片路径字符串，只接收候选列表。推荐用法：先 `recognize(path)` 快速出结果，
  C 报 `need_review` 后再 `recognize(path, thorough=True)` 补一批候选重判。
  A 建议把调用包在 `@st.cache_resource` 后面（B 已内置进程级模型缓存，`warmup()` 可提前预热）。
- **B → C**：C 只读 B 的候选（`image_path, candidates`），自己不调识别模型。
  B 交出的每个候选都满足契约 §2.2：5 字段、`score` 无真实值时是 `null`、失败时 `latex=""` 且 `error` 非空。
  若需要 C 的上下文候选选择，输入图片必须是 PNG/JPEG/GIF/WebP；B 支持的 BMP/TIFF/PDF 需先转换，不能扩大 C 的输入契约。`RECOGNIZER_BACKEND=mock` 只返回失败候选，用于验证回退，不能展示为真实识别成功。
- 共享契约在 `schemas.py`：`Candidate` / `RefineResult` / `CANDIDATE_KEYS` /
  `make_change_context()` / `make_change_trim()` / `independent_engines()`，改字段必须三人同意。

## 六、B 的迭代路线（基础版跑通后再做）

1. ✅ PP-FormulaNet-L 单模型 + 失败兜底 + 多视角扩池 + 契约 v0.2 对齐（本次已完成，24 项自测）
2. 第二模型 UniMERNet：在 `recognizer.py` 的 `ENGINES` 表里加一行
   `ENGINE_UNIMERNET: {"model_name": "UniMERNet"}`，再写一个对应的取结果逻辑，
   `recognize()` 会自动把两个引擎的候选合并返回——**A、C 一行代码都不用改**。
3. 收集测试素材：往 `samples/` 放 10+ 张真实手写公式照片（`hw_01.png`...），
   设 `RECOGNIZER_LOG_JSONL=runs/recognize.jsonl` 批量跑，把日志交给 C 做评估集。

## 七、常见问题

- **`ModuleNotFoundError: No module named 'paddleocr'`** → 没装依赖，或当前 Python 是 3.13（见第二节换环境）。
- **模型下载卡住** → 设置 `PADDLE_PDX_MODEL_SOURCE=BOS` 后重试。
- **CPU 推理慢（一张图几秒）** → 正常，PP-FormulaNet-L 本来就重；急可换 `RECOGNIZER_MODEL=PP-FormulaNet-S` 先联调，演示时再换回 L。
- **公式识别可视化报错** → 可视化只在 Ubuntu 装了 LaTeX 才可用，不影响本模块返回 LaTeX 文本。
