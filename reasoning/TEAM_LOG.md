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

## C 模块真实样本：样本 4–6 重复稳定性评估

**阶段状态：提交、3 个样本各 3 轮真实评估、汇总及离线检查已完成；结果仅限本组小规模重复检查，下一步仅为计划。**

- **本次任务**：用户同意开发优先级后，先提交已有真实手写样本扩充，再对样本 4–6 进行重复稳定性评估；本次仅追加日志，不修改其他文件。
- **负责人决定**：确认先创建 Git 提交 `85a12df`（`扩充真实手写样本评估`），共 12 个文件，提交后工作区干净；随后开展真实重复评估。本阶段无新增公共接口或重要技术选择决定。
- **评估阶段实际创建／修改文件**：每轮均使用 `run_context_benchmark`，分别保存 `D:\latex\artifacts\context_stability_run_1.json`、`D:\latex\artifacts\context_stability_run_2.json`、`D:\latex\artifacts\context_stability_run_3.json`；汇总保存至 `D:\latex\artifacts\context_stability_new_samples.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。无生产代码改动。
- **真实重复评估**：输入为 `D:\latex\artifacts\context_conflict_new_samples.json` 中样本 4–6，使用 `deepseek-flash` 各执行 3 轮真实请求，共 9 次；三轮报告均为 `complete`。三轮选择均为 `[0,1,1]`，最终正确 `9/9`、fallback `0`、renderable `9/9`；3 个样本均 3 次选择一致且始终正确。
- **真实请求延迟**：总体 median `1826.244ms`、min `1651.139ms`、max `3626.861ms`。样本 4 median `2784.642ms`、max `3626.861ms`；样本 5 median `1774.304ms`、max `1791.909ms`；样本 6 median `2088.687ms`、max `2624.15ms`。
- **结果边界**：仅为 3 个已确认真实冲突各 3 次的小规模稳定性检查，不是总体准确率；不推翻此前样本 3 的不稳定结果和更长尾延迟结果。
- **外部资源**：上述评估实际使用了用户配置的 `deepseek-flash` 服务和本地 KaTeX；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，未提供新增代码审核意见。
- **实际测试与检查**：未重跑单元测试；已解析三轮报告和汇总，并断言 9 次选择一致、9 次可渲染；`git diff --check` 无输出。新结果未提交。
- **未解决事项**：样本数量和底图多样性仍不足，自然冲突、总体稳定性及更长尾延迟仍未解决；本组一致结果不能替代此前相反证据。
- **学习进度**：同组重复一致只能支持当前小样本的稳定性观察，不能外推总体，也不能抹去其他样本的不稳定或长尾结果。
- **下一步（计划，未完成）**：增加更多不同底图和自然冲突，再评估稳定性和长尾；本次日志记录未调用 API。

## C 模块公共契约讨论稿与渲染异常边界复核

**阶段状态：公共契约讨论稿、两项审核问题处理、测试与复核已完成；讨论稿尚未由 A/B/C 共同冻结，下一步仅为计划。**

- **本次任务**：用户要求整理 C 模块公共契约文档，并复核候选字段类型约束与渲染异常边界；本次仅追加日志，不修改其他文件。
- **负责人决定／文档定位**：新建 `D:\latex\reasoning\CONTRACT.md`，版本 `v0.1`、日期 `2026-11-03`，供 A/B/C 讨论；该稿尚未共同冻结，不替代公共契约共同确认流程。本阶段未修改公共接口。
- **实际创建／修改文件**：新建 `D:\latex\reasoning\CONTRACT.md`；修改 `D:\latex\reasoning\render_check.py`、`D:\latex\tests\test_render_check.py`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **讨论稿内容**：按真实实现记录 `refine` 输入输出、`raw`／`final`／`changes` 语义、候选格式、置信与复核决策、异常、`choose_with_context`、环境变量、`check_renderable`、示例、非目标和变更流程。
- **关键语义与边界**：`raw` 可能是上下文选中的候选，不必然是最初首候选；任一候选存在结构异常仍需复核；可渲染、识别忠实和结构有效相互独立；`risk_score=None`。
- **首轮审核及处理**：
  - 发现候选字段类型的调用方前置约束与运行时校验描述可能歧义。文档已明确 `engine`、`score`、`latency_ms`、`error` 的类型是调用方前置约束；当前仅保证校验容器、候选 `dict` 和 `latex`，越约行为不作兼容保证。
  - 发现 `render_check` 在 Windows 编码异常时可能抛出 `UnicodeDecodeError`，而非约定的 `RuntimeError`。已将 `D:\latex\reasoning\render_check.py` 改为 `encoding=utf-8`，并将 `UnicodeError` 转为 `RuntimeError`；`D:\latex\tests\test_render_check.py` 新增解码失败和 encoding 断言。
- **复核结果**：最终复核无必须修复项；上述两项首轮问题均已处理。
- **外部资源与 API**：本次日志追加未使用外部资源、未调用 API；上述阶段未提供新增外部资源记录。
- **实际测试与检查**：最终完整 `unittest` 100 项全部通过（7.367s）；审核员 `render_check` 13 项全部通过（0.628s）；`git diff --check` 通过，仅有换行警告。本次日志追加未重新运行测试。
- **Git 状态**：未创建 Git 提交。
- **未解决／未实现事项**：讨论稿不代表 A/B/C 已冻结公共契约；中文混排和 MLP 生产仍未实现。
- **学习进度**：已明确调用方前置约束与当前运行时校验保证需分别描述；Windows 文本解码异常应纳入渲染检查器的 `RuntimeError` 异常边界。
- **下一步（计划，未完成）**：与 A/B 讨论多候选来源、反馈格式、展示口径和冻结时间；本次不将讨论或冻结写为已完成。

## C 模块契约 v0.2：错误定位与局部修正讨论提案

**阶段状态：`CONTRACT.md` v0.2 文档整理、两轮审核及修正已完成；第 13–15 节均为未实现讨论提案，当前 `refine` 不变，下一步仅为计划。**

- **本次任务**：按用户要求，将新增错误定位与局部修正思路整理进 `D:\latex\reasoning\CONTRACT.md`；本次仅追加日志，不修改其他文件。
- **负责人确认的文档范围（非契约冻结决定）**：文档升级为 `v0.2`；第 1–12 节仍描述现有实现，第 13–15 节明确标记为未实现讨论提案，不改变当前 `refine`。
- **实际修改文件**：所述文档阶段修改 `D:\latex\reasoning\CONTRACT.md`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。无生产代码改动。
- **`IssueSpan` 讨论提案**：
  - 字段为 `span_id`、`source_revision`、`target`、`start`、`end`、`text`、`source`、`issue_type`、`severity`、`message`。
  - 采用 Python 切片语义，`start` 含、`end` 不含；`start`／`end` 必须为非布尔整数并具有完整有效边界。`target` 标识解析所得的实际目标文本；`candidate:<index>` 的索引须校验类型和范围，编辑后原锚点失效。
  - 优先定位 LaTeX 预览；原图 `image_region` 必须提供真实坐标并校验原图边界。
- **局部修正讨论提案**：
  - 由用户驱动，形成独立、带版本的编辑结果；只改 `final_latex`，不改候选、`raw_latex` 或当前 `refine`。
  - 三方 `revision` 必须一致；按 `span_id` 取得签发片段并核对 `target`／`start`／`end`／`text`，完成 `expected_text` 切片校验后只执行一次精确替换。
  - 无操作或拒绝不推进版本；仅实际修改才新增 `local_span_replacement` 记录，并保留历史 `changes`。
- **待定事项**：辅助接口还是 `issues` 字段承载、`severity` 映射、图片坐标方案、`revision` 管理、修正后是否重选及最小测试范围。
- **外部资源与 API**：本次仅追加日志，未使用外部资源、未调用 API。
- **审核意见及处理**：首轮发现 6 项问题，第二轮发现 2 项文档歧义，均已修正；最终无必须修复项。
- **实际测试与 Git 检查**：所述阶段未重跑单元测试；`git diff --check` 通过，仅有换行警告；未创建 Git 提交。本次日志追加未重跑测试。
- **未解决／未实现事项**：错误定位、圈选、局部重写及上述待定事项均未实现；文档与审核完成不等于 A/B/C 已冻结契约。
- **学习进度**：已明确片段签发、切片校验、版本一致性和单次精确替换需作为完整提案讨论，不能写成现有能力。
- **下一步（计划，未完成）**：仅计划与 A/B 讨论并冻结后再实现；当前不得宣称已支持错误定位、圈选或局部重写。

## C 模块真实样本：样本 7–9 OCR 冲突与回退评估

**阶段状态：样本 7–9 用户确认、3 次真实请求、回退评估、离线检查及结果保存已完成；样本 7 尚未自动修正，下一步仅为计划。**

- **本次任务**：评估样本 7–9 的真实 OCR 冲突、上下文选择与失败回退；本次仅追加日志，不修改其他文件、不调用 API。
- **用户纠正与负责人决定**：用户纠正“样本7你漏了个分子4，剩下没问题”。样本 7 真值为 `y^{(n)}=\frac{4(-1)^{n}\cdot n!}{(x-1)^{n+1}}`，样本 8 为 `y^{\prime\prime}=2\cdot\sin(2x+\frac{\pi}{2})`，样本 9 为 `=1+x+\frac{1}{2}x^{2}+o(x^{3})`，均为 `confirmed_correct`。本阶段无新增公共接口或重要技术选择决定。
- **真实 OCR 与 baseline 口径**：三条真实 OCR 原始候选分别为 `y^{(n)}=\frac{(x-1)^{n}\cdot n!}{(x-1)^{n+1}}`、`y^{\prime}=...`、`0(x^3)`，均不正确，真实 OCR 为 `0/3`；benchmark candidate0 baseline 为 `1/3`，两者必须区分，不能混报。
- **评估阶段实际创建文件**：新建 `D:\latex\artifacts\context_conflict_samples_7_9.json`；真实评估输出 `D:\latex\artifacts\context_benchmark_samples_7_9.json`，`status=complete`。本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`，无生产代码改动。
- **真实请求与回退结果**：上述评估使用 `deepseek-flash` 执行 3 次真实请求。样本 7 为 `selected_index=null`、`error=KeyError: context selection failed`、latency `8954.553ms`，保留错误 OCR，结果为 `low + need_review=True`；样本 8/9 均选择正确，latency 分别为 `1185.551ms`、`3180.015ms`。
- **评估指标**：final exact `2/3`；成功响应选择 `2/2`；fallback `1/3`；intercepted error `1/1`；missed `0`；renderable `3/3`；review `1/3`。context latency median `3180.015ms`；`n=3` 时 nearest-rank p95 即最大值 `8954.553ms`。
- **结果边界**：样本 7 尚未自动修正，不能宣称总体稳定；可渲染不等于正确，本组结果也不能外推总体准确率或稳定性。
- **外部资源**：上述评估实际使用用户配置的 `deepseek-flash` 服务和本地 KaTeX；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，未提供新增代码审核意见。
- **实际测试与检查**：完整 `unittest` 100 项全部通过（6.933s）。首次校验脚本因前缀断言写法失败，改为完整真值一致性校验后通过；这是校验脚本修正，不是评估失败。`git diff --check` 通过。本次日志追加未重新运行测试或检查。
- **Git 状态**：评估结果未提交，未创建 Git 提交。
- **未解决事项**：样本 7 的上下文选择失败和错误 OCR 保留问题尚未解决；不能将 `low + need_review=True` 的错误拦截写成公式已修复。
- **学习进度**：已再次明确真实 OCR 正确率、benchmark candidate0 baseline、成功响应选择准确率及失败回退是不同口径；错误被拦截不等于错误被纠正。
- **下一步（计划，未完成）**：仅计划对样本 7 单独重复诊断响应格式和服务波动，不写成已修复；本次日志记录未调用 API。

## C 模块样本 7：上下文 KeyError 诊断

**阶段状态：1 次新诊断请求及结果保存已完成；样本 7 尚未修复，不继续重复大量请求。**

- **本次任务**：诊断用户询问的样本 7 上下文失败原因；本次仅追加日志，不修改其他文件、不调用 API。
- **原始 artifact 证据**：仅记录 `KeyError`。`choose_with_context` 需要 `response['selected_index']` 和 `response['reason']`，因此可确定原始解析后的 dict 至少缺少一个必需字段；不能确定具体缺少哪个字段，原始 raw response 未保存。
- **证据边界**：`KeyError` 不是越界 `ValueError`；没有证据证明发生 HTTP 失败。
- **新诊断结果**：使用同图、同候选执行 1 次新的诊断请求，latency 为 `3227.349ms`；返回 keys 为 `['reason','selected_index']`，`selected_index` 类型为 `int`、`reason` 类型为 `str`，结构合法。但选择索引 0（期望 1），理由错误声称图中为 `(x-1)^n` 而非 `4(-1)^n`，仍未纠正。
- **诊断阶段实际保存文件**：`D:\latex\artifacts\context_sample_7_diagnostic.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`，无生产代码改动。
- **结论**：原始缺字段是暂时性格式问题；新响应显示服务／模型输出有波动且可能错选。不宣称样本 7 已修复，不重复大量请求。
- **外部资源**：上述新诊断实际使用现有上下文服务／模型；本次日志追加未调用 API，无其他新增外部资源。
- **审核与测试**：无生产代码改动，未提供新增代码审核意见，未重跑测试。
- **未解决事项**：原始具体缺失字段无法恢复确认；样本 7 的错选和输出波动仍未解决。
- **学习进度**：响应结构合法不代表选择正确；一次新响应可用于区分暂时性格式问题与持续错选，但不能证明稳定性。
- **下一步（计划，未完成）**：不继续重复大量请求；由负责人确认后续处理。

## C 模块真实样本：样本 8–9 响应波动检查

**阶段状态：样本 8/9 各 3 轮真实请求、汇总及离线检查已完成；样本 9 的选择波动和真实漏报仍未解决，下一步仅为计划。**

- **本次任务**：用户要求检查其他样本是否有类似波动。样本 4–6 已有 `9/9` 一致结果，样本 3 已有不稳定结果，均不重复请求；本次仅追加日志，不修改其他文件、不调用 API。
- **负责人决定**：本阶段未提供需新增记录的公共接口或重要技术选择决定。
- **评估阶段实际创建文件**：以 `D:\latex\artifacts\context_conflict_samples_8_9.json` 为输入，分别保存 `D:\latex\artifacts\context_stability_samples_8_9_run_1.json`、`D:\latex\artifacts\context_stability_samples_8_9_run_2.json`、`D:\latex\artifacts\context_stability_samples_8_9_run_3.json`，汇总保存至 `D:\latex\artifacts\context_stability_samples_8_9.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`，无生产代码改动。
- **真实重复检查**：对样本 8/9 使用 `deepseek-flash` 各执行 3 次真实请求，共 6 次。样本 8 索引为 `[0,0,0]`，`3/3` 正确且本组稳定，latency median `1650.462ms`；样本 9 索引为 `[1,0,1]`，`2/3` 正确，run 2 错选候选 0（`0(x^3)`），理由声称图中是 `0`，另外两次均选择 `o`。
- **完整性与总体结果**：全部 6 次均无缺字段、无 fallback，renderable `6/6`；总体 final exact `5/6`，`missed_error=1`，review `0`。总体 latency median `2071.0715ms`、min `1549.716ms`、max `8310.862ms`。
- **真实漏报与结论**：样本 9 run 2 的 final 错误且 `need_review=False`，是真实漏报；结构正常或可渲染不能阻止模型错选。类似选择波动确实存在于样本 9，样本 8 本组稳定；不能以部分样本稳定推断全部稳定。
- **外部资源**：上述评估实际使用了用户配置的 `deepseek-flash` 服务和本地 KaTeX；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，未提供新增代码审核意见。
- **实际测试与检查**：未重跑单元测试；已解析三轮报告和汇总并断言；`git diff --check` 通过，仅有换行警告。评估结果未提交，未创建 Git 提交。
- **未解决事项**：样本 9 的选择波动及漏报尚未解决；样本数量和重复轮次有限，不能据此形成总体稳定性结论。
- **学习进度**：响应字段完整、结构正常和可渲染均不等于选择正确；重复真实请求能够揭示单轮正确结果未暴露的波动与漏报。
- **下一步（计划，未完成）**：仅计划由负责人决定是否讨论更保守的复核策略或更多重复评估，不擅自修改公共规则；本次日志记录未调用 API。

## C 模块契约 v0.3：样本 9 漏报检测设计

**阶段状态：`CONTRACT.md` v0.3 设计文档整理、审核及修正已完成；第 16 节为未实现设计，当前 `refine` 不变，下一步仅为计划。**

