# TEAM LOG

## C 模块第一步：规范化、去重与最小测试

**阶段状态：已完成；下列未来事项尚未实施。**

- **本次任务**：仅实现安全的首尾空白规范化、候选去重和最小测试；不修改 `schemas.py`，不接入 OCR、MLP 或多模态。
- **负责人决定**：项目结构已确认，开始实施。候选冲突不能凭常见程度裁决；回退主引擎候选仅用于展示和编辑，不视为已验证的正确答案。
- **实际环境**：工作区起初为空；Python 3.12.7；无 pytest，故使用标准库 `unittest`。
- **实际创建文件**：`D:\latex\reasoner.py`、`D:\latex\tests\test_reasoner.py`；本次记录仅创建 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - `normalize_latex` 仅 `strip` 首尾空白，保留内部空白。
  - `deduplicate_candidates` 使用规范化副本去重，跳过空白候选；对非 dict、缺少 `latex` 或 `latex` 非字符串的候选明确抛错。
  - 去重保留首个原始 dict，不修改输入。
- **外部资源**：无。
- **代码审核及处理**：代码审核员结论为无必须修复项；建议在 `tests/test_reasoner.py` 增加原始对象身份断言，已采纳并加入 `assertIs`；可选的异常消息断言未采纳。
- **实际测试**：命令 `python -m unittest discover -s tests -v`。初次运行 7 项全部通过（0.002s）；最终运行 `Ran 7 tests in 0.024s`，`OK`。
- **未解决／未来事项（均未实现）**：`refine` 返回契约、结构检查、候选冲突与人工复核编排、OCR 集成、MLP。
- **学习进度**：已完成规范化与候选冲突的初步练习，理解保留原候选及 `low + need_review` 的含义。
- **下一步（计划，未完成）**：由主 Agent 和教导员安排最小 `refine` 或结构检查。

## C 模块第二步：最小结构校验与测试

**阶段状态：已完成；下列未来事项尚未实施。**

- **本次任务**：实现 `reasoning/validators.py` 的 `validate_structure` 和 `tests/test_validators.py`；范围仅为空结果、`{}`、`[]`、`()` 配对及 `\left`/`\right` 配对。
- **负责人决定**：本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **实际修改文件**：`D:\latex\reasoning\validators.py`、`D:\latex\tests\test_validators.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - 空字符串或纯空白字符串返回 `empty_latex`；非字符串输入明确抛出 `TypeError`。
  - 使用栈检查括号嵌套顺序；按完整命令名识别 `\left` 和 `\right`，避免将 `\leftarrow` 误判为 `\left`。
  - 跳过转义非字母字符及双反斜杠；仅返回 `unbalanced_brackets` 或 `unbalanced_left_right`，不修改公式。
- **外部资源**：无。
- **代码审核及处理**：审核员结论为无必须修复项；建议增加 `\(x\)`、`\[x\]` 合法转义测试并去掉重复 `{[}]` 样例，均已采纳。
- **实际测试**：命令 `python -m unittest discover -s tests -v`。初次运行 `Ran 14 tests in 0.002s`，`OK`；最终运行 `Ran 14 tests in 0.026s`，`OK`。
- **未解决／未实现事项**：`\begin`/`\end`、`\frac`、`^`、`_` 校验及完整 `refine` 均未实现。
- **学习进度**：已讲解栈用于检查嵌套顺序，以及结构有效不等于数学正确。
- **下一步（计划，未完成）**：可实现 `\begin`/`\end` 配对或最小 `refine`。

## C 模块第三步：规则版 `refine`

**阶段状态：已完成；下列遗留事项和下一步计划均未实施。**

- **本次任务**：继续实施 `refine` 剩余部分，本步仅完成规则版，不接多模态或 MLP；`risk_score=None`，渲染预览仍由 A 负责。
- **负责人决定**：确认上述实施范围及职责边界；本步不引入多模态、MLP 或 C 模块渲染预览。
- **实际修改文件**：`D:\latex\reasoner.py`、`D:\latex\reasoning\validators.py`、`D:\latex\tests\test_reasoner.py`、`D:\latex\tests\test_validators.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - `validators` 新增 `\begin`/`\end` 环境配对、明显 `\frac` 后续参数缺失、`^`/`_` 缺失及相邻错误检测。
  - 审核后新增同一 base 重复同类脚本检测，覆盖 `x^2^3`、`x_1_2`、`x^{2}^{3}`；合法对照包括 `x^2_3`、`x_1^2`、`x^{2^3}`、`x_{1_{2}}`、`{x^2}^3`、`x^2+y^3`。
  - `refine` 对空候选或全部失败候选返回空串、`low` 并请求人工复核；首个有效候选保留原文 `raw`，以 `strip` 后结果为 `final`，仅在实际发生 `strip` 时记录 `changes`。
  - 单个有效候选为 `medium`；跨引擎一致且结构有效为 `high`；同引擎重复为 `medium`；候选冲突或结构异常为 `low` 并请求人工复核。不进行多数投票或数学纠正，`error` 候选不参与，输入不修改，`risk_score=None`。
