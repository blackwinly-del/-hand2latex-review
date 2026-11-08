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

## C 模块第十一步：Mock 上下文候选选择

**阶段状态：Mock 流程、测试及只读审核已完成；真实 API 接入与真实上下文选择效果验证均未实施。**

- **本次任务**：仅实施 C 模块的上下文候选选择 Mock 流程及测试，不修改 A/B，不接真实 API。
- **负责人决定**：用户明确只负责 C，并确认 `choose_with_context(image_path,candidates) -> {selected_index,reason,error}` 接口；先进行模拟测试。
- **实际创建／修改文件**：新增 `D:\latex\reasoning\context.py`、`D:\latex\tests\test_context.py`；修改 `D:\latex\reasoner.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - `_request_context` 为未配置占位；Mock 成功时仅返回已有候选索引和理由，不能自由生成 LaTeX。
  - `refine` 对规范化冲突调用上下文选择；成功时仅选择已有候选。选择第二候选时，`changes` 记录 `context_candidate_selection` 的 `before`、`after`、`selected_index`、`reason`；`raw_latex` 保留选中候选原文，输入列表不变；选择第一候选不记录该项修改。
  - 上下文选择失败时保留第一有效候选，结果为 `low + need_review=True`；结构错误即使已完成候选选择仍为 `low + need_review=True`；冲突经选择后不直接升为 `high`。
- **外部资源**：本阶段无新增外部资源，未调用真实 API。
- **代码审核及处理**：只读审核无必须修复项；按建议补充负数、浮点数、字符串索引测试，非法输入不调用 API 的测试，以及第二候选含首尾空白时同时记录 `context_candidate_selection` 与 `trim_outer_whitespace` 两条 `changes` 的测试。
- **实际测试**：首轮完整 `unittest` 71 项全部通过；按审核建议补测后，最终完整 `unittest` 72 项全部通过。
- **未解决／未实现事项**：当前仅为 Mock 流程；真实 API 未接入，尚无真实上下文选择效果结论。
- **学习进度**：教导员已讲解候选选择不等于生成或改写。
- **下一步（计划，未完成）**：由负责人确认后续安排。

## C 模块第十二步：可配置 OpenAI 兼容上下文请求

**阶段状态：真实请求适配层、Mock 测试和只读审核已完成；未提供真实密钥，未调用真实 API，真实服务视觉／JSON 兼容性和选择效果未验证。**

- **本次任务**：实现可配置的 OpenAI 兼容上下文请求适配层，并完成 Mock 测试与只读审核；不修改 A/B。
- **负责人决定**：原话“直接做支持openAI接口的自由配置”。保持 `choose_with_context` 与 `refine` 公共接口不变，不改 A/B。
- **实际修改文件**：`D:\latex\reasoning\context.py`、`D:\latex\tests\test_context.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`；`D:\latex\reasoner.py` 本阶段未修改。
- **实际环境**：在项目 `.venv` 安装 `openai 3.42.1`；测试须使用 `.venv`，系统 Python 未安装该依赖。
- **配置结果**：`OPENAI_API_KEY`、`OPENAI_MODEL` 必填；`OPENAI_BASE_URL` 可空并使用 SDK 默认；`OPENAI_TIMEOUT_SECONDS` 默认 30 秒，必须为正有限数。key／model 会 `trim`，空白 `base_url` 视为未配置。
- **实现结果**：
  - 使用 OpenAI `chat.completions`；原图按 PNG／JPEG／GIF／WebP 扩展名映射为 base64 data URL；发送零基索引及原始 LaTeX 候选，并设置 `response_format=json_object`。
  - 仅返回已有候选索引和理由，不采用生成公式；严格索引／理由校验沿用。普通异常只公开异常类型和固定失败说明，配置错误保留安全变量名；`refine` 失败回退不变。
- **外部资源**：OpenAI Python SDK README（https://github.com/openai/openai-python#usage）、客户端源码（https://github.com/openai/openai-python/blob/main/src/openai/_client.py）、Images and vision（https://developers.openai.com/api/docs/guides/images-vision）、Structured Outputs／JSON mode（https://developers.openai.com/api/docs/guides/structured-outputs）、Chat Completions reference（https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create/）。兼容服务不必然支持视觉或 JSON mode。
- **代码审核及处理**：第一轮无必须修复项；采纳配置规范化、异常防泄漏、MIME 覆盖建议。第二轮无必须修复项，仅建议以后进行受控真实 API 冒烟。
- **实际测试**：初版完整 `unittest` 76 项通过（7.560s）；审核补测后 79 项首轮出现 1 个 `ERROR`，原因是 Windows `mimetypes` 未识别 `.webp`；改为固定扩展名映射后，最终主 Agent 完整 `unittest` 79 项全部通过（6.037s），审核员使用 `.venv` 复跑 79 项全部通过（6.438s）。
- **未解决／未实施事项**：真实 API 冒烟与效果评估未做；SDK 真实序列化仅经 Mock 验证；A 端到端联调未做。
- **学习进度**：已说明 OpenAI 兼容不等于所有服务支持视觉／JSON mode，配置通过环境变量与公共接口分离。
- **下一步（计划，未完成）**：负责人配置服务后再做受控真实 API 冒烟。

## C 模块第十二步补充：本地 .env 配置文件

**阶段状态：本地配置模板、加载支持、隔离测试及审核已完成；真实配置与真实 API 冒烟未完成。**

- **本次任务**：补充本地 `.env` 配置模板与加载支持，并验证忽略规则、加载路径及环境变量优先级；不读取或输出真实 `.env`。
- **负责人决定**：用户决定“给个配置文件，我来填”；公共接口不变。
- **实际创建／修改文件**：修改 `D:\latex\.gitignore`、`D:\latex\reasoning\context.py`、`D:\latex\tests\test_context.py`；创建被忽略的 `D:\latex\.env`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **配置及实现结果**：
  - `.env` 模板包含四个配置键，本记录不记录任何未来秘密。
  - `.gitignore` 第一行忽略 `.env`，`git check-ignore` 实际命中。
  - `context.py` 使用项目根路径调用 `load_dotenv(..., override=False)`，系统环境变量优先。
- **外部资源**：`python-dotenv 1.2.4`，已安装到项目 `D:\latex\.venv`。
- **代码审核及处理**：审核无必须修复项；建议补充加载路径及 `override=False` 测试，已通过隔离模块和 mock `dotenv.load_dotenv` 实现，测试不读取或修改真实 `.env`。
- **实际测试**：最终完整 `unittest` 80 项全部通过（4.924s）。
- **未解决／未实施事项**：真实配置仍待用户填写，真实 API 冒烟仍未执行。
- **学习进度**：已明确本地配置模板不等于真实配置，隔离 Mock 测试不能替代真实 API 冒烟。
- **下一步（计划，未完成）**：负责人填写并重启相关进程后再做真实冒烟。

## C 模块第十三步：真实 OpenAI 兼容上下文冒烟

**阶段状态：真实服务成功与失败回退均已实际验证；仅 1 个构造冲突样本，不能外推总体准确率、泛化或校准。**

- **本次任务**：使用真实 OpenAI 兼容服务验证上下文候选选择、失败回退及脱敏结果保存；不修改生产代码或公共接口。
- **负责人决定**：首次服务返回 400 后，诊断确认 `OPENAI_MODEL` 被传为 `true`，提供商只接受 `deepseek-flash`／`deepseek-v4-pro`；用户选择 `deepseek-flash`，已修改被 Git 忽略的 `D:\latex\.env` 中的模型名。
- **配置检查**：用户确认已填写 `.env`；主 Agent 仅检查四个变量是否存在，未输出密钥或 `base_url`，本记录亦不包含其值。
- **实际创建／修改文件**：新建 `D:\latex\artifacts\context_smoke.json`，保存脱敏结果；修改被忽略的 `D:\latex\.env` 模型名；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。本阶段未修改生产代码或公共接口。
- **构造样本**：使用 `D:\latex\data\handwritten\sample_1.png`；候选 0 的分母 `(x+1)` 为故意错误，候选 1 的分母 `(x-1)` 为用户此前确认的正确忠实转录，期望索引为 1。
- **真实调用及回退结果**：
  - 首次真实请求返回 `BadRequestError`，耗时 636.917ms；`refine` 保留错误的首候选，结果为 `low + need_review=True`。
  - 第二次诊断请求重现 400，仅读取经配置值遮蔽的错误类型和消息；据此完成上述模型配置诊断。
  - 修正模型后第三次真实请求成功，选择索引 1，理由指出图中是 `(x-1)`，耗时 1442.32ms。
  - 复用同一真实响应 patch 回 `refine`，未额外发起第四次请求；`refine` 选择正确公式，`confidence=medium`、`need_review=False`、`risk_score=None`，并记录 `context_candidate_selection` 的 `before`／`after`／索引／`reason`。
- **外部资源**：实际调用了用户配置的 OpenAI 兼容服务；不记录其 `base_url` 或密钥。
- **代码审核及处理**：本阶段无生产代码改动，未进行新的代码审核。
- **实际测试**：此前 80 项 `unittest` 通过；本阶段未宣称重新运行。上述结果为真实请求及同一响应回放的实际冒烟结果。
- **未解决／未实施事项**：只有 1 个构造冲突样本，真实多样本选择效果及 A 端到端联调未完成。
- **学习进度**：已实际区分“接口连通／单样本成功”和“总体效果已验证”。
- **下一步（计划，未完成）**：扩大人工确认冲突样本并进行同样本评估。

## C 模块第十四步：冲突基准、真实评估与结构漏报修复

**阶段状态：3 个构造冲突样本的真实评估、失败回归、结构漏报修复及离线回放已完成；真实选择错误本身尚未修复，不能外推总体。**

- **本次任务**：用户授权“你来做吧”，范围仅限 C；建立最小 3 样本构造冲突基准，进行同样本评估、3 次真实 API 调用和失败回归；不修改 A/B 或公共接口。
- **负责人决定**：用户确认上述授权及范围；保持公共 `refine` 字段不变，仅将复核策略调整为更保守。
- **实际创建／修改文件**：新建 `D:\latex\artifacts\context_conflict_samples.json`、`D:\latex\reasoning\context_benchmark.py`、`D:\latex\tests\test_context_benchmark.py`、`D:\latex\artifacts\context_benchmark_results.json`、`D:\latex\artifacts\context_benchmark_replay_after_review_fix.json`；修改 `D:\latex\reasoning\evaluate.py`、`D:\latex\tests\test_evaluate.py`、`D:\latex\reasoner.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **基准数据**：3 个样本均来自人工确认的忠实转录；样本 1 为分母符号冲突，样本 2 表明常规数学写法不等于忠实转录，样本 3 表明结构修补不等于忠实转录。正确索引为 `1/0/1`，构成交错；已通过脚本断言与 `D:\latex\artifacts\handwritten_validation.json` 一致。
- **实现结果**：
  - 每个样本仅直接请求一次 `choose_with_context`，同一响应回放至 `refine`；baseline 显式取 `candidates[0]`，不是 `refine` 选择后的 `raw`。
  - 拒绝重复或无效候选；指标包括 baseline／final exact、错误改写、错误拦截／漏报、误报复核、成功选择准确率及 fallback。
  - 运行器中的延迟字段明确命名为 `context_latency_ms`；独立 `refine` 延迟未测。