- **本次任务**：按用户要求将样本 9 漏报检测方案写入 `D:\latex\reasoning\CONTRACT.md`；本次仅追加日志，不修改其他文件、不调用 API。
- **负责人确认的文档范围（非契约冻结决定）**：`CONTRACT.md` 升级为 `v0.3`；第 16 节明确标记为未实现设计，不改变当前 `refine`。
- **实际修改文件**：所述文档阶段修改 `D:\latex\reasoning\CONTRACT.md`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。无生产代码改动。
- **漏报证据**：样本 9 三次真实请求的选择索引为 `[1,0,1]`；run 2 错选候选 0（`0(x^3)`），且 `need_review=false`，构成真实漏报。
- **本地规则设计**：
  - 枚举全部无序候选对，仅对原始 `latex` 等长的候选逐位置比较；任一独立 `0`／`o` 差异位置触发 `ambiguous_glyph_conflict`，存在其他混合差异时不跳过该检查。
  - 不同长度候选不进入本规则，但不据此宣称无风险；本设计不处理其他字符对，也不宣称覆盖全部视觉混淆。
  - 每个相关候选分别生成 `IssueSpan`；不同候选的数值 `start`／`end` 可以相同，但 `target` 必须分别锚定对应候选。
- **触发后的行为设计**：保留原选择，结果为 `low + need_review=True`；不自动改选，不新增 `changes`；该复核要求优先于上下文成功后的免复核路径。
- **可选二次验证设计**：仅允许回答 `0`／`o`／`unknown`，不得覆盖本地规则的复核结论。
- **验收设计**：包括离线规则测试、样本 9 三次已保存响应回放全部要求复核，以及漏报、复核、正确结果复核和延迟指标；验收项目尚未执行。
- **外部资源与 API**：本次仅追加日志，未使用外部资源、未调用 API。
- **审核意见及处理**：首轮发现跨候选索引锚点和差异算法存在歧义，已改为明确逐候选锚点及等长原始 `latex` 逐位置规则；最终复核无必须修复项。
- **实际测试与 Git 检查**：所述阶段未重跑单元测试；`git diff --check` 通过，仅有换行警告；未创建 Git 提交。本次日志追加未重跑测试或检查。
- **未解决／未实现事项**：本地漏报检测、`IssueSpan` 生成、可选二次验证及上述验收均未实现；文档与审核完成不等于 A/B/C 已冻结契约，也不得宣称当前已支持该检测。
- **学习进度**：已明确不同长度未命中规则不等于无风险；相同字符偏移必须结合各自 `target` 解释，安全复核不能因上下文选择成功而被省略。
- **下一步（计划，未完成）**：仅计划在 A/B/C 三人冻结后实现本地规则并回放样本 9 三次响应，不写成已支持。

## C 模块样本 9：0/o 漏报检测实现与回放验收

**阶段状态：v0.3 最小范围实现、测试、审核、契约同步及无 API 回放验收已完成；其他字符对、不同长度对齐、二次验证和下一步均未实施。**

- **本次任务**：用户明确“实现样本9的漏报检测逻辑”；按 `CONTRACT.md` v0.3 最小范围实现样本 9 的本地 `0`／`o` 漏报检测并回放验收，不扩展未证实范围。
- **负责人决定**：确认上述实现任务及 v0.3 最小范围；保留原候选选择、`final` 和 `changes`，公共返回字段不变。
- **实际创建／修改文件**：修改 `D:\latex\reasoning\validators.py`、`D:\latex\reasoner.py`、`D:\latex\tests\test_validators.py`、`D:\latex\tests\test_reasoner.py`、`D:\latex\tests\test_context_benchmark.py`、`D:\latex\reasoning\CONTRACT.md`；新建 `D:\latex\artifacts\context_sample_9_ambiguity_replay.json`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **实现结果**：
  - `validators.py` 新增 `find_ambiguous_glyph_conflicts` 和 `_make_glyph_span`；枚举全部无序候选对，仅对原始 `latex` 等长的候选逐位置检测 `0`／`o` 差异；存在其他混合差异时仍独立触发该检查，不同长度候选跳过，并校验非法输入。
  - 每条证据包含唯一 `span_id`、`source_revision=0`、`target`、`start`、`end`、`text`、`source`、`severity`、`message`。首轮审核发现三候选场景的 `span_id` 重复后，已将本候选、对端候选和位置纳入 ID。
  - `reasoner.py` 在任一规则命中时设置 `low + need_review=True`；不自动改选，保留原选择、`final` 和 `changes`，公共返回字段不变。
- **测试补充**：`test_validators.py` 覆盖双向、混合差异、重复差异、不同长度、空候选、单候选、非法输入及三候选 ID 唯一；`test_reasoner.py` 验证命中后选中结果不变；`test_context_benchmark.py` 回放样本 9 三次已保存响应，验证均为 `low + need_review=True` 且 `final`／`changes` 不变。
- **代码审核及处理**：首轮审核发现三候选 `span_id` 重复，已按上述方式修复并补测试；最终复核无必须修复项，审核员复跑 108 项全部通过（3.572s）。
- **实际测试**：首轮完整 `unittest` 106 项全部通过（4.904s）；修复及补测后最终完整 `unittest` 108 项全部通过（3.889s）；审核员复核 108 项全部通过（3.572s）。
- **无 API 回放结果**：结果保存至 `D:\latex\artifacts\context_sample_9_ambiguity_replay.json`；previous review `0/3`、new review `3/3`、previous missed `1`、new missed `0`，三次响应的 `final`／`changes` 全部不变，`additional_api_calls=0`。该结果只证明本组回放的复核漏报改善，不证明模型选择准确率提高。
- **契约同步**：`D:\latex\reasoning\CONTRACT.md` 已同步标记本地 `0`／`o` 检测实现、108 项测试及上述回放结果。
- **外部资源与 API**：复用样本 9 三次已保存响应进行本地回放；无新增外部资源，未调用新的真实 API，本次日志追加亦未调用 API。
- **Git 状态**：未创建 Git 提交。
- **未解决／未实现事项**：其他字符对、不同长度对齐和可选二次验证均未实现；不同长度跳过不等于无风险，当前结果不外推为总体检测能力或选择准确率。
- **学习进度**：本地歧义证据可在不改选、不改写公式的前提下补充安全复核；回放漏报减少与模型选择准确率提升是不同结论。
- **下一步（计划，未完成）**：仅计划使用更多真实 `0`／`o` 样本验证，不扩展未证实范围。

## C 模块真实样本：样本 10–12 评估与测试耗时分析

**阶段状态：样本确认、3 次真实请求、本地 KaTeX 检查、结果保存及离线回归已完成；首次流程确实偏慢，调度优化与缓存仅为下一步计划。**

- **本次任务**：使用已保存的 OCR 候选评估样本 10–12，不重跑 OCR；执行 3 次真实 `deepseek-flash` 请求并分析首次完整流程耗时。本次仅追加日志，不修改其他文件、不调用 API。
- **用户纠正与负责人决定**：用户纠正“10少了个负号，其他都是对的”。样本 10 真值为 `y^{\prime\prime\prime}=\frac{-24}{(x-1)^4}`；样本 11/12 按建议确认，三条均为 `confirmed_correct`。本阶段无新增公共接口或重要技术选择决定。
- **真实 OCR 与 baseline 口径**：三条真实 OCR 均不正确，真实 OCR 为 `0/3`；benchmark candidate0 baseline 为 `1/3`，两者必须区分，不能混报。
- **评估阶段实际输出文件**：`D:\latex\artifacts\context_benchmark_samples_10_12.json`，`status=complete`；本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`，无生产代码改动。
- **真实评估结果**：使用保存的 OCR 候选和 `deepseek-flash` 执行 3 次真实请求；样本 10/11/12 全部选择正确，final exact `3/3`，renderable `3/3`，fallback `0`，review `0`。结果仅限本组 3 个样本的单轮评估，不能外推总体准确率或稳定性。
- **真实请求与首次流程耗时**：context latencies 分别为 `2186.086ms`、`2029.322ms`、`3082.662ms`，median `2186.086ms`；`n=3` 时 nearest-rank p95 即最大值 `3082.662ms`。3 次请求加本地 KaTeX 的总 wall 为 `7.951s`；此前 OCR latencies 分别为 `22684.214ms`、`13928.959ms`、`14783.762ms`，合计 `51.397s`，首次完整流程约 `59.348s`。
- **速度结论**：针对用户“速度是否太慢”的询问，结论是首次真实评估确实偏慢，主要耗时在 OCR 和串行 API。后续优先复用 OCR／context 响应并进行离线回放，新样本只做必要真实请求；并行请求和缓存策略均未实施。
- **外部资源**：上述评估实际使用用户配置的 `deepseek-flash` 服务和本地 KaTeX；本次日志追加未调用 API、未读取 `.env`，无其他新增外部资源。
- **代码审核及处理**：无生产代码改动，未提供新增代码审核意见。
- **实际测试与检查**：完整 `unittest` 108 项全部通过（`7.590s`），说明离线回归远快于首次真实流程。已解析确认文件和结果文件；`git diff --check` 无输出。本次日志追加未重新运行测试或检查。
- **Git 状态**：评估结果未提交，未创建 Git 提交。
- **未解决事项**：首次流程的 OCR 与串行 API 耗时问题尚未优化；并行请求和按需缓存未实施，本组结果不足以评价总体稳定性。
- **学习进度**：OCR、真实 context 请求、本地 KaTeX 和离线回归耗时需分别报告；小样本 p95 可能只是最大值，复用已保存响应可避免不必要的重复真实请求。
- **下一步（计划，未完成）**：仅计划优化评估调度并按需缓存，不写成已优化；本次日志记录未调用 API。

## B/C 集成：识别接口、共享契约与联合验证

**阶段状态：C 结果已提交为 `4800645`；B/C 接入、审核修复与联合验证已完成；集成改动尚未提交，第二引擎和真实速度优化未实施。**

- **本次任务与负责人决定**：用户明确在当前任务完成后整合 B 和 C，先将 C 结果提交为 `4800645`，再接入同学 `Downloads` 中的 `recognizer.py`、`schemas.py`、`test_recognizer.py`、`README_B.md`，并新增 `samples/sample_plus.png`。
- **实际接入／修改文件**：上述 B 侧文件及样本已接入；审核修复涉及识别 Mock、C 的 `refine`、B 的去重与日志键及相关测试，`README_B.md` 已补充集成边界。本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`，未修改其他文件。
- **识别接口与共享契约**：
  - `recognize(image_path, *, thorough=False)` 保持向后兼容；`Candidate` 五字段、`RefineResult` 六字段保持一致。
  - B 不 `strip` 原始结果，C 仅 `trim` 首尾空白，二者兼容。
  - 默认模型目录为 `models/PP-FormulaNet-L`，新增 `RECOGNIZER_MODEL_DIR` 配置；模型缓存键包含 `engine`、`model_name`、`model_dir`、`device`。
- **首轮审核及必须项处理**：
  - 发现 Mock 被当作真实成功，已改为 Mock 使用 `make_error`，经 `refine` 返回 `low + need_review=True`；成功链路改用显式 fake，不再冒充真实识别。
  - 发现 B 仅按 `latex` 去重会丢失跨引擎证据，已改为按 `(engine, strip(latex))` 去重并同步日志键；新增跨引擎同式 `high`、同引擎多视角 `medium`、`trim` 和 Mock 失败测试。
  - 最终复核无必须修复问题。
- **测试环境与实际结果**：B 自测初遇 GBK 对勾编码问题，状态输出改为 ASCII 后全部 `PASS`。完整 `unittest` 初版 111 项通过；后续一次测试环境清空 `HOME` 导致 1 个 `ERROR`，修正环境后消除。非 `--real` 自测强制使用 Mock，集成测试使用绝对路径并 patch 配置和 `device`。最终完整 `unittest` 115 项全部通过（14.291s）；审核员 B/C 集成测试 7/7 通过，完整 115 项全部通过（12.747s）。本次日志追加未重新运行测试。
- **真实本地模型联合验证**：真实本地模型完成 B→C 的 `sample4` 识别，结果正确，wall 为 39.262s，`confidence=medium`、`need_review=false`；该单样本结果不外推为总体准确率或速度结论。
- **文档补充**：`README_B.md` 已明确 Mock 只能用于失败回退验证；B 支持 PDF/BMP/TIFF，但这些输入需转换后才可供 C 进行上下文选择。
- **实际使用的外部资源**：同学 `Downloads` 中上述文件及本地 `models/PP-FormulaNet-L` 模型；本次日志追加未调用 API 或真实模型。
- **学习进度**：已明确 Mock 失败回退与显式 fake 成功链路必须区分；跨引擎一致证据不能在 B 侧按纯 `latex` 提前去重；真实单样本成功不等于已完成性能优化。
- **未解决／未实施事项**：集成改动未提交；未实现第二引擎；真实识别速度优化未做。
- **下一步（计划，未完成）**：仅计划由负责人确认后提交集成改动或继续联调，不写成已提交。

## 大赛工作台：整页识别、中文编译、浏览器修复闭环与验收

**阶段状态：整页 `.tex`、中文 PDF、浏览器编辑与修复闭环及完整回归已完成；识别准确率、跨页合并和更多整页真值验证仍未完成。**

- **本次任务**：实现大赛要求的本地 Web 竖切：整页手写图片 → 可编辑 LaTeX → Tectonic 中文 PDF → 编译标行 → AI 建议 → 用户确认修复 → 预览与下载。
- **实际创建／修改文件**：新增 `workbench/`、`tests/test_workbench.py`、`tests/test_workbench_app.py`、`samples/sample_plus.png` 和 `artifacts/full_page_browser_acceptance.json`；修改 `.gitignore`、`package.json`、`package-lock.json` 及本次日志。
- **编译环境**：官方 Tectonic `0.17.0` 安装至 `tools/tectonic`，ctex 中文最小文档和真实整页文档均编译成功。GitHub 直连曾重置，检查官方 PowerShell 安装脚本后安装成功。整页首次 30 秒超时后，新增独立 `FULLPAGE_TIMEOUT_SECONDS`（默认 120 秒）。
- **真实浏览器验证**：实际上传 `data/pdf_pages/page_2.png`，生成可编辑 `.tex`、预览并下载 PDF；注入 `\badmacro` 后定位到源码第 74 行，AI 建议仅删除该命令，用户确认后重新编译并恢复 PDF。
- **原文与安全**：上传保存 `original.tex`，编辑写入 `history`，修复先写 `fix_applied.json` 再编译；修复前 `baseline_sha256` 与 `fix.before` 一致。每轮编译清理旧 PDF，过期建议被拒绝，编辑使旧错误失效，异常响应携带当前源码供页面同步。
- **资源边界**：上传图片限制 20 MB，tex／编译日志限制 200k 字符，模型请求 `max_tokens=16000`，JSON 根节点必须为对象；运行时 jobs 和 Tectonic 工具目录已加入 `.gitignore`。
- **实际测试**：工作台编译与端点测试、完整联合回归 `128` 项全部通过（`6.474s`）；最终代码审核无必须修复项。
- **验收证据**：`artifacts/full_page_browser_acceptance.json` 保存真实 job、错误行号、AI 摘要、历史数量、修复基线及 PDF 签名。流程成功不等于识别准确率或模型稳定性，生成标题、段落和公式仍需人工核对。
- **未解决／未实施事项**：跨页合并、3–5 张整页真值集、真实示意图重建、生产部署和 MLP 生产化均未实施；本批改动尚未提交。
- **下一步（计划，未完成）**：由负责人确认后提交本批实现，补充整页真值与更多典型手写页面进行验收。

## 大赛工作台：跨页合并真实浏览器验收与完整回归

**阶段状态：双页跨页合并的真实浏览器验收、证据修正与完整回归已完成；整页模型稳定性及后续事项仍未完成。**