- **外部资源**：无。
- **代码审核及处理**：第一轮发现重复同类上下标漏报 1 项必须修复问题，已修复并补充检测与测试；第二轮确认必须项已关闭，无新阻断。
- **实际测试**：三次均运行 `python -m unittest discover -s tests -v`。扩展 `validators` 后 17 项通过（0.027s，`OK`）；初版 `refine` 后 26 项通过（0.005s，`OK`）；最终修复后 27 项通过（0.004s，`OK`）。
- **未解决／未实现事项**：建议后续处理 LaTeX 注释和末尾孤立反斜杠；`\dfrac`/`\tfrac` 尚未扩展；多模态、MLP、A/B 集成和真实渲染检查均未实现。
- **学习进度**：已讲解 `refine` 决策表，以及展示选择不等于确认正确。
- **下一步（计划，未完成）**：由负责人确认后续安排。

## C 模块第四步：同样本评估

**阶段状态：评估指标与 Mock 测试已完成；真实评估及下列未来事项均未实施。**

- **本次任务**：新增同样本评估指标计算及 Mock 测试，不使用真实 OCR、渲染，也不形成真实效果结论。
- **负责人决定**：确认继续本阶段。
- **实际修改文件**：`D:\latex\reasoning\evaluate.py`、`D:\latex\tests\test_evaluate.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - 输入为同样本 `ground_truth`、`refine_result`（`raw`、`final`、`need_review`）及 `latency_ms`，可选 `renderable` 由 A 提供；`raw`、`final` 均使用同一 `strip` 规范化后与 `ground_truth` 比较。
  - 输出 `sample_count`、`raw`/`final` 正确数、错误改写数、review 数、`raw`/`final` 完全正确率、错误改写率、`renderable_rate`、`human_review_rate`，以及延迟中位数和 nearest-rank p95。
  - 错误改写率分母为 `raw` 原本正确数，空分母返回 `None`；`renderable_rate` 仅支持全部样本均提供或均未提供 `renderable`，否则报错。
  - 校验空 `samples`、空 `ground_truth`、负数／非数值／NaN／±inf 延迟，以及非 bool 的 `need_review`／`renderable`。
- **外部资源**：无。
- **代码审核及处理**：第一轮发现非有限延迟校验缺失 1 项必须修复问题，已使用 `math.isfinite` 修复，并补充 NaN／±inf、20 条样本 p95=19、median=10.5、全 False `renderable` 及非 bool 测试；第二轮无必须、建议或可选项，无新阻断。
- **实际测试**：命令 `python -m unittest discover -s tests -v`。初次真实全量测试 `Ran 32 tests in 0.006s`，`OK`；修复及补测后最终 `Ran 33 tests in 0.030s`，`OK`。
- **未解决／未实现事项**：真实样本导入、A 反馈文件对接、真实渲染与 OCR 评估、多模态、MLP 均未实现。
- **学习进度**：已理解错误改写率的分母是 `raw` 原本正确数。
- **下一步（计划，未完成）**：由负责人确认。

## C 模块第五步：真实 OCR 冒烟与手写样本验证

**阶段状态：真实识别、冒烟及样本验证已完成；公式内容正确性仍待用户审核。**

- **本次任务**：在项目虚拟环境中接入最小公式识别，完成官方样例冒烟及 3 个手写单公式样本的真实 `recognize + refine` 验证，并记录指标边界。
- **负责人决定**：用户授权后创建项目 `.venv`；本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **实际创建／修改文件**：`D:\latex\recognizer.py`、`D:\latex\artifacts\official_smoke.json`、`D:\latex\artifacts\handwritten_validation.json`、`D:\latex\data\handwritten\sample_1.png` 至 `sample_3.png`；另创建项目 `.venv`，并将模型复制到 `D:\latex\models\PP-FormulaNet-L`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实际环境及实现**：
  - 安装 PaddlePaddle 3.3.0、PaddleOCR 3.7.0、PyMuPDF 2.0、tokenizers 0.23.3、ftfy 6.3.1。
  - `recognizer.py` 使用 PP-FormulaNet-L，在 CPU 上懒加载，候选 `score=None`。
  - 模型复制到 ASCII 路径后，初始化 JSON 错误消失；补装 tokenizers 和 ftfy 后推理成功。
  - 用户 PDF 已渲染 5 页，并裁剪 3 个单公式样本。
- **外部资源**：上述实际安装的 Python 包及 PP-FormulaNet-L 模型。
- **真实运行结果**：
  - 官方样例冒烟完成，结果保存于 `D:\latex\artifacts\official_smoke.json`；产生 1 条 `error=None`、`score=None` 的候选，`refine_result` 为 `medium`、`need_review=False`，模型调用总耗时 29.039 秒。该结果仅证明流程完成，不宣称公式完全正确。
  - 3 张手写样本已在同一进程真实运行 `recognize + refine`，结果保存于 `D:\latex\artifacts\handwritten_validation.json`；3 条均 `error=None`、`score=None`，其中 2 个 `medium`、1 个 `low`。
  - `sample_3` 因结构问题为 `need_review=True`；三条 `recognize` 延迟分别为 7960.823、6302.263、8546.029 ms，总墙钟 41.676 秒。
  - artifact 字段已统一为 `refine_result`。
- **代码审核及处理**：只读代码审核员未发现阻断问题；明确用户尚未审核前不得计算 exact accuracy 或宣称样本正确。
- **实际测试**：刚运行 33 项 `unittest`，全部通过。
- **未解决／未实现事项**：官方样例及 3 个手写样本的公式内容正确性尚未经用户审核；未计算 exact accuracy，也未形成识别正确率结论；`score` 仍为 `None`，`sample_3` 仍需人工复核。
- **学习进度**：已明确推理成功、结构校验结果与公式内容正确性是不同事项，不能由前两者替代人工 correctness 审核。
- **下一步（计划，未完成）**：等待用户审核样本，并由负责人确认后续评估安排。

## C 模块第六步：手写样本人工确认与小样本评估

**阶段状态：3 个选定裁剪样本的用户审核与评估已完成；结果不代表模型总体或生产准确率。**

- **本次任务**：根据用户对 3 个手写样本的审核结论补充 ground truth 与人工复核状态，保存并记录同样本评估结果。
- **负责人决定**：本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **实际修改文件**：`D:\latex\artifacts\handwritten_validation.json` 已为三条样本加入 `ground_truth`、`human_review=confirmed_correct`，为 `sample_2`、`sample_3` 加入来源书写说明并保存评估；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **人工审核及处理**：用户先确认 `sample_1` 识别正确，随后明确“23是我书写问题，识别没有问题”，因此 `sample_2`、`sample_3` 也被确认为忠实转录；该结论不改写为数学公式正确或源式结构正确。
- **外部资源**：本阶段无新增外部资源。
- **实际计算结果**：`sample_count=3`；`raw`／`final` 正确数均为 `3/3`，完全正确率均为 `1.0`；`erroneous_rewrite_count=0`、`rate=0.0`；规则触发 `review=1/3`；`recognize median=7960.823ms`、nearest-rank `p95=8546.029ms`；`renderable_rate=None`，因未实际渲染。
- **实际测试**：本阶段未运行测试；上述为已保存样本的实际评估计算结果。
- **结果边界**：这些指标仅来自用户作业中选取的 3 个裁剪样本，不能外推为模型总体或生产准确率。`sample_3` 的 `low + need_review=True` 是结构规则结果，与用户确认其为忠实转录并不矛盾。
- **未解决／未实现事项**：真实渲染检查仍未实施；小样本结果不足以评估总体或生产表现。
- **学习进度**：已明确人工确认忠实转录、数学公式正确性、源式结构正确性及结构规则复核状态是不同事项。
- **下一步（计划，未完成）**：由负责人确认后续验证安排。

## C 模块第七步：KaTeX 真实渲染检查

**阶段状态：本地渲染检查、修复、测试及本次样本验证已完成；结果仅限本次样本和 KaTeX 0.19.1 配置。**

- **本次任务**：补充真实渲染检查，对官方样例及 3 个手写样本的 `final_latex` 实际运行 KaTeX，不修改 `recognize`／`refine` 公共契约。
- **负责人决定**：本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **实际创建／修改文件**：新增 `D:\latex\package.json`、`D:\latex\package-lock.json`、`D:\latex\reasoning\render_check.py`、`D:\latex\tests\test_render_check.py`；修改 `D:\latex\.gitignore` 以排除 `node_modules`；渲染结果写入 `D:\latex\artifacts\official_smoke.json`、`D:\latex\artifacts\handwritten_validation.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实际环境及实现**：
  - 在项目本地通过 npm 安装并固定 KaTeX 0.19.1。
  - `check_renderable` 使用 JSON stdin、无 shell、固定项目根 cwd，不改写 LaTeX。
  - KaTeX `ParseError` 返回 `renderable=False` 和 `error`；Node／`OSError`／超时／内部与协议错误抛出 `RuntimeError`。
