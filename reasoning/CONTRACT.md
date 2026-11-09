# Hand2LaTeX C 模块公共契约（讨论稿）

- 版本：v0.2
- 日期：2026-11-03
- 状态：供 A/B/C 三人讨论，尚未共同冻结
- 对应实现：`reasoner.py`、`reasoning/context.py`、`reasoning/render_check.py`

第 1—12 节只描述当前已经实现的行为，不新增公共字段，也不替代三人共同确认公共契约文件的流程。第 13—15 节是 v0.2 新增的未实现讨论提案，在冻结前不构成公共字段、接口或现有 `refine` 行为变更。任何字段新增、删除、重命名或语义变化都必须先讨论并确认。

## 1. 核心原则

1. 目标是忠实转录手写公式，不是求解、化简或纠正数学内容。
2. 保留原始候选，不修改调用方传入的候选列表。
3. 多模态模型只能从已有候选中选择，不能自由生成新公式。
4. `confidence` 是规则等级，不是经过校准的正确率。
5. 忠实转录、结构检查和 KaTeX 可渲染性是不同维度，必须分别判断。
6. 当前 MLP 未接入生产流程，`risk_score` 固定为 `None`。

## 2. 生产入口 `refine`

```python
def refine(image_path: str, candidates: list[dict]) -> dict:
    ...
```

### 2.1 `image_path`

- 调用方必须提供本地图片路径字符串。
- 候选冲突时会读取图片并发送给已配置的多模态服务。
- 支持 `.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`，扩展名用于确定 MIME 类型。
- 无候选冲突时当前实现不会读取图片，但调用方不得依赖这一点传入无效路径。
- 图片会离开本地环境并发送给所配置的第三方服务，调用方必须确保允许该数据处理。

### 2.2 `candidates`

输入必须是 `list[dict]`。公共候选格式如下：

```json
{
  "engine": "pp_formulanet_l",
  "latex": "\\frac{x^2}{2}",
  "score": null,
  "latency_ms": 0,
  "error": null
}
```

| 字段 | 类型 | 含义与约束 |
| --- | --- | --- |
| `engine` | `str` | 识别引擎标识，用于跨引擎一致性判断。 |
| `latex` | `str` | 候选 LaTeX，必须存在且为字符串；纯空白候选不参与后续选择。 |
| `score` | `number \| null` | 识别器真实分数；没有真实分数时必须为 `null`。C 不使用它排序或编造置信度。 |
| `latency_ms` | `number` | 识别延迟，C 不用于候选选择。 |
| `error` | `str \| null` | 识别错误；非 `null` 的候选不参与 `refine` 后续选择。 |

上述类型是**调用方前置约束**，不代表 C 已对全部字段实施完整运行时校验。当前实现只明确校验候选容器、字典元素和 `latex`；`engine`、`score`、`latency_ms`、`error` 的缺失或类型越约行为不属于兼容保证，可能按缺省处理、被跳过或产生异常，调用方不得依赖。是否统一拒绝所有越约字段，留待三人冻结契约时决定。

C 的实际处理规则：

- 仅对 LaTeX 执行 `strip()` 首尾空白清理，不折叠内部空白。
- 按清理后的完整字符串去重，保留首个原始候选字典。
- 跳过纯空白候选和 `error != None` 的候选。
- 不做数学化简、自动补全或基于出现频率的多数投票。

## 3. `refine` 返回结构

```json
{
  "raw_latex": "...",
  "final_latex": "...",
  "confidence": "high | medium | low",
  "changes": [],
  "need_review": false,
  "risk_score": null
}
```

| 字段 | 类型 | 准确含义 |
| --- | --- | --- |
| `raw_latex` | `str` | 当前选中候选的原始 LaTeX，未执行首尾清理。若上下文改选其他候选，它不等于去重后的首个候选。 |
| `final_latex` | `str` | 对 `raw_latex` 仅执行 `strip()` 后的结果。 |
| `confidence` | `str` | `high`、`medium` 或 `low`，由规则得到，不是概率。 |
| `changes` | `list[dict]` | 实际发生的候选切换和首尾空白清理；没有实际修改时为空列表。 |
| `need_review` | `bool` | 是否必须人工复核。结构异常或上下文选择失败时为 `true`。 |
| `risk_score` | `null` | MLP 尚未接入，当前始终为 `null`。 |