- **本次任务**：记录整页提示调整后的双页上传验收、分页证据复核及联合回归；本次仅追加 `D:\latex\reasoning\TEAM_LOG.md`，不再调用真实 API，不提交 Git。
- **实际修改／生成文件**：整页提示修改涉及 `D:\latex\workbench\full_page.py`；验收汇总修正涉及 `D:\latex\artifacts\batch_browser_acceptance.json`；真实验收生成或更新 `D:\latex\artifacts\batch_browser_success.png`、`D:\latex\artifacts\jobs\a5873937fd954c75a0f959fbcc4e45b1\main.tex` 和同目录 `main.pdf`。
- **提示调整与重试**：`workbench/full_page.py` 的整页系统提示开头已改为 `Return the JSON object directly and keep analysis brief.`。此前真实双页浏览器上传曾因空响应／截断返回 502；本轮使用该提示重试一次成功，但单次成功不能证明模型输出已稳定。
- **2026-11-15 真实浏览器验收**：使用本地 Playwright 在 `http://127.0.0.1:8000` 依次上传 `data/pdf_pages/page_2.png` 与 `page_3.png`，只发起一次 `POST /api/documents/batch`，HTTP 200，`job_id=a5873937fd954c75a0f959fbcc4e45b1`。接口返回 `page_count=2`、`compile_success=true`；页面显示两个缩略图、标签“第 1 页／第 2 页”和“共 2 页”。iframe PDF 预览请求成功；下载 GET 返回 200，文件签名为 `%PDF-`，大小 30409 字节；无浏览器 console error。
- **分页证据复核**：上述成功 job 的实际 `main.tex` 第 90 行为 `\newpage`。首次 Playwright 汇总误报 `has_newpage=false`，原因是验收 Node 脚本反斜杠转义错误，不是产品分页缺失；改为核对实际 `main.tex` 后，`artifacts/batch_browser_acceptance.json` 已修正为 `has_newpage=true`、`newpage_line=90`。
- **证据与截图边界**：证据为 `D:\latex\artifacts\batch_browser_acceptance.json`、`D:\latex\artifacts\batch_browser_success.png` 及上述 job 的 `main.tex`／`main.pdf`。无头 Chromium 截图中的 PDF iframe 视觉区域可能空白，因此仅声称 iframe 请求与 PDF 下载验证成功，不声称截图已展示 PDF 内容。
- **实际使用资源**：上述验收使用本地 Playwright／无头 Chromium 和本地工作台服务；本次日志追加未调用真实 API，无其他新增外部资源。
- **审核意见及处理**：本阶段未提供新增代码审核意见；验收脚本误报已通过实际 job 源码复核并修正汇总，不作为产品分页缺陷记录。
- **实际测试**：
  - `./.venv/Scripts/python.exe -m unittest discover -s tests`：130 tests，11.595s，`OK`。日志中的 `fix compilation failed`／`RuntimeError: boom` 是故障注入测试的预期输出，不是失败。
  - `./.venv/Scripts/python.exe test_recognizer.py`：非 `--real` 的 B 自测全部 `PASS`，真实模型项 `SKIP`；Windows 控制台中文仍有乱码，不影响退出和测试判定。
  - 本次日志追加未重新运行上述测试。
- **Git 状态**：本轮没有提交 Git；本次未检查 Git 当前状态，不新增集成与工作台改动提交状态断言。
- **未解决／未实施事项**：更多真实多页样本、跨页语义一致性、整页模型稳定性统计、真实示意图重建、生产部署和性能优化均未完成。
- **学习进度**：验收脚本自身的转义错误可能造成误报，须以实际产物复核；iframe 请求和 PDF 下载成功不等于截图已完成 PDF 视觉验证，故障注入的预期日志也不等于回归失败。
- **下一步（计划，未完成）**：由负责人确认后扩展真实多页样本，检查跨页语义并统计整页模型稳定性；其余未实施事项不写成已完成。

## 多页样本评估扩充、402 阻塞与空白页修复

**阶段状态：评估工具、首次真实请求失败证据、离线复跑、空白页修复、审核及本地测试已完成；新的真实多页识别成功结果和三组真实合并／PDF 验收均未完成。**

- **本次任务**：用户要求“扩充真实多页样本测试”。本轮建立多页评估样本与可恢复评估工具，并处理审核发现的空白页成功路径缺失；不把工具或离线验证完成写成真实扩充识别完成。
- **样本与评估口径**：新增 `D:\latex\data\multipage_samples.json`，选择连续 `page_2/page_3/page_4`、逆序 `page_4/page_2`、`page_4/空白 page_5` 三组；`page_1` 为无笔记封面，本轮排除。指标仅为识别完成、人工可见章节标记落在预期分页、`\newpage` 数、Tectonic 编译、PDF 页数／尾页空白；没有整页逐字真值，不计算转录准确率。
- **实际新增／修改文件**：新增 `D:\latex\workbench\multipage_eval.py`、`D:\latex\tests\test_multipage_eval.py` 及上述 manifest；修改 `D:\latex\workbench\full_page.py`；生成或更新 `D:\latex\artifacts\multipage_real\report_initial_real.json` 和 `D:\latex\artifacts\multipage_real\report.json`。本次记录仅追加 `D:\latex\reasoning\TEAM_LOG.md`。
- **已完成的评估工具**：按逐页源文件 SHA256 缓存，采用原子 JSON 写入，支持 `pending/request_error/invalid_document/success`、跨用例复用、`--offline` 和 `--retry-failed`；缓存 raw 响应／错误，并记录合并 `document/main.tex`、编译及 PDF 结构结果。
- **首次真实运行结果**：四个唯一页面各请求一次，共 4 次，模型为 `deepseek-flash`；全部在约 0.4–0.7 秒快速返回 `APIStatusError 402 Insufficient Balance`。三组均为 `page_recognition_failed`，未进入合并／编译，没有产生新 PDF，不能据此断言产品分页失败。原始证据保存在 `D:\latex\artifacts\multipage_real\report_initial_real.json`。
- **同缓存离线复跑**：随后使用 `--offline`，新增 API 调用为 0，`cache_hits=7`、`successful_cache_hits=0`、`failed_cache_hits=7`。当前 `D:\latex\artifacts\multipage_real\report.json` 是 `execution_mode=offline` 的离线报告；错误缓存命中不等于真实识别成功。
- **审核意见及空白页修复**：首轮只读审核发现 1 个必须项：`expected_blank` 的忠实空 `blocks` 会触发 `invalid_document`，填入非空内容又构成编造，空白用例没有可成功路径。现已在 `workbench/full_page.py` 支持显式 `{"type":"blank_page"}` 转为 `\null`，并调整提示为仅真正空白页返回单个 `blank_page`；评估器对人工真值 `expected_blank` 且原始 `blocks=[]` 保留 `raw_document`，同时将规范化 `document` 设为 `blank_page`。带正文、公式或图描述的空白页仍失败。报告新增 `execution_mode`、`retry_failed`、successful／failed cache hits。
- **PDF 尾页判定与复核**：尾页必须无正文、图片和绘图，只允许自动数字页码。修复过程中真实 Tectonic 测试初次失败，原因是第二页自动带页码“2”；随后明确页码不是正文并调整判定，这不是掩盖识别错误。复核员确认原必须项已解决，无剩余必须修复项。
- **实际测试**：新增评估器 3 项通过；workbench 9 项通过，其中包括真实 Tectonic 编译内容页加 `blank_page` 后得到 2 页 PDF，尾页只有自动页码“2”且无图片／绘图。最终 `./.venv/Scripts/python.exe -m unittest discover -s tests` 为 `134 tests`、`8.967s`、`OK`；故障注入 `RuntimeError: boom` 日志不是测试失败。没有重新运行 B 的 `--real`，没有新的真实模型识别成功结果。本次日志追加未重新运行测试。
- **实际使用的外部资源**：上述阶段首次真实运行使用了 `deepseek-flash` 服务，空白页验证使用了本地真实 Tectonic；离线复跑和本次日志追加未调用真实 API，无其他新增外部资源。
- **Git 状态**：本轮未提交 Git。
- **未解决／未完成事项**：第 2 至 5 页的新真实识别、三组真实合并／PDF 验收、真实空白页模型响应、整页转录真值与准确率、跨页语义一致性均未完成。
- **学习进度**：已明确真实请求失败、失败缓存离线命中、工具测试通过和真实识别成功是不同证据；自动页码与正文需区分，空白页忠实空结果也必须有合法成功路径。
- **下一步（计划，未完成）**：余额恢复后计划执行 `./.venv/Scripts/python.exe -m workbench.multipage_eval --manifest data/multipage_samples.json --output artifacts/multipage_real --retry-failed`；尚未通过该命令取得成功的真实复跑，不写成已完成。

## 余额恢复后的真实多页识别：三组结构用例全部通过

**阶段状态：4 张真实手写页的多页识别与三组真实合并／PDF 结构验收已完成；整页转录准确率、跨页语义一致性与模型稳定性统计仍未完成。**

- **本次任务**：用户充值后要求恢复被 402 阻塞的真实多页评估（`--retry-failed`），并回归记录结论。本轮除真实请求外，只修改 `D:\latex\README.md` 并追加本日志，未修改 C 模块公共契约与其他人的模块。
- **API 冒烟**：先用一次极小的真实请求确认计费恢复，`api.deepseek.com/v1` 的 `deepseek-flash` 正常返回（43 tokens，约 1.07 秒），不再出现 402。该请求 `max_tokens=8` 全部消耗为 `reasoning_tokens`、`content` 为空，是冒烟参数过小，不是产品请求问题。
- **第一轮真实运行**：`--retry-failed` 对 4 张唯一页面各请求 1 次，共 4 次调用。`page_2` 成功（52389.941ms，20 块）、`page_4` 成功（28766.162ms，9 块）、`page_5` 成功（787.772ms，仅 1 个 `blank_page`，没有编造内容）；`page_3` 失败，102441.914ms 后 `ValueError: full-page response content is empty (finish_reason=length)`。该轮 `cases_structurally_passed=2/3`，`contiguous_2_3_4` 为 `page_recognition_failed`，失败点在单页请求而非合并逻辑。
- **第二轮重试**：临时设置 `FULLPAGE_MAX_TOKENS=40000`、`FULLPAGE_TIMEOUT_SECONDS=300`（仅环境变量，未改代码）再次 `--retry-failed`，只重发失败的 `page_3`（1 次新调用），其余页面复用缓存；该轮 `cache_hits=6`、`successful_cache_hits=6`、`failed_cache_hits=0`。`page_3` 成功，79399.054ms，16 个块。最终 `report.json` 为 `execution_mode=real_api_and_cache`、`retry_failed=true`、`cases_structurally_passed=3/3`，时间 2026-11-17T09:40:57Z–09:42:25Z（UTC）。
- **三组真实 PDF 证据**：`contiguous_2_3_4` 分页符 2/2，三处人工章节标记均落在预期页段，编译成功，PDF 4 页、33920 字节；`reverse_4_2` 分页符 1/1，两处标记顺序与上传顺序一致，PDF 3 页、29346 字节；`trailing_blank_4_5` 分页符 1/1，`trailing_blank_pdf_is_blank=true`，PDF 2 页、21143 字节。三份 PDF 均真实存在于 `artifacts/multipage_real/<case>/main.pdf`。`contiguous_2_3_4` 与 `reverse_4_2` 的 PDF 页数多于源页数，属于识别内容溢出到下一页，报告按既定口径记录为允许而非失败。
- **实际测试**：`./.venv/Scripts/python.exe -m unittest discover -s tests` 为 `Ran 134 tests in 21.408s`、`OK`；日志中的 `fix compilation failed` 与 `RuntimeError: boom` 是故障注入用例的预期输出。本轮未运行 B 的 `--real`，未新增单页真值评估。
- **实际使用的外部资源**：两轮共 5 次真实 `deepseek-flash` 请求（4 次首轮＋1 次重试），另有 1 次冒烟请求；PDF 均由本地 Tectonic 编译。控制台中文乱码仅为终端编码问题，缓存 JSON 为 UTF-8。
- **证据边界**：本轮只证明结构链路（识别完成、上传顺序、分页、编译、页数、忠实空白页），`transcription_accuracy` 仍为 `not_evaluated_without_full_page_truth`；`page_3` 是先失败再重试成功，不能据此声称模型输出稳定，也没有多次重复运行统计。
- **Git 状态**：本批真实评估产物与 README、日志更新在追加时尚未提交；上一轮一键启动相关提交 `b269cf5` 已推送到 `hand2latex-review` 并经 `git ls-remote` 核对。
- **未解决／未完成事项**：整页转录真值集与准确率、跨页语义一致性、多轮模型稳定性统计、真实示意图重建、部署与性能优化仍未完成。
- **学习进度**：`deepseek-flash` 的 `max_tokens` 包含推理 token，预算不足会出现"耗时很长但 `content` 为空、`finish_reason=length`"的假性失败；处理方式是提高 `FULLPAGE_MAX_TOKENS` 后只重试失败页，而不是重写合并逻辑。评估报告里的"新发请求数／缓存命中数"需按用例区分，不能混读成单页调用次数。
- **下一步（计划，未完成）**：由负责人决定是否提交并推送本批真实评估证据；随后补整页真值集与转录准确率口径，再评估跨页语义一致性。

## 2026-11-19 工作台人工复核标注与本机 GPU 识别实测

**阶段状态：UI 复核标注已完成并在浏览器验证；本机 GPU 上的 PP-FormulaNet-L 单张识别成功。未修改 C 模块代码与公共契约。**

- **本次任务**：用户要求（1）把"可能识别出错、需要人工复核"的位置标注出来；（2）用本机 GPU 跑一次识别。修改 `D:\latex\workbench\static\index.html`、`D:\latex\README.md`，追加本日志；未修改 C 模块、`schemas.py` 或 B 的识别逻辑。
- **复核标注口径**：只标三类可验证信号——编译器明确报告的缺字／无法表示字符（带 `main.tex:行号`）、中文里被转义成 `\$` 的行内公式、正文中裸写的数学符号；不显示置信度、不生成风险分数、不判断识别内容对错。左栏每页有"N 处待复核"和"标为已核对"；中栏黄色行可点击跳到对应行。
- **浏览器实测**：真实 job `3ee80c69…` 命中 6 行 `\$`（第 10/12/38/52/70/72 行），点击第 10 行能选中对应源码；把 `6bb554e9…` 的第 8 行以 fandol 编译（真实 Tectonic 日志），命中 1 处 `Missing character ... U+2208`，左右两处同字符警告已去重；多页 job `a5873937…` 两页均可勾选"已核对"，计数从 0/2 变为 1/2。截图保存在 `.venv/review_*.png`（未纳入 Git）。
- **本地识别现状（实测）**：默认 `.venv` 中先 `import paddle` 再 `import torch` 会报 `WinError 127 ... torch\lib\shm.dll`；先 import torch 再 import paddle 正常。demo 的真实识别路径当前会受此影响，本次未改动 A／B 文件来修复，只记录现象。
- **GPU 实测**：新建 `.venv/gpu-venv`，安装 `paddlepaddle-gpu 3.4.0`（官方 cu129 索引）、`paddleocr 3.7.0`、`tokenizers`、`ftfy`、`torch 2.15.0+cpu`。RTX 5070 Laptop（计算能力 12.0）被 Paddle 识别，`matmul` 落在 `Place(gpu:0)`。同一张 `samples/sample_plus.png`：CPU 首次 30.3 s、预热 11.7 s；GPU 首次 12.3 s、预热 0.62 s；两者输出同为 `x^{3}-x^{2}+x^{2}+x-x+3x-3+4`。识别期间 `nvidia-smi` 采样到 35–44% 利用率、约 355 MiB 显存。
- **环境坑**：`paddleocr 3.7.0` 的公式后处理还缺 `tokenizers` 与 `ftfy`，缺任何一个都只报笼统的 "A dependency error occurred during predictor creation"。
- **实际测试**：`./.venv/Scripts/python.exe -m unittest discover -s tests` 为 `Ran 147 tests in 21.494s`、`OK`。未新增真实整页识别请求，未调用付费 API。
- **证据边界**：GPU 数字来自单张样本单次运行，不构成性能基准；GPU 尚未接入画板演示（演示仍用 `.venv` + CPU 配置）；`样本真实识别` 与 `GPU 基础设施可用` 是两件事，这里只证明后者和单张推理可运行。
- **Git 状态**：本轮改动（index.html、README、本日志）尚未提交。
- **未解决／未完成事项**：画板演示切到 GPU venv（需补 streamlit 依赖并保证 torch 先于 paddle 导入）、整页真值集与转录准确率、真实示意图重建仍未完成。
- **学习进度**：paddle 与 torch 同时存在时，Windows DLL 搜索顺序会让后加载的一方失败；GPU 是否真的在算，要看 `Place(gpu:0)` 和 `nvidia-smi` 利用率，不能只看 `is_compiled_with_cuda()`。
- **下一步（计划，未完成）**：如需要，可在画板演示启动脚本中增加 GPU 选项（GPU venv + `RECOGNIZER_DEVICE=gpu:0`），并实测一次鼠标写公式的端到端延迟。

## 2026-11-20 收口已知缺陷：整页公式、torch 导入顺序、画板 GPU、12 样本真值