- **真实 API 评估**：使用 `deepseek-flash`，3 次真实请求均成功返回，`fallback=0`；样本 1、2 选择正确，样本 3 错选结构修补候选 0。原始结果保存于 `D:\latex\artifacts\context_benchmark_results.json`：baseline correct `1/3`，final correct `2/3`，context selection `2/3`，错误改写 `0`，review `0`，missed error `1`，error interception `0`；真实请求延迟 median `2260.118ms`、nearest-rank p95 `2325.435ms`。结果仅来自 3 个构造样本，不能外推总体。
- **结构漏报修复**：`D:\latex\reasoner.py` 改为任一去重后候选存在结构异常即 `need_review=True`，即使选择了另一候选；不修改 LaTeX。已新增样本 3 真实失败响应的回归测试。
- **离线回放**：使用保存的 3 个真实 `context_result`，未新增 API 调用；最终选择仍为 `2/3`，review `1/3`，intercepted `1`、missed `0`、`error_interception_rate=1.0`、`false_review_rate=0`。结果保存于 `D:\latex\artifacts\context_benchmark_replay_after_review_fix.json`，明确不是新的真实 API 评估；`source_context_latency` 仅为历史真实请求耗时。原始 artifact 仅追加延迟说明，未修改真实选择结果。
- **外部资源**：真实评估实际调用了用户配置的 OpenAI 兼容服务，模型为 `deepseek-flash`；离线回放及本次日志记录未调用 API，未读取 `.env`。
- **代码审核及处理**：首轮审核发现 raw 基线口径错误，已修正；后续审核无必须修复项，按建议补充真实数据离线测试和重复候选校验。漏报修复后增加真实失败响应回归；最终审核无必须修复项，延迟含义建议已通过字段及 artifact 说明处理。
- **实际测试**：首轮 84 项中 1 项 FAIL，发现 raw 基线口径错误；修正后 84 项全部通过（5.712s）。补真实数据离线测试和重复候选校验后 86 项全部通过（3.371s）；真实漏报修复后 87 项全部通过（5.102s）；最终延迟命名澄清后 87 项全部通过（4.741s）。
- **未解决／未实施事项**：样本 3 的真实选择错误本身尚未修复；仅有 3 个构造冲突样本，样本量不足；未做新的真实 API 复测、A 联调或 MLP 生产化。
- **学习进度**：真实基准能够发现 Mock 无法发现的选择漏报；提高错误拦截不等于提高选择准确率。
- **下一步（计划，未完成）**：扩大自然／构造冲突样本，另行评估提示词或选择策略。