`raw_latex` 为空字符串表示没有可用候选，不代表识别出了空公式。

## 4. `changes` 记录格式

### 4.1 上下文改选候选

仅在实际选择了非首个去重候选时记录：

```json
{
  "rule": "context_candidate_selection",
  "before": "x+1",
  "after": "x-1",
  "selected_index": 1,
  "reason": "选择该候选的理由"
}
```

- `selected_index` 是从 0 开始的候选索引。
- `before` 是去重后首个候选的原始 LaTeX。
- `after` 是上下文选中候选的原始 LaTeX。
- 选择首个候选时不记录候选切换。

### 4.2 清理首尾空白

仅在实际发生变化时记录：

```json
{
  "rule": "trim_outer_whitespace",
  "before": " x-1 ",
  "after": "x-1"
}
```

如果上下文改选和空白清理同时发生，分别记录两条 `changes`。

## 5. 决策与复核规则

| 情况 | 选择结果 | `confidence` | `need_review` |
| --- | --- | --- | --- |
| 没有有效候选 | 空字符串 | `low` | `true` |
| 无冲突、结构正常、仅一个引擎支持 | 首个有效候选 | `medium` | `false` |
| 无冲突、结构正常、多个不同引擎支持同一结果 | 首个有效候选 | `high` | `false` |
| 候选冲突，上下文成功选择，所有候选结构正常 | 被索引选中的候选 | `medium` | `false` |
| 候选冲突，上下文失败或响应非法 | 首个有效候选 | `low` | `true` |
| 任一有效候选存在结构异常 | 按上下文结果选择，但保留复核 | `low` | `true` |

重要边界：

- 同一引擎的重复候选不会单独产生 `high`。
- 上下文选择成功不会把冲突结果直接提升为 `high`。
- 被选候选结构正常，不代表识别一定正确；其他候选的结构异常仍会触发复核。
- 忠实但结构不完整的公式仍应保留原文，同时请求复核。

## 6. 输入错误与异常

### 6.1 候选结构错误

当前实现会明确抛出：

- `candidates` 不是列表：`TypeError`。
- 候选元素不是字典：`TypeError`。
- 候选缺少 `latex` 字段：`ValueError`。
- `latex` 不是字符串：`TypeError`。

空列表、全部空白或全部失败的候选不抛出异常，而是返回空 LaTeX、`low` 和 `need_review=true`。

### 6.2 上下文服务错误

API 超时、网络错误、配置错误、无效 JSON、空理由、非法索引等不会生成新公式，也不会被静默当作成功。`refine` 会保留首个有效候选，并返回 `low + need_review=true`。

## 7. 上下文选择接口 `choose_with_context`

这是 C 的候选选择辅助接口，调用方通常应优先使用 `refine`，而不是自行组合返回结果。

```python
def choose_with_context(image_path: str, candidates: list[dict]) -> dict:
    ...
```

成功返回：

```json
{
  "selected_index": 1,
  "reason": "选择理由",
  "error": null
}
```

失败返回：

```json
{
  "selected_index": null,
  "reason": "",
  "error": "安全的错误摘要"
}
```

约束：

- 至少需要两个候选。
- 每个候选必须包含非空白 `latex`，且 `error=None`。
- 只接受范围内、非布尔的整数索引。
- 拒绝负数、浮点数、数字字符串、布尔值和越界索引。
- `reason` 必须是非空白字符串。
- 输入校验错误在请求前抛出 `TypeError` 或 `ValueError`；服务和响应错误通过上述失败结构返回。
- 普通服务异常只返回异常类型和固定说明，不直接公开完整响应体或密钥。

### 7.1 配置

通过项目根目录的本地 `.env` 或已有系统环境变量配置，已有系统环境变量优先：