- **外部资源**：npm 包 KaTeX 0.19.1。
- **代码审核及处理**：首轮发现本地模块路径及错误边界 2 项必须修复问题，已修复并补充测试；第二轮代码复审无阻断。渲染证据审核无阻断。
- **实际测试**：新增测试曾因 Windows 当前目录清理顺序失败，修正测试后完整 `unittest` 45 项通过；JSON 重载断言通过。
- **真实渲染结果**：官方样例与 3 个手写样本合计 `4/4 renderable=True,error=None`；其中手写样本 `3/3`，`renderable_rate=1.0`。结果已保存至上述两个 artifact。
- **结果边界**：`sample_3` 可渲染与 `low + need_review=True` 不矛盾；可渲染不证明结构正确、数学正确或识别忠实。`4/4` 和 `3/3` 仅限本次样本和 KaTeX 0.19.1 配置，不能外推。
- **未解决／未实现事项**：本次未形成模型总体或生产环境的可渲染率结论；渲染通过不能替代结构、数学及识别忠实性审核。
- **学习进度**：已明确语法可渲染性、结构规则复核和识别正确性是不同的验证维度。
- **下一步（计划，未完成）**：由负责人确认后续验证安排。

## C 模块第八步：可选 MLP 学习实验第一步——结构化特征提取