## C 模块第十五步：提示词改进、指标语义与稳定性对照

**阶段状态：提示词与指标语义修改、测试、审核及两组真实对照已完成；选择稳定性、高延迟、自然冲突和 A 联调仍未解决，下一步仅为计划。**

- **本次任务**：用户授权“检查一下，继续完善，我先出去一会”；仅完善 C 模块，不修改 A/B 或公共接口。
- **负责人决定**：确认上述授权及范围；对照后停止对同一样本继续调参，以避免过拟合。
- **检查发现**：旧提示未明确禁止结构整洁偏好；`false_review` 将忠实但需结构复核的结果误称为误报。
- **实际创建／修改文件**：修改 `D:\latex\reasoning\evaluate.py`、`D:\latex\tests\test_evaluate.py`、`D:\latex\tests\test_context_benchmark.py`、`D:\latex\reasoning\context.py`、`D:\latex\tests\test_context.py`；旧 artifact `D:\latex\artifacts\context_benchmark_results.json`、`D:\latex\artifacts\context_benchmark_replay_after_review_fix.json` 仅增加语义注释，历史数值不变；新建 `D:\latex\artifacts\context_benchmark_results_prompt_v2.json`、`D:\latex\artifacts\context_sample_3_prompt_comparison.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - 指标改为 `correct_final_review_count`／`correct_final_review_rate`，不再把忠实但需结构复核称为误报。
  - `context.py` 提取 `_CONTEXT_SYSTEM_PROMPT`；新提示要求只选择图中可见符号，即使数学无效或结构不完整，也不偏爱常规、完整或整洁形式；仍只返回已有候选索引和理由。
  - `test_context.py` 补全 existing candidate、visibly present、不生成／纠正／简化及零基索引等完整提示词契约断言。
- **独立新提示真实基准**：执行 3 次真实请求，结果保存至 `D:\latex\artifacts\context_benchmark_results_prompt_v2.json`，未覆盖旧结果。选择正确 `3/3`，fallback `0`，final exact `3/3`；样本 3 忠实原文但为 `low + need_review=True`，`correct_final_review_rate=1/3`；context median `2120.01ms`、nearest-rank p95 `9438.044ms`。仅为单轮 3 样本，不能据此宣称稳定。
- **代码审核及处理**：审核无必须修复项；建议重复样本 3 和补完整提示词断言，均已采纳。
- **重复稳定性真实对照**：保持模型、候选和配置一致，旧／新提示交替各执行 3 次真实请求，共 6 次，结果保存至 `D:\latex\artifacts\context_sample_3_prompt_comparison.json`。旧提示 `0/3` 正确，新提示 `2/3` 正确（索引 `1/0/1`）；fallback 均为 `0`，当前安全复核均为 `3/3`。旧提示中位延迟 `2996.302ms`，新提示 `7460.756ms`。新提示有改善但不稳定，且本组更慢；已停止对同一样本继续调参。
- **外部资源**：上述历史真实基准和对照实际调用了用户配置的 OpenAI 兼容服务；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **实际离线测试**：提示词／指标改动后完整 `unittest` 87 项全部通过（4.785s）；审核员离线复跑 87 项全部通过（4.792s）；补完整提示词契约后最终 87 项全部通过（4.950s）。2 个新 JSON artifact 均已实际解析验证；`git diff --check` 通过，仅有换行警告。这些离线检查与上述真实请求结果分开记录。
- **未解决／未实施事项**：新提示在样本 3 上仍有 `1/3` 错选，选择稳定性未解决；样本仍少且均为构造冲突；高延迟、自然冲突和 A 联调未完成；无 MLP 生产结论。
- **学习进度**：单轮 `3/3` 不等于稳定，重复对照能揭示随机性；正确结果复核不等于误报。
- **下一步（计划，未完成）**：扩大多样化冲突集后再评价提示与延迟，不在同一样本继续调参。

## C 模块第十六步：十样本多样化冲突真实评估

**阶段状态：10 个构造样本的 Mock 离线回归、真实评估、审核及结果保存已完成；未解决事项与下一步计划仍未实施。**

- **本次任务**：用户授权“ok，继续推进”，范围仅限 C；扩大构造冲突样本并进行离线回归和真实评估，不修改 A/B。
- **负责人决定**：确认上述授权及范围；本阶段未提供需新增记录的公共接口或其他重要技术选择决定。
- **实际创建／修改文件**：新建 `D:\latex\artifacts\context_conflict_samples_v2.json`、`D:\latex\artifacts\context_benchmark_results_v2.json`；修改 `D:\latex\tests\test_context_benchmark.py`，新增 v2 数据回归、10 次 Mock 离线运行及数据集结构复核说明；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **v2 构造数据**：从 3 张人工确认底图派生 10 个二选一构造冲突，覆盖分母符号、指数、常数、分子系数、常规化补 `x`、prime、sin 平方、结构补括号、极限目标和 `1/4` 系数；正确索引 0／1 各 5。脚本已验证 ID、图片、真值、唯一性和期望候选，确认 `5/5` 平衡；样本 3 明确为 `low + need_review`。
- **真实 API 评估**：使用显式 v2 输入和独立输出执行 10 次真实 API 请求，断言结果共 10 条，保存至 `D:\latex\artifacts\context_benchmark_results_v2.json`，未覆盖历史结果。candidate0 baseline exact `5/10`，final exact `10/10`，context selection `10/10`，fallback `0`，错误改写 `0`，review `3/10`，`correct_final_review=3/10`；3 个样本 3 变体均忠实且为 `low + need_review`，5 次实际候选切换均记录 `changes`。
- **真实请求延迟**：仅测 `choose_with_context`，不含 `refine`；context median `1993.2685ms`，nearest-rank p95 `21363.249ms`。`n=10` 时 p95 就是最大值；离群样本为 `sample_3_faithful_not_structural_repair`，另两个样本 3 变体分别为 `3375.638ms`、`4864.171ms`。离群原因未确定，不归因于结构审查。
- **结果边界**：结果 artifact 已加入 scope／latency／review 说明。baseline 只是构造对中的候选 0，不是独立无上下文系统；`10/10` 只限这 10 个由 3 张底图派生的二选一构造样本，不能外推 OCR 总体准确率或稳定性。本轮无最终错误，`error_interception_rate=null`，不能宣称拦截有效；`correct_final_review` 不是错误拦截；`renderable_rate=null`。
- **外部资源**：上述真实评估实际调用了用户配置的 OpenAI 兼容服务；Mock 离线测试及本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：审核数值一致，无必须修复项；建议均已采纳，并强调上述样本、baseline、延迟及复核指标限制。
- **实际离线测试与检查**：完整 `unittest` 首次 88 项全部通过（7.206s）；补直接 v2 离线测试后最终 88 项全部通过（5.048s）。结果 JSON 解析及 10 条断言通过，`git diff --check` 通过，仅有换行警告。这些均为 Mock／离线检查，与上述真实 API 结果分开记录。
- **未解决／未实施事项**：自然冲突、更多底图、选择稳定性及长尾延迟原因仍未解决；本轮无最终错误，不能评价漏报率；无 MLP 生产结论。
- **学习进度**：扩大构造样本可提高覆盖面，但仍不等于独立真实分布；小样本 p95 可能只是最大值。
- **下一步（计划，未完成）**：获得更多人工确认底图／自然冲突后再扩大评估，不在当前样本继续调参。

## C 模块第十七步：基准渲染评估与无 API 离线回放

**阶段状态：基准渲染评估、无 API 离线回放、测试、审核及结果保存已完成；未解决事项与下一步计划仍未实施。**

- **本次任务**：用户“继续干活”，范围仅限 C；为既有基准补充 KaTeX 可渲染评估及保存真实响应的本地回放，不修改 A/B，不读取 `.env`，不调用 API。
- **负责人决定**：确认上述授权及范围；公共 `refine` 接口保持不变。
- **实际创建／修改文件**：修改 `D:\latex\reasoning\context_benchmark.py`、`D:\latex\tests\test_context_benchmark.py`；新建 `D:\latex\artifacts\context_benchmark_results_v2_rendered.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。源文件 `D:\latex\artifacts\context_benchmark_results_v2.json` 未被改写。
- **实现结果**：
  - `run_context_benchmark` 对 `final_latex` 调用现有 `check_renderable`，保存 `render_result`／`renderable`；检查器故障仍抛错，不将其当作公式不可渲染。
  - 新增 `replay_context_benchmark`，深拷贝保存报告，复用已保存的 `context_result` 回放 `refine` 和 KaTeX；拒绝覆盖源文件，保留历史延迟及源 `scope`／`review` 说明，`additional_api_calls=0`。
  - 测试覆盖 Mock 渲染、回放源不变、渲染失败、拒绝覆盖、元数据保留和无 API；无 API 测试直接 patch `reasoner.choose_with_context` 并 `assert_not_called`。