| 环境变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | API 密钥，不得写入代码、日志或 Git。 |
| `OPENAI_MODEL` | 是 | 必须支持图片输入；JSON mode 支持取决于服务。 |
| `OPENAI_BASE_URL` | 否 | OpenAI 兼容 API 根地址；留空使用 SDK 默认值。 |
| `OPENAI_TIMEOUT_SECONDS` | 否 | 默认 `30`，必须是正有限数。 |

“OpenAI 兼容”不保证每个服务都支持视觉输入或 `response_format=json_object`，兼容失败必须走人工复核回退。

## 8. KaTeX 辅助接口 `check_renderable`

```python
def check_renderable(latex: str) -> dict:
    ...
```

成功检查结果：

```json
{"renderable": true, "error": null}
```

公式解析失败：

```json
{"renderable": false, "error": "KaTeX ParseError 信息"}
```

- 该接口不修改 LaTeX。
- Node.js 缺失、超时、检查器内部异常或无效协议输出会抛出 `RuntimeError`，不会误记为公式不可渲染。
- `refine` 本身不调用该接口，渲染结果不包含在当前 `refine` 返回结构中。
- `renderable=true` 不代表结构正常、数学正确或忠实转录。

## 9. 调用示例

### 9.1 单个有效候选

输入：

```python
refine("formula.png", [
    {
        "engine": "pp_formulanet_l",
        "latex": " x^2 ",
        "score": None,
        "latency_ms": 100,
        "error": None,
    }
])
```

返回：

```json
{
  "raw_latex": " x^2 ",
  "final_latex": "x^2",
  "confidence": "medium",
  "changes": [
    {
      "rule": "trim_outer_whitespace",
      "before": " x^2 ",
      "after": "x^2"
    }
  ],
  "need_review": false,
  "risk_score": null
}
```

### 9.2 空候选

```json
{
  "raw_latex": "",
  "final_latex": "",
  "confidence": "low",
  "changes": [],
  "need_review": true,
  "risk_score": null
}
```

## 10. 当前明确不支持或尚未证明的能力

- 中文与公式混排的可靠识别。
- 自动求解、数学纠错或缺乏依据的等价化简。
- 生产级 MLP 风险评分。
- 总体识别准确率、跨字迹泛化或上下文选择稳定性保证。
- 手写笔记风字体属于独立展示功能，不改变本契约中的 LaTeX。

## 11. 契约变更流程

以下内容不得由任何开发者或辅助 Agent 单方面修改：

- `refine` 和候选输入输出字段。
- `confidence`、`need_review`、`raw_latex` 的语义。
- `changes` 的记录规则。
- 异常、空候选、冲突和 API 失败回退行为。
- 上下文模型能否生成或改写 LaTeX 的边界。

变更前必须：

1. 由 A/B/C 讨论并确认兼容性和迁移方式。
2. 同步更新公共契约、实现和最小测试。
3. 分别验证正常、空输入、异常输入、冲突和失败回退。
4. 记录真实测试证据，不把讨论稿当作已冻结协议。

## 12. 三人仍需讨论的事项

- 多真实候选由何种识别流程提供，以及候选顺序是否稳定。
- 用户编辑、人工确认和反馈保存的数据格式；该格式不在当前 `refine` 契约内。
- 页面如何分别展示忠实结果、结构复核和渲染状态。
- 何时将本讨论稿正式冻结为三人共同认可的版本。

## 13. 新增提案：片段级错误定位（未实现）

> 本节是 v0.2 新增讨论提案，不是当前 `refine` 返回字段，也不代表已经实现错误定位。是否引入独立辅助接口或可选字段，需三人另行确认。

### 13.1 目标与分阶段方向

目标不仅是返回整式 LaTeX 和整体复核状态，还要指出“哪里可能有问题”。

建议按以下顺序实施：

1. **LaTeX 预览定位**：先利用候选差异和确定性结构检查定位具体子串。
2. **上下文理由关联**：仅当模型明确提供可验证的片段证据时，才关联到对应子串；不得根据整式理由猜测片段置信度。
3. **原始笔迹叠加**：后续只有获得可靠的图片坐标与 LaTeX 片段映射后，才在原图上叠加标注。