**阶段状态：特征提取、修复、测试及复审已完成；训练标签、训练和风险评分均未实施。**

- **本次任务**：开始可选 MLP 学习实验第一步，新增结构化特征提取及测试；不训练、不安装 PyTorch、不读取原图、不使用 `score`、不修改 LaTeX、不接入 `refine`，`risk_score` 仍为 `None`。
- **负责人决定**：确认本步仅实现特征，不形成训练标签、训练结果或风险分数，不宣称 MLP 有效。
- **实际创建文件**：`D:\latex\reasoning\features.py`、`D:\latex\tests\test_features.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - `FEATURE_NAMES` 固定为 8 项，顺序为 `candidate_count`、`valid_candidate_count`、`engine_count`、`error_candidate_count`、`structure_issue_count`、`has_conflict`、`selected_latex_length`、`selected_script_count`。
  - `extract_features` 返回 8 个 `float`；空候选返回全 0；输入校验及 `strip`／去重语义与 `reasoner` 对齐，且不修改输入。
  - 首轮审核发现跨引擎重复候选导致 `engine_count` 漏计，已改为在原始有效候选中累计 `supporting_engines`；其余特征仍按去重语义计算。
- **外部资源**：无；未安装 PyTorch。
- **代码审核及处理**：首轮发现上述 `engine_count` 漏计问题，已修复，并补充跨引擎、完整字段顺序、异常输入类型及 `strip` 后长度测试；最终复审无必须修复问题。
- **实际测试**：最终完整 `unittest` 53 项全部通过。
- **未解决／未实现事项**：本步只有特征提取，没有训练标签、训练结果或风险分数；未接入 `refine`，未读取原图，未使用 `score`，不能据此宣称 MLP 有效。
- **学习进度**：教导员已讲解结构化特征与人工标签的区别；二者不能混同。
- **下一步（计划，未完成）**：由负责人确认后续可选学习实验安排。

## C 模块第九步：可选 MLP 学习实验第二步——未训练的 `RiskMLP`

**阶段状态：模型结构、展示辅助、测试及复审已完成；训练、真实风险评分和 `refine` 接入均未实施。**

- **本次任务**：新增固定结构的 `RiskMLP` 及测试，仅返回 logit，并提供与训练、推断流程分离的展示辅助；不训练、不计算 BCE、不生成真实 `risk_score` 输出、不接入 `refine`。
- **负责人决定**：本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **实际创建文件**：`D:\latex\reasoning\risk_mlp.py`、`D:\latex\tests\test_risk_mlp.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实际环境及实现**：
  - 在项目 `.venv` 中通过 PyTorch 官方 CPU 索引安装 `torch 2.15.0+cpu`。
  - `RiskMLP` 固定为 `Linear(8,16) → ReLU → Linear(16,8) → ReLU → Linear(8,1)`；`forward` 仅返回 logit，不提前执行 sigmoid。
  - `risk_score` 仅作为展示辅助执行 sigmoid，并使用 `@torch.no_grad`；已添加一行说明：该值为未校准实验分数，绝不改写 LaTeX。