**阶段状态：整页行内公式与 Unicode 数学符号已修复并测试；默认 `.venv` 真实识别恢复；画板已可用 GPU 启动；12 条用户确认真值已建立并完成一次 GPU 精确匹配评估。整页逐字真值与本地整页识别仍未完成。**

- **本次任务**：用户针对上一轮列出的缺口说“来吧，干活”，要求处理：整页 `$...$` 被转义与缺字形、paddle/torch 导入顺序、画板接入 GPU、转录准确率真值、未提交改动。
- **实际修改文件**：`D:\latex\workbench\full_page.py`、`D:\latex\tests\test_workbench.py`、`D:\latex\recognizer.py`、`D:\latex\scripts\launch_demo.ps1`、`D:\latex\启动画板.bat`、`D:\latex\demo\app.py`、`D:\latex\demo\requirements-demo.txt`、`D:\latex\README.md`、新增 `D:\latex\data\handwritten_ground_truth.json`、`D:\latex\reasoning\handwritten_eval.py`、`D:\latex\tests\test_handwritten_eval.py`，追加本日志。
- **整页转写修复（已测试）**：`_escape_text` 现在保留成对的 `$...$` 与 `$$...$$`，把正文和公式片段里的 ∈、≤、∑、π 等 27 个 Unicode 数学符号转成 LaTeX 命令，只有落单 `$` 才转义；含中文的成对 `$` 仍按字面处理，避免把“价格 $5 … $10”误判成公式。新增 7 项 workbench 用例，包含 build_tex 段落保留 `$x\in A$`。
- **torch 导入顺序（已实测）**：`recognizer.py` 新增 `_formula_recognition_class()`，仅在 Windows 上、加载 `paddleocr` 前按需先 `import torch`，失败则跳过。默认 `.venv` 运行 `recognizer.py samples/sample_plus.png` 成功：模型加载 9.5 s、推理 26.02 s，输出 `x^{3}-x^{2}+x^{2}+x-x+3x-3+4`，不再出现 `WinError 127 ... shm.dll`。
- **画板 GPU（已实测）**：`scripts/launch_demo.ps1` 新增 `-Gpu`，切换到 `.venv\gpu-venv` 并设置 `RECOGNIZER_DEVICE=gpu:0`；GPU 环境缺画板依赖时按 `demo/requirements-demo.txt` 安装。已向 GPU 环境装入 streamlit 1.67.0、streamlit-drawable-canvas 0.13.0、openai 3.57.0、python-dotenv 1.2.4。用 `-Gpu -NoBrowser -Port 8599` 启动成功，浏览器实测显示“识别设备：GPU（gpu:0）”；`nvidia-smi` 的 compute apps 中出现该 Streamlit 进程，Paddle 日志报告 `GPU Compute Capability: 12.0`。测试后已停止该进程。
- **12 样本真值（已建立）**：从 4 份旧评估产物合并出 `data/handwritten_ground_truth.json`，12 条均标注 `review_status=ground_truth_user_confirmed`，保留原 `review_note` 与来源产物路径；没有生成或修改任何真值。`reasoning/handwritten_eval.py` 复用 C 的 `evaluate_refinement` 口径（strip 后整串精确匹配），单样本失败不中断整轮。
- **GPU 实测准确率（2026-11-20）**：RTX 5070 Laptop、`PP-FormulaNet-L`、`gpu:0`，12 样本 raw 精确 5/12（41.7%），final 精确 5/12（41.7%），C 改写正确结果为错误 0 条；规则复核命中 1 条（sample_3 结构问题），漏判 7 条。7 条错误分别是：sample_6 多出裁剪边界外的编号/根式、sample_7 漏因子 4、sample_8 单撇/双撇混淆、sample_9 `o`→`0`、sample_10 指数与分子错误、sample_11 双撇→`n`、sample_12 `2!`/`3!`→`21`/`31` 且多减号。完整报告在 `artifacts/handwritten_eval_gpu.json`。
- **实际测试**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 159 tests in 11.800s`、`OK`；新增的 Tectonic 用例真实编译含 `$x∈A$` 与 `x ≤ 3` 的段落，验证日志无 `Missing character`。日志中的 `RuntimeError: page two exploded` 是故障注入用例的预期输出。
- **证据边界**：12 条是公式裁剪图，不是整页；样本量小且曾用于冲突分析，41.7% 不能当泛化准确率或性能基准。整页识别仍走远端 `deepseek-flash`，本机 GPU 未覆盖整页版面分析/中文 OCR，`transcription_accuracy` 对整页仍未评估。画板 GPU 只验证了启动、页面设备显示和进程占用 GPU，没有重新用鼠标画公式做端到端识别计时。
- **Git 状态**：本条目与上述代码、文档改动放在同一提交中（提交哈希见 `git log -1`）；本次不推送远端。
- **学习进度**：修复“缺字”不一定要换模型，先把编码确定性转成 LaTeX 就能消除一类问题；但 7/12 的真实识别错误是模型本身看错，规则复核无法兜底，必须靠人工对原图核对。
- **未完成事项**：整页逐字真值与准确率、本地整页识别、跨页语义一致性、模型多次运行稳定性统计仍未完成。

## 2026-11-20 识别准确率提升：换 UniMERNet，否定多视角凑数

**阶段状态：在同一 12 样本真值上完成 4 组模型/策略对比；画板优先切换到 UniMERNet 单视角，实测 final 精确匹配从 5/12 提升到 8/12。剩余 4 条错误未解决。**

- **本次任务**：用户要求“41.7% 提升看看”。本轮只做实测选型与引擎注册，不改 `schemas.py`，不通过改写错误结果提高数字。
- **诊断过程（全部实跑）**：PP-FormulaNet-L 多视角候选池 best-of-N 只有 7/12；PP-FormulaNet_plus-L 单视角 7/12、多视角 best-of-N 8/12；UniMERNet 单视角 8/12、多视角 best-of-N 9/12。对 sample_6/7/10/12 额外测试 zoom2/zoom3、加白边、锐化、对比度增强，均未产生正确结果；LaTeX_OCR_rec 在 sample_10 上输出无关公式，未采用。
- **选择器反证**：给 `reasoning/handwritten_eval.py` 增加 `--thorough` 后，用 UniMERNet 多视角 + C 的真实上下文选择跑 12 样本，发生 6 次付费 API 选择调用，final 反而 7/12：sample_3 被选中“补括号”的候选，sample_11 被选中 `2^x`，sample_10 被选中 `-84`。因此本轮不把多视角 + 选择器作为提升方案，也不把 9/12 的候选池上限写成实际准确率。
- **最终实测对比**：PP-FormulaNet-L 单视角 5/12（41.7%）；PP-FormulaNet_plus-L 单视角 7/12（58.3%）；UniMERNet 单视角 8/12（66.7%）；UniMERNet 多视角 + 上下文选择 7/12（58.3%）。报告分别在 `artifacts/handwritten_eval_gpu.json`、`handwritten_eval_plus_gpu.json`、`handwritten_eval_unimernet_gpu.json`、`handwritten_eval_unimernet_thorough_gpu.json`。
- **UniMERNet 仍错 4 条**：sample_6 裁剪含“(3)原式”而真值只取公式本体；sample_7 漏因子 4；sample_10 三撇与 `-24` 识别错误；sample_11 双撇变单撇。sample_6/7/10 在已试模型的所有多视角候选里都没有正确答案。
- **产品改动**：`recognizer.py` 把 `pp_formulanet_plus_l`、`unimernet` 注册为独立引擎，已知 `RECOGNIZER_MODEL` 自动映射引擎名，`models/<模型名>` 都可作为本地权重目录；`scripts/launch_demo.ps1` 在存在 `models/UniMERNet` 且用户未显式指定模型时优先使用 UniMERNet，并把 `PADDLE_PDX_CACHE_HOME` 固定到仓库 `.paddlex`；`demo/app.py` 显示模型名与设备；`.gitignore` 排除 `.paddlex/`。`tests/test_recognizer.py` 新增引擎映射自测。
- **新发现的环境坑**：PaddleX 默认缓存 `%USERPROFILE%\.paddlex` 含中文用户名时，PP-FormulaNet_plus-L、UniMERNet、LaTeX_OCR_rec 都在建 predictor 时报 `inference.json` 空输入 parse error；复制到 ASCII 的 `models/<模型名>` 后均能加载。UniMERNet 权重约 1.6 GB，已放在本机 `models/UniMERNet`（Git 忽略）。
- **浏览器实测**：`启动画板.bat -Gpu` 等价命令启动后，页面显示“识别模型：UniMERNet · 设备：GPU（gpu:0）”；`nvidia-smi` compute apps 中能看到 Streamlit 进程。测试后已停止。
- **CPU 兼容实测**：默认 `.venv` 设 `RECOGNIZER_MODEL=UniMERNet` 跑 `samples/sample_plus.png`，引擎名正确为 `unimernet`，模型加载 10.3 s、推理 21.95 s，输出与 GPU/PP-FormulaNet-L 相同。
- **实际测试**：B 自测脚本全部 PASS（含新增引擎映射）；`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 160 tests in 12.108s`、`OK`。
- **证据边界**：8/12 来自同一批 12 个裁剪图，且这些样本参与了本轮选型，不能当泛化准确率；UniMERNet 单视角中位识别延迟约 0.79 s，仅为本机本次测量。整页识别仍走远端 API，不受本次换模型影响。
- **Git 状态**：本条目与代码、报告、文档改动放在同一提交中（哈希见 `git log -1`）；本次不推送远端。
- **学习进度**：提高精确匹配率不能靠“把候选修得更像数学”，多视角只扩大候选池，选择器本身也会选错；独立模型的错误分布不同，先用真值集测清单视角收益，再决定是否引入更复杂的仲裁。
- **未完成事项**：sample_6 需要公式区域裁剪/ prose 排除策略，sample_7/10 需要更强手写识别或更多独立模型；上下文选择的忠实性仍需专门评估与改进。

## 2026-11-21 工作台完善：任务恢复、原稿管理、失败页重试

**阶段状态：工作台的任务恢复、最近列表、TeX 下载/恢复、失败页页码映射、复核状态保存和单页重试均已实现并通过后端与浏览器验证；未修改 `schemas.py`。**

- **本次任务**：目标“完善工作台”。先读当前代码，确定实际缺口为刷新丢任务、不能下载/恢复 TeX、复核勾选不保存、失败页导致页码跳行错位，以及失败页只能整批重传。
- **后端改动（`workbench/app.py`）**：新任务保存 `job.json`、`compile.json` 和每页 `document.json`；新增 `GET /api/jobs` 最近列表，`GET /api/jobs/{id}` 返回完整任务，老任务无元数据时按目录重建；新增 `/tex`、`/original` 下载、`/restore-original` 恢复编译、`/pages/{page}/retry` 单页重试。重试只调用失败页的 `generate_document`，成功页从 `document.json` 复原；老任务缺结构时返回 409，不偷偷整批重跑。
- **页码修复**：每个成功页记录 `merged_page`，失败页为 `null`；前端跳页和复核计数按合并页序映射。浏览器初审曾发现新写的 `pageReviewCount` 错把页码数字当页对象，已修正为按页码查对象后复测通过。
- **前端改动（`workbench/static/index.html`）**：最近任务下拉、地址栏 `#job=<id>` 刷新恢复、复核勾选按任务存 localStorage、当前/原稿 TeX 下载、恢复原稿确认、失败页“重试这一页”按钮与付费提示；未保存修改在离开页面前警告。
- **后端测试**：新增任务列表/恢复/下载/原稿恢复测试、老任务元数据重建测试、失败页重试测试；重试测试确认识别总调用从 3 次只增加到 4 次，且第 4 次路径是 `page_02`，合并顺序为甲/乙/丙，重复重试成功页返回 409。`test_workbench_app` 共 14 项通过。
- **浏览器实测**：本地构造三页任务（第 2 页失败），通过 `#job=` 打开后真实 Tectonic 编译成功；页签分别为无标记/识别失败/1 处待复核，计数 `[0,0,1]`，点第 3 页选中正确代码行，勾选后 localStorage 写入 `{"3":true}`，刷新仍保留；下载链接与内容正确；手动改代码后“恢复识别原稿”恢复并重新编译。另用仅测试的 mock `generate_document` 服务器点击“重试这一页”，第 2 页变为成功、三页 merged_page 为 1/2/3、文本按第一页/第二页重试成功/第三页排列；未调用付费识别。测试服务器均已停止，临时 job 已删除。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 163 tests in 26.759s`、`OK`；`RuntimeError: page two exploded` 是故障注入用例的预期输出。
- **证据边界**：单页重试的浏览器验收用 mock 识别响应，证明的是前端点击、后端合并、编译和状态更新，不证明远端模型重试成功率；真实远端重试仍受余额、超时和模型稳定性影响。复核勾选保存在当前浏览器，不随任务目录跨设备同步。
- **Git 状态**：本条目与代码、文档改动放在同一提交中（哈希见 `git log -1`）；本次不推送远端。
- **未完成事项**：整页转录真值与本地整页识别仍未完成；任务列表目前最多展示 20 个，未做分页搜索；浏览器后退/前进导航未单独做 hash 历史管理。

## 2026-11-21 工作台任务搜索分页与历史导航

**阶段状态：上一项遗留的任务列表分页搜索和浏览器历史导航均已完成并实测。**

- **后端**：`GET /api/jobs` 新增 `q`（标题或 job id 子串）、`limit`、`offset`，返回 `total/limit/offset`。新增分页搜索测试，两个“分页验收”任务在 `limit=1` 下页 0/页 1 不重复，按 id 可搜，空结果返回 0。
- **前端**：搜索框、查找/刷新、每页 10 个的上一页/下一页；`hashchange` 时按地址打开任务，空 hash 清空当前任务，避免后退/前进仍显示旧任务。新任务或重试成功后回到列表第一页。
- **浏览器实测**：两个本地任务“导航验收甲/乙”，搜索甲得到 `total=1` 且只剩甲；打开甲后改 hash 打开乙，`goBack()` 回到甲、`goForward()` 回到乙，最后清空 hash 后 `jobId` 为空。测试后已停止服务器并删除临时 job。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 164 tests in 19.949s`、`OK`。
- **Git 状态**：本条目与代码、文档改动放在同一提交中（哈希见 `git log -1`）；本次不推送远端。
- **未完成事项**：整页转录真值与本地整页识别仍未完成；真实远端单页重试成功率未单独统计。

## 2026-11-21 本地识别配置统一改为 GPU

**阶段状态：本机 `.env`、`.env.example` 和画板启动默认路径已切到 UniMERNet + gpu:0；CPU 保留显式兜底。工作台整页识别仍走远端 API，不受影响。**