当前没有原图坐标或片段级数值置信度，不能伪造这类数据。

### 13.2 提议的 `IssueSpan` 数据形态

以下为讨论示例，不是现有返回结构：

```json
{
  "span_id": "final:12-13:1",
  "source_revision": 3,
  "target": "final_latex",
  "start": 12,
  "end": 13,
  "text": "1",
  "source": "candidate_difference",
  "issue_type": "conflicting_fragment",
  "severity": "review",
  "message": "另一候选在此处为 4"
}
```

| 字段 | 提议含义 |
| --- | --- |
| `span_id` | 当前结果和版本内唯一的片段标识，不得跨版本复用。 |
| `source_revision` | 片段所属结果版本，局部修正时用于核对当前版本。 |
| `target` | 目标标识，例如 `final_latex` 或 `candidate:<index>`。目标文本由当前结果版本根据该标识解析，不是把标识本身当作字符串切片。 |
| `start` | 片段起始位置，包含该位置；必须是非布尔整数，并使用目标文本的 Python 字符串索引。 |
| `end` | 片段结束位置，不包含该位置；必须是非布尔整数。 |
| `text` | 目标文本在 `[start:end]` 的精确子串，用于校验锚点。 |
| `source` | 证据来源，例如 `candidate_difference`、`structure_rule` 或经过验证的 `context_reason`。 |
| `issue_type` | 问题类型，例如候选差异、括号异常或上下标异常。 |
| `severity` | 展示级别，例如 `info`、`warning`、`review`；不是数值正确率。 |
| `message` | 面向用户的具体说明，不应只重复整体置信等级。 |

索引规则：

- `start` 包含、`end` 不包含，与 Python 切片一致，并统一满足 `0 <= start < end <= len(目标文本)`，不能依赖 Python 对负索引或越界切片的自动处理。
- `text == 目标文本[start:end]` 必须始终成立。
- `final_latex` 对应当前编辑版本中的最终字符串；`candidate:<index>` 对应当前 `refine` 去重后候选列表中该索引候选的原始 `latex`，不使用清理后的副本。`<index>` 必须是非布尔整数，并满足 `0 <= index < len(当前 refine 去重后候选列表)`，不满足时目标无效并拒绝解析。
- 索引对应解析后的确切目标文本，不能在 `raw_latex` 与 `final_latex` 之间混用。
- 任何实际编辑或替换使旧片段和旧索引失效，必须重新计算；无实际变化或被拒绝的请求不产生新版本，旧锚点继续有效。

### 13.3 原图标注的后续扩展

若未来支持原图叠加，可讨论增加 `image_region`，至少包含原图坐标系、图片宽高以及 `x/y/width/height`。`image_region` 必须关联到某个 `span_id`，但不能用 LaTeX 字符位置反推手写图片位置。区域相对所记录的原图必须满足 `x >= 0`、`y >= 0`、`width > 0`、`height > 0`、`x + width <= 图片宽度`、`y + height <= 图片高度`。展示缩放只转换显示坐标，不修改保存的原图坐标。

在获得识别器或独立布局模型提供的真实区域前，优先实现 LaTeX 预览中的颜色、下划线等展示能力。

## 14. 新增提案：用户驱动的局部修正（未实现）

> 本节同样是讨论提案。当前 C 不支持圈选、局部重写或局部 LaTeX 替换，以下规则用于防止未来实现演变为全文重写。

### 14.1 目标与边界

- 用户指定需要修正的片段，C 只替换对应子串。
- C 不根据用户选择自行猜测或生成修正结果。
- 重新手写片段、圈选和图片交互属于输入来源；进入 C 的修正请求仍必须包含明确的替换文本。
- 局部修正只能作用于未来独立、带版本编辑结果中的 `final_latex`，不能修改候选或 `raw_latex`，也不能回写当前 `refine` 返回对象。当前 `refine` 的 `final_latex == raw_latex.strip()` 和既有 `changes` 规则保持不变。
- 原始 OCR 候选和 `raw_latex` 作为历史证据保留，新的编辑版本单独保存最终文本和新增修改记录。