- **实际离线回放**：使用 `D:\latex\artifacts\context_benchmark_results_v2.json` 中 10 个已保存真实响应进行本地 `refine` 回放和 KaTeX 检查，无新增 API 调用；输出保存至 `D:\latex\artifacts\context_benchmark_results_v2_rendered.json`。源文件仍无 `render_result` 且未被改写；输出 10 条 `render_result` 均 `renderable=True`、`error=None`。
- **回放摘要**：final exact `10/10`，`renderable_rate=1.0`，review `3/10`，`correct_final_review=3/10`；3 个样本 3 变体同时忠实、可渲染且为 `low + need_review`，证明三个维度独立。baseline `5/10` 和 context latency median `1993.2685ms`、nearest-rank p95 `21363.249ms` 均为历史真实请求值，不是回放性能。
- **结果边界**：输出保留 `evaluation_scope`、`review_note`、`render_note`。样本仅为 3 张底图派生的构造冲突，不能外推总体或稳定性；可渲染不等于结构有效或忠实；本轮无最终错误，不能宣称错误拦截有效；`renderable_rate` 与 review 指标独立。
- **外部资源**：复用上述 artifact 中已保存的真实响应和项目现有本地 KaTeX 检查器；本阶段未调用 API、未读取 `.env`，无新增外部资源。
- **代码审核及处理**：审核无必须修复项，仅指出无 API 测试的 Mock 目标不准确；已改为直接 patch `reasoner.choose_with_context` 并 `assert_not_called`。审核员禁用网络复跑 90 项全部通过（5.390s）。
- **实际测试与检查**：初版完整 `unittest` 90 项全部通过（6.397s）；保留元数据后 90 项全部通过（5.476s）；审核员禁用网络复跑 90 项全部通过（5.390s）；修正 Mock 目标后最终 90 项全部通过（5.112s）。实际验证源文件未改、10 条 KaTeX 结果及 3 条结构复核；`git diff --check` 通过，仅有换行警告。
- **未解决／未实施事项**：更多底图／自然冲突、选择稳定性及 API 长尾延迟仍未解决；本次可渲染率不推广到其他样本；无 MLP 生产结论。
- **学习进度**：忠实转录、结构检查和 KaTeX 可渲染必须分别报告；离线回放可减少重复付费，但不能替代新的真实评估。
- **下一步（计划，未完成）**：用新增真实样本复用同一评估与回放流程。