- **本地 `.env`（Git 忽略）**：新增 `RECOGNIZER_MODEL=UniMERNet`、`RECOGNIZER_MODEL_DIR=D:/latex/models/UniMERNet`、`RECOGNIZER_DEVICE=gpu:0`、`PADDLE_PDX_CACHE_HOME=D:/latex/.paddlex`；实测 `reasoner` 加载后四项均生效。
- **`.env.example`**：默认值同步改为 UniMERNet + gpu:0，并注明没有 NVIDIA GPU 时改回 PP-FormulaNet-L + cpu、画板用 `-Cpu`。
- **画板启动**：`scripts/launch_demo.ps1` 默认优先 `.venv\gpu-venv`；GPU 环境缺失时自动退回 CPU，显式 `-Gpu` 缺失则报错，`-Cpu` 强制 CPU 并覆盖 `.env` 的 `gpu:0`。`启动画板.bat` 注释同步。
- **工作台启动体检**：`scripts/launch.ps1` 的本地模型检查改为优先识别 `models/UniMERNet`，再检查 `PP-FormulaNet-L`，避免已有 UniMERNet 时误报缺模型。
- **浏览器实测**：不带 `-Gpu` 启动画板，日志显示“使用 GPU 环境（RECOGNIZER_DEVICE=gpu:0）”，页面显示“识别模型：UniMERNet · 设备：GPU（gpu:0）”；加 `-Cpu` 启动后页面显示“设备：CPU”，证明本地 `.env` 的 GPU 值被显式覆盖。测试服务器已停止。
- **测试隔离修复**：本地 `.env` 改变默认引擎后，`test_integration_bc.test_default_local_model_directory_is_used` 原先把 `DEFAULT_ENGINE` 当成 PP-L 写死；现改为显式传入 `ENGINE_PP_FORMULANET_L`，测试不再受本机 `.env` 影响。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 164 tests in 17.002s`、`OK`。
- **证据边界**：`recognizer.py` 的代码默认仍是 `cpu` 和 `PP-FormulaNet-L`，保证无 GPU 的克隆可运行；GPU 是本地配置而非公共默认。Web 工作台的整页转写仍调用远端 `deepseek-flash`，不会因为本机 GPU 而变快或本地化。
- **Git 状态**：`.env.example`、启动脚本、文档和测试改动放在同一提交中；`.env` 含密钥且被忽略，只在本机生效，不进入提交。
- **未完成事项**：真实鼠标书写到 GPU 识别的端到端延迟未重新计时；整页转录本地化仍未实现。

## 2026-11-22 图形主导页保留原图

**阶段状态：整页基本是图的页面现在自动嵌入原图并跳过重复标签；老任务可一键重建；图文混排页保持原描述框。**

- **问题证据**：用户截图任务 `7bd4e97a3a494dd1b03a025a7547b17c` 的 `page_01/document.json` 有 13 块——1 个 figure 描述 + 12 个把图中标签逐条抄出的 paragraph。旧 `build_tex` 把 figure 渲染成“原始示意图（未重新绘制）”文字框，导致 PDF 既没有图，又重复了标签。
- **判定规则**：`_figure_dominant_page` 仅在一页恰有一个 figure、描述不少于 120 字符、源图文件存在、其余全是长度不超过 200 的 paragraph，且至少除一条外的标签首行出现在图注中时，认定为图形主导页；图文混排或长正文页不触发。
- **生成改动**：`generate_document` 给 figure 块写 `source_image` 绝对路径；`build_tex` 先按 `page_break` 分页，图形主导页用 `\includegraphics` 嵌入原图（`width=0.92\linewidth,height=0.78\textheight,keepaspectratio`）并只保留首句图注，其他标签不再输出；普通/混排 figure 仍走原描述框。
- **老任务重建**：新增 `POST /api/jobs/{job_id}/figures/use-source`，读取已有 `document.json`、补 `source_image`、重建 TeX 和 PDF，不调用识别模型；任务返回 `has_figures`。前端只在当前 TeX 仍含“未重新绘制”占位时显示“图形页改用原图”按钮，重建后按钮隐藏。
- **浏览器实测**：复制用户真实图形页为临时任务 `2222…`，打开后 `has_figures=true`、TeX 含占位、无 `\includegraphics`；点击按钮后 `\includegraphics` 出现、占位和重复标签消失、`hasPdf=true`，`pymupdf` 确认 PDF 第 1 页含 1 张嵌入图片；按钮随后隐藏。测试服务器已停止，临时任务已删除，原用户任务未被修改。
- **实际测试**：新增 3 项 build_tex/generate 测试、1 项真实 Tectonic 图形页编译测试、1 项重建端点测试；`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 169 tests in 31.248s`、`OK`。
- **证据边界**：仅图形主导页会嵌整页原图；图文混排仍需文字描述，因为模型没有返回图形裁剪框。嵌入的是图片，图内文字不再作为可搜索文本保留，这是“保留视觉原图”的代价。源图路径记录为本机绝对路径，任务目录移动后需点一次重建或重新上传。
- **Git 状态**：本条目与代码、文档、测试改动放在同一提交中（哈希见 `git log -1`）；本次不推送远端。
- **未完成事项**：图文混排页的精确裁剪区检测、图形页多图拆分、整页转录真值仍未完成。

## 2026-11-23 提速、可信度信号、改稿便捷性与独立安装包

**阶段状态：本轮按用户要求"不要再死磕正确率，重点是速度、可操作便捷性、打包成软件、把状态和可信度都摆出来让人判断哪里可能有问题"做。已完成并行识别、真实信号落盘、系统状态面板、改稿便捷性、打包脚本与安装器脚本；全量回归 180 项通过，zip 包已解压实跑验证。准确率相关代码本轮未改。**

- **速度：多页并行识别**。`workbench/app.py` 的 `_page_concurrency()` 读 `WORKBENCH_PAGE_CONCURRENCY`（默认 3，夹在 1~10，再和实际页数取小），`_create_document` 用 `ThreadPoolExecutor` 并发发每页的云端请求。实测（mock 两页延迟 2.0 s / 1.0 s）浏览器端总耗时 2036 ms，小于串行的 3000 ms；服务端探针显示两页起始时刻相同、合计 2017 ms。
- **速度：编译复用**。TeX 与上次逐字节相同且 `main.pdf`、`compile.json` 都在时直接返回 `reused: true`，不再跑 Tectonic；前端提示"代码没变，直接复用了上一次的编译结果"。
- **可信度信号只记真实值**。`workbench/full_page.py` 新增 `_usage_signal()`：落盘 `finish_reason`、真实 `prompt/completion/total_tokens`、`max_tokens`、`near_token_budget`（输出达到预算 95% 以上才为真）、`attempts`、`retried`，再加 `_block_stats()` 的块数量统计和该页 `latency_ms`。**没有引入任何自造分数**；界面明写"系统不给识别可信度分数"，理由是无法验证。`raw_latex` 与原始识别结果未被覆盖。
- **运行进度登记**。`_RUNS` 是加锁的内存字典，最多留 20 条；客户端生成 32 位十六进制 `run_id` 随 multipart 上传，不合法就退回用 `job_id`；`GET /api/runs/{run_id}` 供前端每 1.2 秒轮询逐页状态与耗时。修掉一处真实缺陷：客户端最后一次轮询晚于任务完成，导致总耗时记不上，改为 `fetchRun()` 并在 `upload()` 的 `finally` 里 await 一次。
- **系统状态面板**。`GET /api/status` 只报可核查事实：版本与提交号（`BUILD_INFO.json` 或 git）、Python 与平台、OpenAI 配置（**只报密钥长度**）、Tectonic 路径与版本、ctex 字体集、本地识别配置与已下载模型、并行页数、前端 `vue.global.js` 来源、任务目录与占用。子进程与目录扫描结果缓存 30 秒。顺手修了 `_tectonic_status()` 把版本读成 `"T"` 的 bug（原来在遍历字符串而不是按行切分），并补了单测。
- **改稿便捷性**。`Ctrl+S` 编译；`F2` 跳下一处待复核并显示"正在看第 N / M 处待复核（第 X 行）"；编辑内容每 1.2 秒存进 localStorage，与服务器版本不一致时给出"恢复我的修改 / 丢弃"；新增 `GET /api/jobs/{id}/history` 与 `POST /api/jobs/{id}/restore-history`，因为每次写 `main.tex` 都会留一份 `history/<uuid>.tex`，所以回滚是真的撤销（最多列 50 份）。修掉两个前端缺陷：`loadJobs` 没从 `setup()` 返回（"最近任务"的刷新按钮点了没反应）、`reviewCursor` 没暴露。
- **打包脚本**。新增 `scripts/package.ps1`：按第十节口径的排除清单 robocopy 复制 → 把 `node_modules/vue/dist/vue.global.js` 复制进包（目标机器不需要 Node.js）→ 写 `BUILD_INFO.json` → 放入 `installer/安装说明.txt` → 逐项核对该在的在、不该带的没带 → 扫描包内全部文本文件确认本机 `OPENAI_API_KEY` 的值没混进去（扫到即中止）→ 压 zip 并打印 SHA256 → `-BuildInstaller` 时若本机有 Inno Setup 6 就编 `setup.exe`。脚本只读仓库、只往 `dist/` 写。
- **安装器脚本**。新增 `installer/hand2latex.iss`（`PrivilegesRequired=lowest`，装到 `{localappdata}\Programs\Hand2LaTeX`，卸载时删 `.venv`/`__pycache__`/`node_modules`，`artifacts` 交给卸载提示决定）和中文 `installer/安装说明.txt`。**本机没有安装 Inno Setup，`.iss` 没有编译验证过**，`package.ps1` 在这种情况下会如实告警而不是假装成功。
- **打包过程中真找到并修掉的两个缺陷**：① PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会给 `BUILD_INFO.json` 写 BOM，`json.loads(read_text(encoding="utf-8"))` 解析失败后静默回退到 git，安装包状态里错报"来源：开发仓库"；改为用 .NET 写无 BOM UTF-8，同时 `_build_info()` 用 `utf-8-sig` 读以兼容旧包，并补了带 BOM 的单测。② `Compress-Archive -Path $Staging\*` 让 zip 里没有顶层文件夹，用户"解压到当前文件夹"会把几百个文件撒出来；改为压缩整个暂存目录，`安装说明.txt` 的措辞同步改。
- **实际验证（针对最终那个 zip 本体，不是暂存目录）**：`dist/Hand2LaTeX-1.0.0-win64.zip`，20.4 MB，SHA256 `7A4C1099D9653629E05D493AB2538827D75EB6719A988084AE54CB39B8CA5941`。解压到临时目录后从解压目录起服务（8014 端口）：`/api/status` 报告 `build.source = 安装包`、`commit = 30cc4f9`、`built_at` 有值、前端来自随包副本、Tectonic 0.17.0 在包内可用、任务数 0、`openai.configured = false`（包里不带 `.env`，如实报未配置）；`/vendor/vue/vue.global.js` 返回 200、609371 字节；无头浏览器打开首页 Vue 正常挂载（10 个状态 chip、上传控件存在、`pageErrors` 为空），状态详情显示"来源 安装包""vue.global.js 来自随安装包携带的副本""API 密钥 未配置：上传识别、修复建议都用不了"，页面文本里没有出现任何密钥长度数字。核对 `/api/status` 响应体不含本机 `OPENAI_API_KEY` 的值。测试服务已停止，解压目录已删除。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 180 tests in 27.170s`、`OK`（14 个模块有测试项，`tests/test_recognizer.py` 是契约自检脚本，unittest 收 0 项）。浏览器实测用 mock 识别 + mock 编译的临时服务器（8012 端口）跑完整流程，结果 `STATUS CHECK OK`、`pageErrors: []`，覆盖：状态条与详情表、逐页实时进度、每页真实信号 chip、编译复用提示、草稿保存/刷新/恢复、`Ctrl+S`、历史版本列表与回滚、`F2` 跳转与位置计数。mock 服务器已停止，临时任务目录已清理。
- **证据边界**：本轮**没有用真实付费 API 跑过任何识别**，速度结论来自 mock 延迟（2.0 s / 1.0 s）下的并发行为，证明的是"请求确实并行发出"，不是真实网关下的提速倍数；真实网关可能限流，并行度调大后未实测。状态面板、进度、信号、便捷性同样是在 mock 下验证的。安装器 `.iss` 未编译验证。准确率相关的评估口径与真值集本轮未动，整页转录仍然没有逐字真值。
- **边界遵守**：`schemas.py` 未被修改（公共契约不动）；未越界改 A、B 的文件；`raw_latex` 与识别原稿保留；未编造置信度或测试结果，上面每条数字都来自本次实际运行的输出。
- **Git 状态**：本条目与代码、文档、测试改动放在同一提交中；`.env` 含密钥且被 git 忽略，不进入提交；`dist/` 被忽略，zip 只在本机。本次不推送远端。
- **未完成事项**：`installer/hand2latex.iss` 的真实编译验证；真实付费 API 下的并行提速倍数与限流表现；10 页以上大批量的并行压测；整页转录真值集仍缺；安装包在"干净机器"（没装过 Python 依赖、没有 `.env`）上的首次启动全流程未实测。

## 2026-11-23（晚）安装器真的编出来并实装实卸验证过了

**阶段状态：上一条里"未编译验证"的 `installer/hand2latex.iss` 现在编译通过、装得上、跑得起来、卸得干净。上面那条未完成事项里的"安装器真实编译验证"已完成，其余仍未做。**

- **装 Inno Setup 的过程（含网络受阻的真实处理）**：`winget install JRSoftware.InnoSetup` 失败，报 `InternetOpenUrl() failed 0x80072efd`——winget 的安装器 URL 指向 GitHub，本机 `github.com` 直连不通（curl 返回 000），本机那个 127.0.0.1:7897 代理端口也没在监听。jrsoftware.org 官方站可通，但 `files.jrsoftware.org/is/6/` 下只有 `.issig` 签名文件，官方下载页的 exe 链接同样指向 GitHub。改走镜像 `ghfast.top` 下载 `innosetup-6.7.3.exe`，**下载后用 winget 清单里公布的官方 SHA256 `9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732` 核对，一致才运行**（另一个镜像 `ghproxy.net` 下载不完整、哈希不符，已丢弃）。安装器留在 `.venv/innosetup-6.7.3.exe`（git 忽略）。
- **安装位置与开关踩坑**：第一次静默安装"退出码 0 但什么都没装"，日志显示 Git Bash 把 `/VERYSILENT` 之类开关转成了路径（`C:/Program Files/Git/VERYSILENT`）；改用 PowerShell `Start-Process -ArgumentList` 传参才生效。安装器按注册表里旧的安装位置装到了 `D:\API\Inno Setup 6`（不在 PATH，也不在脚本原来探测的三个默认目录里）。
- **因此改了 `package.ps1` 的 ISCC 查找顺序**：`-Iscc` 参数 → PATH → 三个默认目录 → **注册表卸载项的 `InstallLocation`**（本机靠这一步才找到）。顺手修了两个自相矛盾/不好用的地方：① 原来"清理临时目录"排在"编安装器"之前，导致 `-BuildInstaller` 不加 `-KeepStaging` 必然失败，现在清理挪到最后；② 安装器的 SHA256 也一起打印出来。
- **简体中文安装界面**：Inno Setup 6.7.3 的 `Languages\` 里**没有** ChineseSimplified.isl（官方安装器不带简体中文），原脚本引用 `compiler:Languages\ChineseSimplified.isl` 必然编译失败。改为把官方翻译（标注适用 6.5.0+，取自 jrsoftware.org/files/istrans 指向的仓库，经镜像下载）随仓库放在 `installer/languages/ChineseSimplified.isl`，补上 UTF-8 BOM，`.iss` 引用相对路径，这样换一台构建机也不需要动 Inno Setup 的安装目录。
- **编译结果**：`ISCC 6.7.3` 报 `Successful compile`（约 28 s），产出 `dist/Hand2LaTeX-1.0.0-win64-setup.exe`，15.5 MB，SHA256 `6C102726C542158089BBB562F7E4EEB6C96629B3FFD792E766D2798B80C5E745`；同一次运行的 zip 为 20.4 MB，SHA256 `5A38761F4FB228CD434EB435FDED5872245B37D0B2F7E6663B3A34337CD461CD`。
- **实装验证（装到 git 忽略的 `.venv\installtest`，不是用户目录）**：静默安装退出码 0；核对启动/关闭脚本、`安装说明.txt`、`BUILD_INFO.json`、`tools\tectonic\tectonic.exe`、随包 `vue.global.js`、`unins000.exe` 都在，`.env`/`.venv`/`node_modules`/`models`/`artifacts`/`.git` 都没被带进去；安装日志里没有 `-- Run entry --`，证明 `[Run]` 的 `skipifsilent` 生效、静默安装不会自己把工作台启起来。从安装目录起服务（8015 端口）实测：`build.source = 安装包`、`commit = fd1592d`、前端与 Tectonic 路径都在安装目录内、任务目录也在安装目录内、`openai.configured = false`（不带 `.env`，如实报未配置）。
- **实卸验证**：先塞进 `artifacts\jobs\keepme.txt` 和 `workbench\__pycache__`、`reasoning\__pycache__`，再 `/VERYSILENT` 卸载：退出码 0，程序文件、`.venv`、各层 `__pycache__`、开始菜单组、HKCU 卸载项全部清掉，`artifacts\jobs\keepme.txt` **按设计保留**。临时安装目录已删除。
- **验证过程中真找到并修掉的两个缺陷**：① 我给"卸载时问要不要删 artifacts"加的弹框判断误用了 `WizardSilent`——那是安装阶段的函数，卸载阶段调用会抛 `内部错误：Cannot call "WizardSilent" function during Uninstall`，静默卸载直接退出码 1、什么都没删（日志抓到的原文），改用 `UninstallSilent`；同时给安装阶段"没检测到 Python"的提示也加了静默判断，避免静默安装被弹框卡住。② `[UninstallDelete]` 只删顶层 `__pycache__`，`workbench\` 与 `reasoning\` 下的没删，卸载后留 12 个垃圾条目，已逐条补上。另外发现原脚本注释和 `安装说明.txt` 都写着"卸载向导会问要不要保留任务产物"，但当时**根本没有这段代码**——这次把 `InitializeUninstall` 真写出来了，文档才不是假承诺。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 180 tests in 30.926s`、`OK`（本轮没改 Python 代码，只改了打包脚本、安装脚本和文档）。最终那个 zip 也重新解压跑了一遍：`/api/status` 与无头浏览器检查全过（`PACKAGE PAGE CHECK OK`，`pageErrors: []`，页面上没有任何密钥长度数字）。
- **证据边界**：只验证了**静默**安装与**静默**卸载；带界面的向导（选目录、勾桌面快捷方式、卸载时那个"要不要删 artifacts"的对话框）**没有人工点过一遍**，只做了代码审阅，所以对话框的实际文案与按钮行为没有实测证据。安装包里不含 Python，干净机器上的首次启动全流程仍未实测。ISCC 是从镜像下载后按官方 SHA256 核对的，核对通过才运行；但镜像本身不是官方分发点，这一点如实记下。
- **边界遵守**：未改 `schemas.py`，未越界改 A、B 的文件，未编造测试结果；本机新装的 Inno Setup 6 在 `D:\API\Inno Setup 6`（用户级、非仓库内），仓库里只多了 `installer/languages/ChineseSimplified.isl` 这一个第三方文件。
- **Git 状态**：本条目与打包脚本、安装脚本、语言文件、文档改动放在同一提交中；`dist/` 与 `.venv/` 都被忽略，zip、setup.exe 和下载的安装器只在本机。本次不推送远端。
- **未完成事项**：带界面安装向导的人工走查；干净机器（无 Python 依赖、无 `.env`）上的首次启动全流程；真实付费 API 下的并行提速倍数与限流表现；10 页以上大批量压测；整页转录真值集仍缺。