### 14.2 提议的修正请求

```json
{
  "span_id": "final:12-13:1",
  "source_revision": 3,
  "target": "final_latex",
  "start": 12,
  "end": 13,
  "expected_text": "1",
  "replacement": "4",
  "reason": "user_correction"
}
```

| 字段 | 提议含义 |
| --- | --- |
| `span_id` | 用户选择的片段标识。 |
| `source_revision` | 片段所属结果版本，防止编辑后继续使用旧位置。 |
| `target` | 局部修正只允许为 `final_latex`；实际目标文本由当前编辑版本解析，不能修改候选或 `raw_latex`。 |
| `start`、`end` | 与定位阶段一致的 Python 切片位置。 |
| `expected_text` | 用户选择时看到的原始子串。 |
| `replacement` | 用户确认的新子串，C 不进行数学化简或自动补全。 |
| `reason` | 修改来源，当前建议为用户修正而非模型自动重写。 |

### 14.3 替换前必须满足的安全条件

1. 先按 `span_id` 取得当前编辑版本签发的原始 `IssueSpan`，并强制满足 `请求.source_revision == 已签发 IssueSpan.source_revision == 当前编辑版本`；任一方不一致都拒绝替换且不推进版本，不能只检查请求里存在同名字段。
2. 请求中的 `target/start/end/expected_text` 必须与已签发片段的 `target/start/end/text` 完全一致，防止用有效 `span_id` 搭配另一处坐标。
3. `target` 只能是 `final_latex`，由当前编辑版本解析出实际目标文本；`start`、`end` 必须是非布尔整数，并满足 `0 <= start < end <= len(目标文本)`。
4. `目标文本[start:end] == expected_text` 必须成立，否则拒绝替换并报告片段已失效。
5. 只能对目标文本执行一次精确切片替换：`目标文本[:start] + replacement + 目标文本[end:]`。
6. `replacement` 必须是字符串；不得借此替换整条公式，除非用户明确选择全文编辑而非局部修正。
7. 若替换文本与原片段相同，不产生实际修改、修改记录或新版本，旧锚点继续有效；被拒绝的请求同样不推进版本。
8. 只有实际内容变化才产生新的编辑版本和修改记录；此时旧 `span_id` 和旧 `source_revision` 失效，后续修正必须基于新版本重新定位。
9. 替换后重新执行结构检查和渲染检查，但不把检查通过等同于识别正确。

这些规则用于处理重复符号、连续编辑和用户界面旧状态，避免“看起来只改了一处，实际替换了另一处”。

### 14.4 提议的修改记录

以下示例属于未来的独立、带版本编辑结果，不回写当前 `refine` 返回对象，也不改变其既有字段不变量：

```json
{
  "rule": "local_span_replacement",
  "span_id": "final:12-13:1",
  "source_revision": 3,
  "start": 12,
  "end": 13,
  "before": "1",
  "after": "4",
  "reason": "user_correction"
}
```

`local_span_replacement` 目前只是提议的新 `changes.rule`，未加入现有实现。它不能覆盖或删除此前的 `context_candidate_selection`、`trim_outer_whitespace` 等历史记录。

## 15. 定位与修正提案的待定事项

三人实现前仍需共同决定：

1. 片段定位使用独立辅助接口，还是在 `refine` 中增加可选 `issues` 字段。
2. `severity` 与现有 `confidence`、`need_review` 的映射，禁止编造片段级概率。
3. 候选差异、结构规则和上下文理由分别允许定位到哪些证据。
4. 原图坐标从何处获得，以及图片缩放后如何保持坐标一致。
5. `source_revision` 的生成、保存和校验方式，以及用户连续编辑时的版本管理。
6. 用户修正后是否需要重新执行候选选择；默认建议只做结构／渲染复核，不重新触发整式重写。
7. 最小测试必须覆盖重复子串、失效版本、越界索引、空替换、无实际变化、Unicode 索引和连续局部修正。

在上述事项冻结前，当前 `refine` 输入输出和异常行为保持不变。