## C 模块第十八步：评估预检、原子检查点与失败恢复

**阶段状态：预检、原子检查点、失败恢复、测试、审核及真实历史响应回放已完成；未解决事项与下一步计划仍未实施。**

- **本次任务**：用户“进行完善”，范围仅限 C，不继续调提示；完善评估可靠性和已付费响应保护，公共 `refine` 接口不变。
- **负责人决定**：确认上述授权及范围；本阶段未提供需新增记录的公共接口或其他重要技术选择决定。
- **实际修改文件**：`D:\latex\reasoning\context_benchmark.py`、`D:\latex\tests\test_context_benchmark.py`；更新 `D:\latex\artifacts\context_benchmark_results_v2_rendered.json`，仅为当前无 API 回放输出；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **预检结果**：运行前校验所有样本非空、`sample_id` 非空且唯一、`image_path` 非空、至少 2 个候选、候选有效且唯一、`ground_truth` 非空、`expected_index` 在范围内且期望候选等于真值；输出目录必须已存在。`run` 和 `replay` 均拒绝输入输出同路径；预检或同路径保护失败时零 API 且原数据不变。
- **持久化与恢复**：每获得 `context_result` 立即先写 `summary=None`、`status=context_response_saved_refine_pending`；`refine` 后写 `context_responses_saved_render_pending`；全部响应完成后才渲染，最终为 `complete`。任一记录暂缺 `refine_result` 时不强行计算摘要；pending 可直接 replay。
- **原子写**：在同目录写入 `.tmp` 后使用 `os.replace`，并在 `finally` 清理；Mock 注入 `Path.write_text` 失败时，旧有效 JSON 保持不变且无 tmp 残留。
- **Mock 故障注入测试覆盖**：后续无效样本、空图片、单候选及缺输出目录均零 API；第二请求注入 `FileNotFoundError` 时保留首响应；两样本渲染中途注入失败时，pending 的两个结果均无 `renderable`，并可直接 replay 至 `complete`；注入 `refine` 异常时当前原始响应已保存、`summary=None`，无 API replay 成功；另覆盖输入输出同路径保护及原子写故障。这些均为 Mock 故障注入，不是真实服务故障记录。
- **外部资源**：无新增外部资源；本阶段未调用 API、未读取 `.env`。
- **代码审核及处理**：首轮 93 项通过（4.596s），审核员复跑 93 项通过（4.290s）并发现后续输入错误丢失风险；补预检和每响应保存后 95 项通过（4.632s）；加入原子写后 96 项通过（4.441s）；最终审核发现 refine 前未落盘及 run 覆盖输入风险，修复后 98 项全部通过（4.568s）。最终审核明确当前 MVP 范围无必须修复项。
- **真实历史响应本地回放**：使用现有 10 个已保存真实响应进行本地回放，无新增 API；最终 `status=complete`，final exact `10/10`、`renderable_rate=10/10`、review `3/10` 均不变。该结果复用历史真实响应，与上述 Mock 故障注入测试明确区分。
- **实际检查**：`git diff --check` 通过，仅有换行警告。
- **未解决／未实施事项**：这些测试证明失败恢复，不证明上下文选择准确率或稳定性；更多底图、自然冲突和 API 长尾仍未解决；无 MLP 生产结论。
- **学习进度**：评估工具也必须保护实验数据；原子检查点和可回放 pending 能避免异常导致重复付费。
- **下一步（计划，未完成）**：新增真实样本时沿用预检、检查点和回放，不继续假设性扩展。