- **外部资源**：PyTorch 官方 CPU 索引及实际安装的 `torch 2.15.0+cpu`。
- **代码审核及处理**：只读审核无必须修复项；按建议补充语义 docstring 和严格层顺序断言，处理后再次运行完整测试。
- **实际测试**：覆盖完整层顺序、批量 shape、未提前 sigmoid、零 logit 及展示无梯度；补充审核建议前后完整 `unittest` 均为 58 项全部通过。
- **未解决／未实现事项**：模型未训练，未实现或使用 BCE，尚无真实 `risk_score` 输出，未接入 `refine`；不得宣称模型已训练、分数已校准或方法有效。
- **学习进度**：教导员已讲解 logit、sigmoid 与 `BCEWithLogitsLoss` 的关系；logit 为 0 时展示值为 0.5，但不表示 50% 的真实正确率。
- **下一步（计划，未完成）**：由负责人确认后续可选学习实验安排。

## C 模块第十步：可选 MLP 学习实验第三步——合成样本训练

**阶段状态：合成教学样本训练、测试及只读代码审核已完成；生产风险评分与集成均未实施。**

- **本次任务**：新增最小训练流程及测试，仅使用 4 条合成教学样本验证训练步骤和参数更新，不使用此前 3 个真实样本训练。
- **负责人决定**：确认 `train_risk` 显式接收 `(n,8)` features 与 `(n,1)` labels；采用 `RiskMLP` logits、`nn.BCEWithLogitsLoss` 和 Adam，训练中不提前执行 sigmoid。
- **实际创建文件**：`D:\latex\reasoning\train_risk.py`、`D:\latex\tests\test_train_risk.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - 校验输入非空、数值有限、标签仅为 0/1，并校验 `epochs` 和 `learning_rate`。
  - 每轮严格按 `zero_grad → forward → loss → backward → step` 顺序训练，返回 `model` 和 `loss_history`。
- **外部资源**：本阶段无新增外部资源。
- **代码审核及处理**：只读代码审核无必须、建议或可选项，无需修改。
- **实际测试**：仅使用 4 条合成教学样本训练 200 轮，损失较初值下降且最终 `<0.1`；单步参数变化测试通过；完整 `unittest` 63 项全部通过。
- **未解决／未实现事项**：未使用此前 3 个真实样本训练，未保存生产模型，未接入 `refine`，未修改 LaTeX，无生产 `risk_score`；不宣称 MLP 有效或已校准。
- **学习进度**：教导员已讲解训练五步；小样本损失下降不等于泛化能力或生产有效性。
- **下一步（计划，未完成）**：由负责人确认后续安排。