## 2026-11-23（更晚）打包告警说准话，并在干净提交上重打、重验两个产物

**阶段状态：`package.ps1` 的两处告警改成如实描述；在提交 `8ea79e6` 的干净工作区上重打了 zip 与 setup.exe，两个产物都重新走了一遍完整验证。**

- **告警修正一**：原来只要 `git status --porcelain` 非空就报"安装包里会带上这些改动，但提交号对不上"。实际触发它的是未跟踪文件（`artifacts/compile_smoke/`、`docs/assets/repair_pdf_page_*.png`），已跟踪文件当时是干净的，提交号并没有对不上。现在分开报：`--untracked-files=no` 的结果才触发"提交号对不上"，未跟踪文件单独报数量和第一个例子。
- **告警修正二**：未跟踪文件那条最初把 `artifacts/compile_smoke/error.tex` 当成例子，但 `artifacts` 本来就在 robocopy 排除清单里，根本不会进包。把排除清单提到脚本开头并抽出 `Test-ExcludedPath`，未跟踪文件先按同一份清单过滤再报告；现在报的是 2 个真会进包的文件（`docs/assets/repair_pdf_page_1.png`、`_2.png`）。
- **重打与重验**：在提交 `8ea79e6` 上重跑 `package.ps1 -BuildInstaller`，`BUILD_INFO.json` 记的提交号就是 `8ea79e6`，已跟踪文件无未提交改动。产物：`dist/Hand2LaTeX-1.0.0-win64.zip` 20.4 MB、SHA256 `C30DFA363D75E565B74A08B849EF3EFBBF5B2ED639D7D9520698BD93B6D80E37`；`dist/Hand2LaTeX-1.0.0-win64-setup.exe` 15.5 MB、SHA256 `7BDC80C048D857556142235906065E22BF8D4AE97BF2ACED2BC4985A4C6A8D71`（ISCC 6.7.3，`Successful compile` 约 17 s）。
- **zip 验证**：解压到临时目录、从解压目录起服务（8014）：`build.source = 安装包`、`commit = 8ea79e6`、前端来自随包副本、Tectonic 可用、任务数 0、`openai.configured = false`；无头浏览器首页检查 `PACKAGE PAGE CHECK OK`（10 个状态 chip、上传控件在、详情显示"来源 安装包"与"API 密钥 未配置"、`pageErrors: []`、页面无任何密钥长度数字）。
- **setup.exe 验证**：静默装到 `.venv\installtest`（退出码 0），关键文件齐（启动脚本、`BUILD_INFO.json`、`tools\tectonic\tectonic.exe`、随包 `vue.global.js`、`unins000.exe`）；从安装目录起服务（8015）实测 `build.source = 安装包`、`commit = 8ea79e6`、前端/Tectonic/任务目录全在安装目录内、云端识别如实报未配置；塞入 `artifacts\jobs\keepme.txt` 与 `workbench\__pycache__\app.pyc` 后静默卸载退出码 0，程序文件、`__pycache__`、开始菜单组、HKCU 卸载项全清，`keepme.txt` 按设计保留。临时安装目录与解压目录都已删除，测试服务已停止。
- **实际回归**：本轮只改了 `scripts/package.ps1` 与文档，没动 Python 代码；上一次全量回归（`Ran 180 tests`、`OK`）对应的 Python 代码与现在完全一致，本轮未重跑。
- **证据边界**：仍然只验证了静默安装/静默卸载，带界面的向导没有人工点过。两个 SHA256 只对这一次构建有效——`README.md` 与 `TEAM_LOG.md` 本身也在包里，本条目提交后再打包哈希必然变，这一点已写进 README 6.5，避免以后拿旧哈希去核对新包。
- **Git 状态**：`fcc2d52`（告警分开报）、`8ea79e6`（告警按排除清单过滤）为代码提交；本条目与 README 的哈希更新为随后的文档提交。`dist/` 与 `.venv/` 均被忽略，产物只在本机。本次不推送远端。
- **未完成事项**：带界面安装向导的人工走查；干净机器上的首次启动全流程；真实付费 API 下的并行提速与限流表现；10 页以上压测；整页转录真值集仍缺。

## 2026-11-24 真实付费 API 跑通端到端：并行提速 2.81 倍，并暴露识别不确定性

**阶段状态：上一条里"真实付费 API 下的并行提速"已完成实测。走的是产品真实链路（`POST /api/documents/batch` → 并行识别 → 信号落盘 → Tectonic 编译），不是 mock。同时暴露出远端整页识别不是确定性的，这一点已写进 README 的"尚未证明"。**

- **怎么跑的**：素材是 `data/pdf_pages/page_2.png`、`page_3.png`、`page_4.png`（3 张真实手写笔记页，共约 265 KB）；模型 `deepseek-flash`（`OPENAI_BASE_URL=https://api.deepseek.com/v1`，输出预算 24000，单页超时 120 s）。起两个真实服务实例：8016 端口 `WORKBENCH_PAGE_CONCURRENCY=3`、8017 端口 `WORKBENCH_PAGE_CONCURRENCY=1`，同样 3 张图各跑一轮。客户端脚本 `.venv/real_api_check.py`（git 忽略）在发请求的同时每 0.4 秒轮询 `/api/runs/{run_id}`，记录"同时有几页在跑"。
- **实测提速 2.81 倍**：并发 3 客户端实测总耗时 82721 ms（服务端 run 记 82658 ms），串行 1 为 232729 ms（run 记 232688 ms）。并发轮三页开始时刻为 run 起点后 8 / 12 / 13 ms，串行轮为 3 / 77600 / 200047 ms；客户端轮询看到的同时在跑页数上限分别是 3 和 1（轮询样本 203 与 573 个）。三页各自耗时：并发轮 65258 / 71311 / 77329 ms，串行轮 77596 / 122447 / 28862 ms。
- **真实信号（全部来自模型返回，未加工）**：两轮 6 页 `finish_reason` 全为 `stop`，`attempts` 全为 1（没有触发重试），`near_token_budget` 全为 `false`；prompt_tokens 每页 920，completion_tokens 并发轮 16354 / 18211 / 10892、串行轮 18959 / 20232 / 6754，两轮合计 91402；单页最高用到输出预算的 84%（20232/24000）。6 页 `human_review` 全为 `required`。
- **编译与复用**：两轮 Tectonic 都真实编译成功（并发轮 PDF 32 KB、`errors` 为空、`returncode` 0），紧接着用同一份 TeX 再调一次 `/api/jobs/{id}/compile`，两轮都返回 `reused=true`——编译复用路径在真实环境验证过。
- **发现一：远端整页识别不是确定性的**。同样 3 张图、同一模型跑两轮，TeX 长度 2799 vs 3052 字符；块统计也不同：第 1 页 `paragraph/display_formula` 为 5/17 与 3/19，第 2 页为 0/16 与 0/8。**没有真值集，无法判断哪一轮更接近原文**，因此"重试这一页"必然给出不同结果，`human_review=required` 不是保守而是必要。这条已改写 README 第一节原来的"模型稳定性只有单次证据"。
- **发现二：3 张原图编出 4 页 PDF，这是正常的**。用 pymupdf 核对：`main.tex` 里 `\newpage` 是 2 个（对应 3 页，正确），第三页内容在 LaTeX 里自然溢出到第 4 个 PDF 页（第 3 PDF 页 650 字符、第 4 页 291 字符）。所以**"PDF 页数 ≠ 原图页数"不能当复核信号**，否则会天天误报；真正的缺口是 PDF 窗格只是 `iframe`，点左栏原图页只把代码跳到对应行、不会把 PDF 跳到对应页，要做这个映射需要在编译时记录每个 `\newpage` 落在第几个 PDF 页。
- **发现三（环境坑）**：本机 `NO_PROXY=[::1],::1` 会让 httpx 直接抛 `InvalidURL: Invalid port: ':1]'`（它把该值当 URL 解析）。测试脚本改用 `httpx.Client(trust_env=False)` 绕过；产品里的 OpenAI 调用不受影响，本次真实识别成功即为证据。以后写任何用 httpx 的本机脚本都会再撞一次。
- **证据落盘**：`artifacts/real_api_parallel/run_concurrency_3.json`、`run_concurrency_1.json`（含逐页 signals、run 时间线、compile 日志）与 `summary.json`（对照与结论）。两个任务目录在 `artifacts/jobs/`（git 忽略）：`1ba16d725fc74dbab41d4e8c646435f1`、`a94781454db842ea987212fae72421b3`。两个测试服务已停止。
- **证据边界**：每种并发只跑了一轮、只有 3 页，**没有压测并行度上限，也没有遇到网关限流**，所以"并发调大一定更快"仍无证据；`near_token_budget` 真实触发次数为 0，这条告警依然只有 mock 证据；本次没有做浏览器端验收（真实 API 只跑了服务端链路）；没有任何准确率结论——没有真值集，本轮不评转录正确性。
- **边界遵守**：未改 `schemas.py`，未改 A、B 的文件，未编造置信度；`raw_latex` 与识别原稿未被覆盖（两轮各自生成独立任务目录）。花费为 6 次真实整页识别调用、completion 合计 91402 token。
- **Git 状态**：本条目、README 9.3 与"尚未证明"的改写、以及 `artifacts/real_api_parallel/` 三个 JSON 放在同一提交中；`.venv/real_api_check.py` 与两个任务目录被 git 忽略。本次不推送远端。
- **未完成事项**：并行度压测与限流表现；10 页以上大批量；`near_token_budget` 的真实触发案例；PDF 页与原图页的映射；带界面安装向导的人工走查；干净机器首次启动全流程；整页转录真值集仍缺。

## 2026-11-24（晚）随包带 Python 运行时：安装包不再要求对方装 Python

**阶段状态：用户选定"随包带 embeddable Python"这条路，已实现并实测。zip 64.9 MB、setup.exe 44.1 MB，解压包与安装目录都用自己的启动器起过服务、跑过浏览器检查、静默卸载干净。全量回归 181 项通过。**

- **依赖面先查清再动手**：`requirements.txt` 里有 `torch>=2.2,<3`（几个 GB），但 torch 只被 `reasoning/risk_mlp.py`、`reasoning/train_risk.py` 和 `recognizer.py` 用到，Pillow 与 numpy 只被 `demo/app.py` 和 `recognizer.py` 用到；`recognizer.py` 里 PIL/torch/paddleocr 全是函数内延迟导入。工作台链路是 `workbench.app → workbench.full_page → reasoning.context`（只用 openai + dotenv），所以随包运行时只需要 7 个包，写进新文件 `requirements-app.txt`。
- **pymupdf 一处故意的版本分叉**：`requirements.txt` 钉 2.0，而 2.0 是元包，会拖进 `pymupdf-layout`（onnxruntime 54 MB + numpy 55 MB + networkx 18 MB）与 `pymupdf4llm`，实测运行时体积 **324 MB**；改钉 1.x 后 **111.5 MB**。代码里只用到 `pymupdf.open()` / `page_count` / `get_text()` / `get_images()` / `get_drawings()`（`workbench/multipage_eval.py`），这些 1.24+ 就有。为确认分叉安全，用同一个真实 PDF 在 1.28.2 与 2.0 上各跑一遍这五个 API：页数都是 4、末页文本都是 291 字符、图片都是 0、drawings 都是 4，**逐项一致**。
- **运行时怎么构建**（新脚本 `scripts/build_python_runtime.ps1`）：下载 `python-3.12.10-embed-amd64.zip`（缓存在 `.cache/`，git 忽略）→ **按 python.org 下载页公布的 MD5 `fe8ef205f2e9c3ba44d0cf9954e1abd3` 校验，不符即中止** → 解压到 `runtime/python/` → 改 `python312._pth`：保留原有 stdlib 条目，追加 `Lib\site-packages` 与 `..\..`（包根，这样 `import workbench` 才找得到）并启用 `import site`；embeddable 版**会忽略 PYTHONPATH**，所以只能写在这个文件里，且该文件只写 ASCII（它是 CPython 启动路径配置，不放中文注释）→ 用**构建机的 pip** `--target` 装依赖，故意不在运行时里装 pip（省 13 MB、少一次联网）→ 用随包 `python.exe` 真跑一次 `import workbench.app` 自检。构建机 Python 次版本必须与运行时一致（都 3.12），否则 wheel 的 `.pyd` ABI 对不上，脚本先核对再动手。
- **为什么选 3.12.10**：python.org 上 3.12.11~3.12.16 都是只发源码的安全维护版，`ftp/python/3.12.x/` 里**没有** Windows embeddable 二进制，逐个查过；3.12.10 是最新有 Windows 二进制的 3.12。
- **启动器改动**（`scripts/launch.ps1`）：检测到 `runtime\python\python.exe` 就完全不碰 `.venv`——不建虚拟环境、不 pip install、日志与 PID 改放 `runtime\`（`$VenvRoot` 整体切过去，`-Stop`/`-Status` 因此自动跟着走同一份 PID 文件）；网页依赖探针失败时不再"warn 后继续"，而是直接停下并提示重装（随包运行时缺依赖说明包坏了，自己 pip install 到 runtime 里是错的修法）；启动前自检从"跑 B 模块契约测试 `tests/test_recognizer.py`"换成"`import workbench.app`"，并明说跳过原因（随包运行时不含 paddle/torch，跑 B 侧契约没意义）；本地模型缺失从 warn 降为 info，因为安装包本来就不带模型。顺带修掉一句写死的提示"日志 .venv\workbench.log"，改成实际路径。
- **状态接口**：`/api/status` 新增 `python_runtime`（`executable` 绝对路径、`bundled` 是否随包运行时、`source` 中文说明、`in_virtualenv`），前端状态详情多一行"Python 运行时"；`BUILD_INFO.json` 也记 `python_runtime.bundled/version/covers`。配了单测（`_python_runtime()` 对随包路径报 bundled、对 `.venv` 路径不报）。
- **安装器**：用 ISPP 在编译期 `FileExists(SourceDir + "\runtime\python\python.exe")` 判断这个包有没有随包运行时，只有瘦包才在 `InitializeSetup` 里提示"没检测到 Python"；`[UninstallDelete]` 补上 `runtime\workbench.log`、`.log.err`、`.pid`、`probe_*.py`。
- **打包脚本**：新增 `-NoPython` 瘦包开关；`.cache` 与 `runtime` 加进排除清单；密钥扫描范围改成"只扫我们自己打包的文本文件"，随包运行时与 `tools/` 里的第三方文件不在范围内，并把这句话打印出来（原来会把几千个 site-packages 文件一起扫，慢且没有意义）；`BUILD_INFO.json` 的 `needs`/`bundled`/`not_bundled` 按是否带运行时分两种写法。`.gitignore` 补 `.cache/`。
- **打包核对抓到一个真问题**：构建运行时的自检探针 `import workbench.app` 会在包根建出 `artifacts\jobs`（`app.py` 在导入时就 `mkdir`），于是"artifacts 不该出现在安装包里"这条核对**失败并中止打包**。改成探针之后只删空的 `artifacts`（有文件就不动并告警）。这正是核对环节该有的作用。
- **实际验证（针对提交 `b9fae78` 干净工作区打出的最终产物）**：
  - 产物：zip 64.9 MB，SHA256 `6989654F8454C0D7F951B37E98F75430A4076D93DAA57E98E3AAEDE81D3E53EA`；setup.exe 44.1 MB，SHA256 `01B84DE262091BFE005EE0CDE392542A3F2AFF95EED275DB2EDDA66C60B98CFB`；随包运行时 111.5 MB；ISCC 编译 `Successful compile` 约 69 s。
  - 绿色包：解压后**用它自己的 `scripts/launch.ps1`** 起服务（8022），启动器输出"使用随包 Python 运行时（Python 3.12），不建虚拟环境、不装依赖""依赖齐全，无需安装""workbench.app 可以被随包运行时导入"；`/api/status` 报 `python_runtime.bundled=true`、解释器 `...\pkgcheck\Hand2LaTeX-1.0.0-win64\runtime\python\python.exe`、`in_virtualenv=false`、Python 3.12.10、`build.source=安装包`、`commit=b9fae78`、Tectonic 与任务目录都在包内、`openai.configured=false`；无头浏览器 `PACKAGE PAGE CHECK OK`（10 chip、上传控件在、详情显示"安装包随带的 Python 运行时"、`pageErrors: []`、无密钥长度数字）；`launch.ps1 -Stop` 停掉 PID 1960、端口关闭、`-Status` 报未运行。
  - 安装器：静默装机退出码 0，`runtime\python\python.exe`、`site-packages\uvicorn`、`requirements-app.txt`、`BUILD_INFO.json`（`python_runtime.bundled=true`、`version=3.12.10`）都在，`.env`/`.venv`/`.cache`/`node_modules`/`models`/`artifacts`/`.git` 都没进包；从安装目录用它自己的启动器起服务（8021）实测 `bundled=true`、解释器在安装目录内；塞入 `artifacts\jobs\keepme.txt` 与 `runtime\workbench.log` 后静默卸载退出码 0，程序文件、整个 `runtime\`（含日志）、`__pycache__`、开始菜单组、注册表项全清，`keepme.txt` 保留。临时目录已删。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 181 tests`、`OK`（新增 1 项 `_python_runtime` 测试）；mock 服务器 + Playwright 的 `STATUS CHECK OK` 重跑通过（状态详情多了一行"Python 运行时"，其余断言不变），`pageErrors: []`。