## C 当前最新状态（2026-11-03）

**阶段状态：以下仅汇总已有完成项和真实结果；下一步均为计划，本次仅追加日志。**

- **范围与本次修改**：仅 C，不把 A/B 列为我们的任务；本次仅追加 `D:\latex\reasoning\TEAM_LOG.md`，未修改其他文件。
- **已完成**：规范化／去重、结构检查与人工复核、`raw`／`final`／`changes` 保留、可配置 OpenAI 兼容上下文选择（只选已有索引）、API 失败回退、真实 KaTeX 检查、10 个构造冲突的真实评估、预检、原子检查点和 pending 离线回放。
- **最新真实／回放指标**：10 个样本均由 3 张人工确认底图派生，为二选一构造冲突；candidate0 baseline `5/10`，final exact `10/10`，KaTeX renderable `10/10`，review `3/10`。真实 context 请求 median `1993.2685ms`；`n=10` 时 nearest-rank p95 即最大值 `21363.249ms`。渲染及回放结果复用已保存真实响应，不是新的真实 API 评估。
- **结果边界**：上述结果不能外推总体 OCR 准确率或稳定性；本轮无最终错误，不能据此证明错误拦截能力。
- **稳定性证据**：样本 3 重复对照中旧提示 `0/3`、新提示 `2/3`，新提示仍有随机性；安全复核均为 `3/3`。
- **最新离线验证**：第十八步最终完整 `unittest` 98 项全部通过（4.568s）；本次状态更新未重新运行测试，未新增外部资源或代码审核。
- **当前工作区**：仍有未提交的 C 代码、测试、实验产物和日志；未创建新 Git 提交。
- **未解决**：更多底图／自然冲突、选择稳定性、API 长尾延迟；MLP 仍只是教学实验，无生产风险评分或效果结论。
- **学习进度**：已明确构造样本结果、重复选择稳定性、可渲染性及失败恢复需分别判断，均不能替代总体效果验证。
- **下一步（计划，未完成）**：新增人工确认底图或自然冲突后，沿用预检、检查点、真实评估和离线回放；不在现有样本上继续调参。

## C 模块混合识别实验：中文与公式拆分尝试

**阶段状态：2 次真实多模态请求及结果保存已完成；本样本公式成功、中文失败，混合识别未成功，参考与人工复核仍待确认。**

- **本次任务**：用户要求尝试改进 OCR 配置以支持中文公式混合；主 Agent 说明 PP-FormulaNet-L 配置属于 B，且不会可靠增加中文能力。用户明确选择“C侧混合识别实验（推荐）”，因此未修改 B、OCR 配置、生产代码或公共接口。
- **负责人决定**：确认采用 C 侧混合识别实验；不通过修改 B 的 PP-FormulaNet-L 配置宣称获得中文能力。
- **实际修改文件**：实验结果保存至 `D:\latex\artifacts\mixed_ocr_smoke.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **真实实验**：对 `D:\latex\data\handwritten\sample_6.png` 使用现有 `deepseek-flash` 进行 2 次真实多模态请求，均要求返回 `{text,latex}`，且提示中不提供预期中文。
  - 第一次使用英文提示，耗时 `2617.012ms`；`text` 为“ԭʽ”，`latex` 为 `\lim_{t\to0}\frac{t-\ln(1+t)}{t^2}`。
  - 第二次使用中文提示并明确禁止拼音、乱码和猜测，耗时 `2561.92ms`；`text` 仍为“ԭʽ”，`latex` 为 `\lim_{t\to 0}\frac{t-\ln(1+t)}{t^2}`。
- **结果与边界**：两次公式均与待用户确认的参考一致，但中文均与“原式”不符，不能算混合识别成功。artifact 中 `reference` 和 `human_review` 仍为 `pending`，不计算准确率。结论仅限当前服务在此样本上公式成功、中文失败；提示调整未解决中文问题，不宣称支持中文混排。
- **外部资源**：上述实验实际使用了现有 `deepseek-flash` 多模态服务；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，未做新代码审核。
- **实际测试**：未运行单元测试，原因是无代码改动；上述结果仅为 2 次真实多模态请求，不作为单元测试或总体效果评估。
- **未解决事项**：当前服务在该样本上的中文识别失败，参考与人工复核仍待确认，尚无中文混排支持或准确率结论。
- **学习进度**：公式输出正确不能证明同次请求的中文输出正确；加强提示约束未解决本样本的中文乱码问题。
- **下一步（计划，未完成）**：若继续，需评估支持中文的视觉模型或独立中文 OCR；这属于新的识别方案，不在当前 C 生产范围。不在同样本继续堆提示。

## C 模块新增真实样本：样本 6 OCR 冲突评估

**阶段状态：样本 6 的确认、1 次真实上下文请求、本地 KaTeX 检查及结果保存已完成；样本 4/5 仍 pending，下一步仅为计划。**

- **本次任务**：记录用户“确认样本 6 的标准转录”，并保存该真实 OCR 冲突样本的上下文评估结果；本次仅追加日志，不修改其他文件。
- **负责人决定**：样本 6 的纯公式真值确认为 `\lim\limits_{t\rightarrow0}\frac{t-\ln(1+t)}{t^{2}}`；题号和中文原式不纳入。样本 4/5 仍待确认。
- **评估阶段实际创建／修改文件**：`D:\latex\artifacts\handwritten_new_samples.json` 中样本 6 已写入 `ground_truth` 和 `confirmed_correct`，真实 PP-FormulaNet 候选保持不变；新建 `D:\latex\artifacts\context_conflict_sample_6.json` 和 `D:\latex\artifacts\context_benchmark_sample_6.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **冲突样本**：候选 0 为真实 OCR 错误前缀 `(3)\sqrt{\frac{1}{n}}+1=...`，候选 1 为用户确认的正确公式，`expected_index=1`。
- **真实评估结果**：使用 `deepseek-flash` 执行 1 次真实上下文请求，并执行本地 KaTeX 检查；结果保存至 `D:\latex\artifacts\context_benchmark_sample_6.json`，`status=complete`。模型选择索引 1，理由指出候选 0 含图中不存在的根式。
- **指标与延迟**：raw baseline `0/1`，final exact `1/1`，renderable `1/1`，review `0`，fallback `0`；`changes` 记录从错误候选切换到正确候选。context latency `7478.977ms`；OCR 此前 latency `14826.419ms`。
- **结果边界**：仅 1 个样本、1 次真实请求，不能宣称选择稳定或总体准确率；`error_interception_rate=null`。
- **外部资源**：上述评估实际使用了用户配置的 `deepseek-flash` 服务和本地 KaTeX；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，无新增代码审核意见。
- **实际检查**：未重跑单元测试；已解析并断言确认文件和结果文件，`git diff --check` 通过，仅有换行警告。
- **未解决事项**：样本 4/5 尚未确认；本样本结果不足以评价稳定性、总体准确率或错误拦截能力。
- **学习进度**：真实 OCR 错误可作为上下文冲突候选，但单样本成功不能替代多样本和重复评估。
- **下一步（计划，未完成）**：样本 4/5 待确认后再评估；本次不将其写为已完成。