- **证据边界**：所有验证都在**本机**（装了 Python 3.12 的开发机）上做，**没有在一台真没装过 Python 的干净机器上跑过**，所以"零 Python 依赖"还差最后一道实证；带界面的安装向导依旧没有人工点过；随包运行时不覆盖画板与 B 侧本地识别（缺 torch/paddle/模型），文档与安装说明都写明了；卸载后 `.env`（可能含密钥）仍留在安装目录，卸载器不删用户密钥文件，安装说明里提示自行删除。构建运行时需要联网（python.org + PyPI），离线构建暂不支持。
- **边界遵守**：未改 `schemas.py`；未越界改 A、B 的文件（`recognizer.py` 只读未改）；未编造置信度或测试结果；pymupdf 的版本分叉写在 `requirements-app.txt` 的注释里并附了一致性实测，不是偷偷改的。
- **Git 状态**：代码提交 `b9fae78`（11 个文件），本条目与 README 的哈希更新为随后的文档提交；`dist/`、`.venv/`、`.cache/` 均被忽略，产物与下载缓存只在本机。本次不推送远端。
- **未完成事项**：干净机器（无 Python）上的首次启动实证；带界面安装向导的人工走查；离线构建（预先备好 wheel）；运行时体积进一步压缩（pymupdf 占 54 MB）；并行度压测与限流表现；10 页以上大批量；PDF 页与原图页的映射；整页转录真值集仍缺。

## 2026-11-25 用户实测反馈的两个真实缺陷：都复现、都修了、都加了回归

**阶段状态：用户把安装包解开逐项实测，反馈"整体质量不错，但有 2 个真实缺陷"。两条都在本机复现成功，已修复并重打重验。全量回归 185 项通过（新增 4 项打包文件名测试）。用户同时确认了一批功能实测可用（免装环境启动、网页工作台、真实 PDF 编译与中文/公式排版、Ctrl+S、编译复用、历史版本、错误定位到行、任务列表、C 层规范化、无密钥时 502 且不漏堆栈）。**