## C 模块新增真实样本：样本 4–6 完整评估

**阶段状态：样本 4/5 用户确认、3 样本单轮真实评估、真实写盘故障后的无 API 离线恢复、Mock 回归及结果保存已完成；下一步仅为计划。**

- **本次任务**：完成新增真实样本 4–6 的人工确认、冲突评估、渲染结果恢复及故障回归；本次仅追加日志，不修改其他文件。
- **负责人决定**：用户已确认样本 4、5，样本 6 真值维持此前确认；至此样本 4/5/6 全部为 `confirmed_correct`，`D:\latex\artifacts\handwritten_new_samples.json` 的 `review_status=ground_truth_user_confirmed`。本阶段无新增公共接口或重要技术选择决定。
- **评估阶段实际创建／修改文件**：更新 `D:\latex\artifacts\handwritten_new_samples.json`；新建 `D:\latex\artifacts\context_conflict_new_samples.json`、`D:\latex\artifacts\context_benchmark_new_samples.json`、`D:\latex\artifacts\context_benchmark_new_samples_rendered.json`；修改 `D:\latex\tests\test_context_benchmark.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。无生产逻辑修改。
- **新建冲突样本**：
  - 样本 4：候选 0 为真实 OCR 正确结果，候选 1 为将常数 `4` 改为 `1` 的构造错误。
  - 样本 5：候选 0 为分母 `x+1` 的构造错误，候选 1 为真实 OCR 正确结果。
  - 样本 6：候选 0 为真实 OCR 错误前缀结果，候选 1 为用户确认结果。
- **真实 API 评估**：使用 `deepseek-flash` 执行 3 次真实请求。真实 OCR 本身在样本 4/5 正确、样本 6 错误，即 `2/3`；这不等于 benchmark 的 candidate0 baseline `1/3`。上下文选择 `3/3`，fallback `0`，final exact `3/3`，renderable `3/3`，review `0`，错误改写 `0`。
- **真实请求延迟**：context latencies 分别为 `2150.6ms`、`1270.342ms`、`2248.92ms`，median `2150.6ms`；`n=3` 时 nearest-rank p95 即最大值 `2248.92ms`。仅为 3 个样本的单轮结果，不能外推稳定性或总体表现。
- **实际故障与无 API 离线恢复**：最终写渲染结果时，Windows `os.replace` 实际发生 `PermissionError`，这不是 Mock 故障；`D:\latex\artifacts\context_benchmark_new_samples.json` 的 `render_pending` 检查点已保存 3 个真实响应。随后直接离线 replay 到新文件 `D:\latex\artifacts\context_benchmark_new_samples_rendered.json`，无新增 API，`status=complete`，3 个样本结果全部恢复；不重复请求。
- **外部资源**：上述真实评估实际使用了用户配置的 `deepseek-flash` 服务及本地 KaTeX；离线恢复、Mock 回归和本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：本阶段未提供新增代码审核意见；真实故障通过回归测试覆盖，无生产逻辑修改。
- **Mock 回归、实际测试与检查**：针对上述真实故障，在 `D:\latex\tests\test_context_benchmark.py` 增加第三次 `os.replace` 失败的 Mock 回归，验证 pending 保留且无 tmp 残留；完整 `unittest` 99 项全部通过（5.422s）。已断言样本全部确认、3 条完整结果以及 final／renderable／fallback 指标；`git diff --check` 通过，仅有换行警告。结果文件未提交。
- **未解决事项**：当前只有 3 个样本的单轮评估，不能据此宣称选择稳定或总体有效；不宣称中文混排支持。
- **学习进度**：真实 OCR 正确率与构造基准 candidate0 baseline 必须分开报告；真实写盘故障可由已保存响应离线恢复，Mock 回归用于防止同类故障复发，二者不能混同。
- **下一步（计划，未完成）**：获得更多不同底图／自然冲突后再评估；本次日志记录未调用 API。