- **缺陷一：`Start-Process` 在"环境里有大小写重名变量"时直接崩**。用户报的是体检误报"随包 Python 运行时无法执行"，实际 `python.exe --version` 正常，根因是 `Start-Process` 抛 `ArgumentException：已添加项。字典中的关键字:"https_proxy" 所添加的关键字:"HTTPS_PROXY"`（代理软件常同时设 `HTTPS_PROXY` 与 `https_proxy`）。**本机复现**：在同时设置这两个变量的环境下，`Start-Process` 带重定向崩、**不带重定向也崩**，`Get-ChildItem Env:` 同样崩；而 `[Environment]::GetEnvironmentVariables()`、`.NET Process::Start`、`cmd /C` 重定向、直接 `&` 调用四种方式都正常。
- **影响比用户报的更严重**：`launch.ps1` 里 `Start-Process` 有三处用途——`Invoke-Captured`（所有体检探针）、开浏览器、**启动服务**。也就是说那种环境下工作台根本起不来，而脚本只会说"随包运行时无法执行/安装包不完整"，把人引到错误的排查方向。
- **修法（都按实测能活的方案改）**：① `Invoke-Captured` 改成 `& $exe @args 2>&1` 直接调用，临时把 `ErrorActionPreference` 放宽到 `Continue`（子进程写 stderr 是正常的，在 `Stop` 下会被当致命错误），用 `Push-Location`/`Pop-Location` 顶替 `-WorkingDirectory`，退出码取 `$LASTEXITCODE`；脚本顶部加 `[Console]::OutputEncoding = UTF8`，实测中文输出（`test_recognizer.py` 的 PASS 行）能正确捕获。② 服务进程改由 **WMI `Win32_Process Create`** 拉起一个 `cmd /S /C` 外壳，用 **cmd 的文件重定向**写日志：文件句柄由 python 自己继承，启动器退出后照常写；不用 `.NET RedirectStandardOutput`（那是管道，没人一直读就会写满把服务卡死）；用 WMI 而不是本地 `Process.Start` 是为了让进程彻底脱离控制台，否则外壳会继承启动器的输出句柄，调用方看着像"命令一直没结束"。③ cmd 只是外壳，**PID 文件必须记 python 那个进程**，所以按 `ParentProcessId` + 命令行含 `workbench.app` 认出真进程再写 PID，否则 `-Stop` 会杀错对象、把服务留下。④ 开浏览器改 `[System.Diagnostics.Process]::Start($Url)`，失败就如实提示手动复制地址。`launch_demo.ps1` 的三处同样处理。
- **缺陷一验证**：在 `HTTPS_PROXY` + `https_proxy` 同时存在的环境下，开发仓库与解压出来的安装包各跑一遍完整流程——体检（如实报"使用随包 Python 运行时…不建虚拟环境、不装依赖""依赖齐全，无需安装""workbench.app 可以被随包运行时导入"）、起服务（PID 文件里经 `Win32_Process` 核对确认是 `python.exe` 而非 `cmd.exe`，命令行就是 uvicorn）、日志落盘（`runtime\workbench.log.err` 里有 uvicorn 启动行）、`/api/status` 200、无头浏览器 `PACKAGE PAGE CHECK OK`、`-Stop` 后端口关闭且无残留 python/cmd 进程。启动器本身也 promptly 退出（返回码 0），不再挂住调用方。
- **缺陷二：zip 里的中文文件名**。**本机核实结果与用户描述有一处不同，如实记下**：用户说"`flag_bits & 0x800 == 0`"，但实测旧包（`Compress-Archive` 产出）的 7 个非 ASCII 条目**UTF-8 标志位是设了的**；真正的规范问题是**条目名用反斜杠分隔**（`Hand2LaTeX-1.0.0-win64\docs\assets\...`，zip 规范要求正斜杠），这是 .NET Framework 的老毛病。乱码本身来自**解压工具无视 UTF-8 标志位**：同一个新包，`Expand-Archive`（与 Windows 资源管理器同一套解析）解出来中文名与目录结构完全正确，Info-ZIP `unzip` 解出来是 `Õà¦Úù¡ÕÀÑõ¢£ÕŦ.bat`——**与用户报的字符串一模一样**，且这台 `unzip` 不支持 `-O UTF-8`（会打印帮助、解出 0 个文件）。
- **修法**：① 打包改用新脚本 `scripts/make_package_zip.py`（Python `zipfile`）：`as_posix()` 保证分隔符是 `/`，非 ASCII 名自动带 UTF-8 标志位；**打完当场核对**——条目名不含反斜杠、非 ASCII 条目都带标志位、`启动工作台.bat`/`关闭工作台.bat`/`安装说明.txt`/`start.bat`/`stop.bat`/`INSTALL.txt` 六个入口名必须原样存在，不通过就以非 0 退出、`package.ps1` 中止打包。② **加一层与解压工具无关的保险**：随包放 `start.bat`、`stop.bat`、`INSTALL.txt` 三个英文名同内容入口，`安装说明.txt` 开头写明"文件名是乱码就用这三个"，安装器的快捷方式也改指英文名（显示名仍是中文）。这样即便名字全乱，用户也还找得到启动脚本。
- **缺陷二验证**：合成用例（含中文目录与文件名）打包后核对通过；`Expand-Archive` 解出 5 个文件名与目录结构全对；`unzip` 仍然乱码（预期，已记录为工具限制并用英文名兜底）。最终真实包：5645 个条目、7 个非 ASCII 条目全带标志位、无反斜杠、六个入口名齐全；解压后中英文入口与 `runtime\` 都在。新增 `tests/test_packaging.py` 4 项锁住这些行为（含"反斜杠条目名与缺失入口必须被核对出来"——因为 Python 的 zipfile 在 Windows 上会自动规范化反斜杠、造不出真坏包，所以把核对逻辑拆成可直接喂数据的 `audit_names()` 再测）。
- **最终产物（提交 `f7e1c53`）**：`dist/Hand2LaTeX-1.0.0-win64.zip` 65 MB，SHA256 `954DD370B526DDD0EE7C0CE08058D42B13887BF3CA547EB579763C376BADDADE`；`dist/Hand2LaTeX-1.0.0-win64-setup.exe` 44.2 MB，SHA256 `65CB7575D470E84BA66D47687236437D9F5E2D8559CA9D2292AEAF76699AE55B`；随包运行时 111.5 MB。setup.exe 静默装机退出码 0，中英文入口与 `runtime\python\python.exe` 都在，开始菜单四个快捷方式的目标（`start.bat`/`stop.bat`/`INSTALL.txt`/`unins000.exe`）用 `WScript.Shell` 逐个解析并确认真实存在；静默卸载退出码 0，程序文件、整个 `runtime\`、`__pycache__`、开始菜单组、注册表项全清，`artifacts\jobs\keepme.txt` 保留。临时目录已删。
- **实际回归**：`./.venv/Scripts/python.exe -m unittest discover -s tests -q` 为 `Ran 185 tests`、`OK`。
- **证据边界**：`unzip` 的乱码是那个工具的行为，**没有修好它、也修不了**，只能用英文名入口兜底；带界面安装向导依旧没有人工点过；所有验证仍在本机（装了 Python 3.12 的开发机）上做，干净机器实证还欠着。用户反馈里"`flag_bits == 0`"这一句与本机实测不符，已如实记下差异而不是照抄。
- **并发情况（需要留意）**：本轮期间仓库里出现了不是本会话创建的改动——`docs/待办清单.md`（325 行，2026-11-25 08:48）与 `.gitignore` 新增 `.dsh-meow/`，看起来是另一个会话在按优化清单继续做。本会话**没有提交也没有修改**这两处；另外那份文档有一处事实错误：它称"`.venv/` 里检索 playwright 零命中"，实际存在 9 个 Playwright 脚本（`workbench_status_check.cjs`、`package_page_check.cjs` 等）。
- **边界遵守**：未改 `schemas.py`，未越界改 A、B 的文件，未编造测试结果；两处修复都先复现再改，改完都在真实产物上重验。
- **Git 状态**：代码提交 `f7e1c53`（7 个文件），本条目与 README 更新为随后的文档提交；`dist/`、`.venv/`、`.cache/` 均被忽略。本次不推送远端。
- **未完成事项**：干净机器（无 Python）实证；带界面安装向导人工走查；`unzip` 类工具的乱码只能靠英文名兜底，没有根治；离线构建；运行时瘦身（pymupdf 54 MB，网页链路其实用不到，可再省一半体积）；并行度压测与限流；PDF 页与原图页映射；整页转录真值集仍缺。

## 2026-11-26 第三方代码审计的 8 项：逐条核实，7 项成立并已修，1 项表述需修正

**阶段状态：收到一份外部审计（P0-1/2/3、P1-1~P1-5 共 8 项），按"确定缺陷才改"的原则逐条复核。核实结果：7 项成立、已修并加回归；1 项（P1-4）的实际形态与描述不同，已按真实情况处理。全量回归 244 项通过（原 234 + 新增 10），内核 8 个文件仍与基线逐字节一致。**

- **P1-1（成立，最该修的一条）：`BUILD_INFO.json` 被提交进了仓库，导致开发仓库的状态面板报假话。** 该文件本是打包产物（`source=安装包`、`commit=b9fae78`、`built_at=2026-11-25 07:47`），但它在 git 历史里，`workbench/app.py` 的 `_build_info()` 又只看"文件在不在"就返回 `source=安装包`。于是开发仓库的 `/api/status` 会显示一个早已不存在的提交号。**修法两层**：① `git rm --cached BUILD_INFO.json` + 写进 `.gitignore`（本地文件保留，打包还要用）；② 判据补严——有 `.git` 就是开发仓库（打包会排除 `.git`），此时一律以 `git rev-parse` 为准，**不看 BUILD_INFO.json**。第 ② 层是必要的：只做 ① 的话，刚打完包的机器上文件还在，照样报假。原来的 `test_build_info_reads_bom_prefixed_json` 因此失败（它没隔离 `.git`），改成把 `_PROJECT_ROOT` 也指到无 `.git` 的临时目录——它本来就是模拟安装包场景。
- **P0-1（成立）：画板启动器的端口探测退回了旧写法。** `scripts/launch_demo.ps1` 用 `TcpListener.Start()/Stop()` 判断端口，而 `scripts/launch.ps1` 早就换成了主动连接探测。两个启动器对同一个问题有两种写法，其中一个是我当初踩过坑后修好的，另一个漏改。已统一成主动连接（`TcpClient.BeginConnect` + 300 ms 超时）。
  - **如实记一处修正**：我在两个脚本原来的注释里都写了"`TcpListener.Start()` 在 Windows 上能被本进程成功绑到别人正在监听的端口上"。本轮实测**没能复现**——.NET 的 `TcpListener.ExclusiveAddressUse` 默认为 `False`，但在这个环境下对已被监听的端口仍会抛 `SocketException`。要误报得占用方自己也设了 `SO_REUSEADDR`。注释已改成准确表述（依赖 Windows 端口重用语义、条件性误报），不再断言"必定能绑成功"。
- **P0-2（成立）：`reasoning/TEAM_LOG.md` 缺 41 行。** 本地 885 行、`ca1228f` 里 926 行。缺的是两条完整历史记录：11-24「随包带 Python 运行时」与 11-25「用户实测反馈的两个缺陷」。按审计建议**从 `ca1228f` 原样取回、不重写**。验证方式：先 `diff` 确认前 885 行逐字节一致，再把尾部追加进去；追加后整文件与 `ca1228f` 版本逐字节一致。
- **P0-3（成立）：README 数字与实际不符。** 实测 `20` 个测试模块、`244` 项通过、`11` 跳过（原文写"14 个测试模块、180 项"）。按"数字写死必然再次过期"处理：测试命令的注释改成带日期标注的实测值；「合并后核对的四件事」与「55 个提交、538 个文件」都明确标成**合并当时的快照**，不再读成现状。另外把「内核 5 个文件」改成 8 个——`check_kernel.py` 实际校验 8 个文件，AGENTS.md 的清单也是 8 个。
- **P1-2（成立，而且比审计描述的更严重）：真实打包路径用的是没有校验的那个脚本。** `package.ps1:450` 调 `make_zip.py`（只压不验），而 `tests/test_packaging.py` 锁的是 `make_package_zip.py`（压完当场核对）。两边都"通过"，但真实打出来的 zip 从来没人核对文件名——**被测的从来不是被用的那个**。更深一层：`make_package_zip.py` 要求六个入口齐全（含 `start.bat`/`stop.bat`/`INSTALL.txt`），而这三个英文兜底文件在仓库和暂存目录里**都不存在**（`f7e1c53` 只改了 7 个文件，没创建它们），所以直接换脚本会让打包在 zip 阶段失败。**修法**：① `package.ps1` 真的把三个英文名从中文入口复制出来；② 暂存核对段补上这三个文件的检查；③ 换用 `make_package_zip.py` 并把它的 JSON 报告解析成人话；④ 删掉没有调用方的 `make_zip.py`（留着只会让人再调错）；⑤ 新增 `PackageScriptWiringTests`，锁住"package.ps1 必须调 make_package_zip.py、必须生成三个英文入口"。
- **P1-3（成立）：`push_via_api.py` 推不动二进制。** 第 142 行把内容按 utf-8 编码塞进 Git Blob API。仓库里有 **385 个含 NUL 的文件**（`data/page_math/*.png` 353 张、`artifacts/` 7、`docs/` 7、`samples/` 1），实测 `pm_001.png`（33,915 字节，首字节 `0x89`）抛 `UnicodeDecodeError`。此前只推过 README/AGENTS 这类文本，所以从未触发。**修法四处**：① 改 `encoding: base64`；② token 默认读 `GITHUB_TOKEN` 环境变量（argv 会留在 shell 历史与进程列表里）；③ `--force` 覆盖前要求输入 `yes` 确认；④ 新增 `--dry-run`。加 `tests/test_push_via_api.py` 6 项锁住这些判据（含用真实 png 验证 base64 可往返）。
- **P1-4（成立的根因，"已造重复历史"的描述需修正）：脚本不幂等，但形态与审计说的不同。** 审计称 `8038b9d` 与 `8e9dd00` 树相同、父提交不同；实测 `8e9dd00` **不在本仓库**，真实的一对是 `4616a7a`（本地）与 `8038b9d`（远端），两者 tree 都是 `cdbda02`——同一改动经 git 与 API 两条通道各留下一条记录，形成**两套平行历史**（同样 7 条提交信息，SHA 全不同），远端 `11bae7c` 与本地 `6c4d877` 树哈希相同（`4e91b5c`）。远端历史内部**没有空提交**（逐条比对树与父树，7 条都有实际改动）。**修法**：① 脚本加幂等闸门——先比对远端树的 blob sha 与本地，完全一致就直接返回 0，不建提交；② 比对时拒绝采信 GitHub 截断过的 tree（`truncated`）；③ 本地历史 `git reset --hard origin/hand2latex-review`，让双轨归一，修复改动叠在其上，不再产生第二条线。
- **P1-5（成立）：并发测试自己在锁外读文件。** `tests/test_workbench_app.py` 的 `worker()` 里 `read_text` 在 `with _job_write_lock(...)` 块**外面**，而 `_write_main_tex` 用 `write_text`（先截断再写）。锁本身没问题，问题在测试：它会撞上"截断后、写回前"的空文件，抖出一个与产品代码无关的假失败。连跑 5 次全绿只是抽样抽到了正面。修法就是把那一行读挪进 `with` 块，连跑 8 次仍全绿。
- **实际回归**：`runtime/python/python.exe -m unittest discover -s tests -q` 为 `Ran 244 tests`、`OK`（`skipped=11`）；`check_kernel.py` 8 个文件全部「一致」，基线来源仍是 git 提交 `992dd4e`。
- **证据边界**：`package.ps1` 的改动只做了语法检查与 `make_package_zip.py` 的独立实测（合成暂存目录，六入口齐全时退出码 0、缺一个时退出码 1），**没有真跑一次完整打包**（要下载/携带 126 MB 运行时，本轮没做）；`push_via_api.py` 的 base64 改动**没有真推一次含二进制的提交**（当前网络下 git 通道可用，且不宜为验证而制造远端提交），验证方式是用真实 png 做 base64 往返 + 断言请求体 encoding；`--force` 的交互确认只在代码层加了，没在真实远端演练"取消后引用未动"。
- **边界遵守**：未改 6 个内核路径中的任何一行（`check_kernel.py` 全绿可证）；未编造测试结果；对没能复现的 P0-1 现象如实记录，而不是照抄审计的说法。
- **Git 状态**：本轮修复将在随后的提交里入库；`BUILD_INFO.json` 已移出版本控制；`dist/`、`.venv/`、`.cache/` 仍被忽略。
- **未完成事项**：干净机器（无 Python）首次启动实证；带界面安装向导人工走查；`unzip` 类工具的乱码只能靠英文名兜底；离线构建；运行时瘦身；并行度压测与限流；PDF 页与原图页映射；整页转录真值集。

## 2026-11-26（续）推送环节暴露的第三个缺陷，以及双轨历史的清理

**阶段状态：拿到 token 后走 API 通道推送，第一次推「含删除的提交」当场崩了——这是脚本的第三个缺陷，修完重推成功。远端 538 个 blob 与本地逐一哈希零差异；干净克隆（`--depth 1`）跑全量 245 项全过。双轨历史已归一，`hand2latex-review` 与 `hand2latex-complete` 现在指向同一提交。**

- **第三个缺陷（本轮新发现）：`push_via_api.py` 处理不了删除。** `_changed_files` 用的是 `git diff --name-only`，只给路径、不给状态，于是删除的文件也被当成普通改动去 `git show HEAD:<path>` —— 该命令对已删除的文件**退出码 128**，整批推送直接崩。本次推送恰好第一次碰到删除（`BUILD_INFO.json`、`scripts/make_zip.py`），此前只推过新增与修改，所以一直没暴露。
- **还有一层更隐蔽的**：就算跳过删除的文件，树里也不会真的删掉它——`base_tree` 会把未提到的条目继承回来。Git Tree API 删除条目要**显式写 `{"sha": None}`**。原来那句注释"远端有但本地没有的（删除）也要带上"只 `print` 了一句提醒就 `return`，等于**从来没删过任何文件**。改成 `--name-status` 分流 + `sha: None` 后，两个删除都真正生效（远端 blob 数 540 → 538 已核对）。
- **幂等闸门实测有效**：推送成功后立刻再跑一次，输出「远端 hand2latex-review 的树与本地 87d4a7d5 完全一致（538 个文件），无需推送」直接退出，远端仍是 `6c97971`，**没有产生第二条提交**。这正是上一轮加的那个闸门在起作用。
- **P1-4 的纠正（上一轮我说错了一半）**：上一轮我写"`8e9dd00` 不在本仓库"。当时确实不在——它只在 `hand2latex-complete-2026-11-25` 分支上，而我没 fetch 到那条分支就下了结论。**审计的描述是对的**：`8038b9d`（review 分支）与 `8e9dd00`（complete 分支）**树同为 `cdbda02`、提交信息一字不差、父提交不同**，是货真价实的重复提交。根因是同一份改动经"本地 git"与"API 通道"两条路各留了一条记录。教训与上次那条一样：**"我这儿没有"不等于"从来不存在"，下结论前先把远端所有引用都拿全**。
- **双轨历史已归一**：`hand2latex-review`（默认分支）与 `hand2latex-complete-2026-11-25` 现在都指向 `6c979713`，本地 `HEAD` 也是它。complete 分支原本是另一条平行线（`ff0370b0`，树 `4e91b5c`），内容与被推的旧提交相同，直接指到同一提交，平行线消失。
- **干净克隆验证（最有说服力的一条）**：`git clone --depth 1 --branch hand2latex-review` 到临时目录后——
  - 538 个文件全下来；`BUILD_INFO.json` 与 `scripts/make_zip.py` **确实不在**（删除生效）；
  - 装 `requirements-app.txt` 依赖 + 补 `tools/tectonic/`（被 gitignore，本就该自己准备）后，全量 **245 项全过**；
  - `check_kernel.py` 在**没有 git 历史**的浅克隆里走兜底值，8 个文件仍全绿，输出明写「基线来源：脚本内置值」；
  - `_build_info()` 报 `source=开发仓库`、`commit=6c97971`、`built_at=None`——**P1-1 的修复在干净环境下确认生效**。
- **一处需要队友知道的执行细节**：随包运行时（embeddable Python）的 `python312._pth` 里写死了仓库根（`..\..`），且**有 `_pth` 时 PYTHONPATH 会被完全忽略**。所以在克隆目录里用随包 runtime 跑 `unittest discover`，会静默地跑回原仓库的测试文件（报错路径会露出 `h2l-work\tests\...`）。这不是仓库缺陷，但在别的目录验证时必须用标准 venv，否则验的是错的东西——我第一次就踩了，看到 11 个失败才反应过来。
- **实际回归**：原仓库 `245 passed / 11 skipped`；干净克隆 `245 passed / 20 skipped`（多出的 9 个全是缺可选依赖：torch 7、paddleocr 1、katex 4 —— 部分与本地重叠）。
- **证据边界**：API 推送通道的 base64 我只在**文本文件**上真推过（本次 14 个改动无二进制），"推二进制"仍只有单测层面的 base64 往返证据（用真实 `pm_001.png` 验证），**没有真推过一张图到远端**；`--force` 的交互确认仍未在真实远端演练；`setup.exe` 安装器本轮没编（只打了 `-NoPython` 瘦包，21 MB）。
- **边界遵守**：未改 6 个内核路径；未编造测试结果；上一轮的判断错误（`8e9dd00` 是否存在）已在上方明确纠正，没有悄悄改掉。

## 2026-11-26（再续）二进制推送已实证，push_via_api 的四个缺口补齐

**阶段状态：用临时分支实推了两个二进制文件并逐字节验回，证明 base64 那条路真的通；随后把脚本剩下四个缺口全部补上，每项都有测试与真实远端验证。**

- **二进制推送实证（此前只有单测证据）**：在临时分支 `test/binary-push` 上推了两个文件——`all_bytes.bin`（4096 字节，覆盖全部 256 种字节值、含 NUL）与 `real_pm_001.png`（33915 字节真实裁切图）。推完**从远端取回逐字节比对**，两个文件的 sha256 与本地完全相同（`c8f5d034…`、`b89aad38…`）。**这个证据比自校验更强**：自校验比的是 blob sha，取回比对比的是解出来的字节。
- **四个缺口（逐个补，都先确认存在再改）**：
  - **①建不了分支**：原来只有 `PATCH /git/refs/heads/<branch>`，对不存在的分支只会 422。改成先 `GET /git/ref/<branch>` 探测（`404` 当"不存在"这个正常答案，不混进重试），不存在时要求显式 `--create-branch`，再用 `POST /git/refs` 建。默认拒绝而不是自动建——打错分支名却"成功"建出一条新分支，比报错难查得多。
  - **②合并拓扑被压平**：`parents` 原来恒写成 `[base_sha]`。合并提交经这条路推上去会变成单亲，历史形状就错了。改成 `rev-list --reverse base..head` 取提交链**逐提交重放**，父提交从 commit 对象本体读，链内父提交映射成新建的 sha、链外原样保留；顺带把 committer 也带上（原来只设 author，提交者会是错的）。
  - **③base 过期会静默吃掉别人的提交**：在过期 base 上建树，别人新推的文件会被当成"删除"抹掉。现在先查远端分支当前指向，与 `--base` 不一致就**停下来说清楚**（要覆盖得显式 `--force`）；再用 `merge-base --is-ancestor` 校验 head 确实是 base 的后代。
  - **④推完自说自话**：新增**推后自校验**——重新拉远端树与本地逐 blob 比对，不一致返回 4 并打出「仅远端有 / 仅本地有 / 内容不同」三类差异。
  - 另补 `--delete-branch`（`DELETE` 后复查 404 才算真删）。
- **又踩一个坑并修掉**：`_commit_meta` 里原本用 `str(raw)` 解析 `cat-file commit` 的输出。但 `raw` 是 **bytes**，`str(bytes)` 得到的是 `"b'tree ...'"` 这种字面量，行首变成 `b'parent`，`startswith("parent ")` **永远匹配不到**——于是每个提交都被当成无父提交，多父支持等于没做。改成 `.decode()` 后正常；用真实合并提交 `5bdd02b` 验出 2 个父提交，并加了测试锁住（含"用 `str(bytes)` 会失效"这条注释说明）。
- **实测记录（都在远端真仓库上做）**：
  - 新建分支推二进制：自校验「540 个 blob 与本地逐一一致」，取回逐字节比对 sha256 相同；
  - 删除该分支：删后复查返回 404；远端 5 个分支 `hand2latex-review`/`complete`/`mvp`/`workbench`/`wonhoyeon123-test` 均未受影响；
  - 全量回归 **253 项通过**（原 245 + 新增 8）。
- **一处遗留（如实记）**：最终那次推送到 `hand2latex-review` 后，`github.com:443` 又开始 502，本地 fetch 不回那个 API 创建的提交，所以本地 `HEAD` 停在 `f1cb06b`、远端停在 `3ee41768`。**两者树哈希完全相同**（`cf1061f6`），内容一致，只是提交对象不同；等通道恢复一次 `git fetch` 就能对齐。我试过用 API 数据手工重建提交对象让 git 认识它，但重算的 sha 对不上（`d7007594` vs `3ee41768`，时间格式细节不同），这条路不可靠，没继续。
- **证据边界**：`--force` 的交互确认与 `--delete-branch` 的确认都在真实远端走过（管道喂 `yes`）；但「base 过期时被拦住」这条只做了代码与测试层面的确认，**没有真的制造一次并发推送去撞它**；多父重放只验证了"能读出 2 个父提交"，**没有真推一个合并提交到远端**看拓扑。
- **边界遵守**：未改 6 个内核路径；临时分支与测试文件已全部清理（远端分支删净、本地 `git branch -D`、`tests/fixtures_binary_push/` 已删），工作区干净。

## 2026-11-26（历雨飞）更正一条时间线，并记本轮三件事

**阶段状态：`hand2latex-complete-2026-11-25` 已快进到 `9df62c5`、与默认分支对齐；任务列表分页测试改成每次运行唯一的标记，污染环境下修复前 `6 != 2`、修复后 OK，全量 255 项通过；`AGENTS.md` 里"502 与代理无关"改成两种成因都写。另有一条日志的时间线需要更正。**

- **要更正的一条**：`docs/verify-teammate-questions`（`2ec8b67`）里的条目标题写"两条都已在远端解决，但他给的是旧状态"。时间线不是这样：我给用户那份清单时，默认分支确实是 `753797d`（当时用 API 查过），清单写的是"启动器修复需要合进默认分支、4.1 约定要用户定"；用户随后明确指示"1 进默认分支、2 改成只推自己的分支"，我才推了 `2d8b321`（`6362a12` 的 cherry-pick，树同为 `3d1e1ed8`、父提交同为 `753797d`）和 `9df62c5`。所以那是"清单给出的时刻还没做"，不是"给了过期信息"——解决动作本身就是那次推送。两边的观察都对，只是先后不同。
- **那两次直接推默认分支**：都是在用户明确指示下做的，提交说明里写明是旧约定下的最后一次。此后按 `9df62c5` 的新约定，改动一律先落自己的分支，本轮三件事都是这么推的。
- **`hand2latex-complete-2026-11-25` 快进**：`753797d → 9df62c5`，纯快进、不改历史。按新约定它只由维护者更新，这次是用户点头后由我执行。
- **测试加固（`fix/job-list-test-isolation` 的 `b2be235`）**：根因比"清理不原子"更具体——测试用固定标题"分页验收A/B"造夹具，再用 `q=分页验收` 搜索，残留夹具标题相同，所以 total 被抬高。我本机 `artifacts/jobs` 有 141 个任务目录而测试照样过，就因为它们标题里没有这个词。只加固清理治不了本（被打断一次就永久留垃圾）；改法是标题带每次运行唯一的标记、查询搜这个标记，测试与被污染的环境彻底解耦，断言未动。**实证**：故意造 4 个旧标题残留夹具，修复前 `AssertionError: 6 != 2`，修复后 OK；全量 `Ran 255 tests, OK (skipped=4)`。
- **`AGENTS.md` 更正（`8b7e377`）**：原文"502 与代理无关，是上游偶发故障"站不住。袁昊然那台是走代理 000、绕过代理 200；我这台根本没有 proxy 变量，失败纯粹是通路间歇断开（不清理任何东西，`ls-remote` 一次就通）。两种成因都真实存在，改成两种都写，探测块补 `curl --noproxy '*'`，并说明绕过代理能通时只在子进程里 `env -u` 清变量、不改本机配置。
- **证据边界**：那两个远端实验（并发推送撞"base 过期被拦"、推合并提交看多父拓扑）**本轮没做**——`push_via_api.py` 需要 `GITHUB_TOKEN`，我这边没有，也不去读凭据管理器里存的密钥。`docs/verify-teammate-questions` 那条分支未动。
- **合并提示**：本条追加在 `TEAM_LOG.md` 末尾，与 `2ec8b67` 那条位置相同；两条都进默认分支时末尾会冲突，两条都保留即可。
