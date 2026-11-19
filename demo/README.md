# 画板 + 动态手写公式识别 Demo

「杀手锏」功能：用鼠标在画板上写一个公式（如 `F = ma`），停笔约 1 秒，右侧自动识别并排版成 LaTeX——**全程无需点上传 / 识别按钮**。

## 快速开始

```bash
# 1. 安装依赖（在已有 venv 里，requirements.txt 已装过基础依赖）
./.venv/Scripts/python.exe -m pip install -r demo/requirements-demo.txt

# 2. （可选）真实识别：再装 B 层引擎依赖
./.venv/Scripts/python.exe -m pip install -r requirements-b.txt

# 3. 启动
./.venv/Scripts/python.exe -m streamlit run demo/app.py
```

浏览器会自动打开 `http://localhost:8501`。

## 两种运行模式

| 模式 | 环境变量 | 说明 |
| --- | --- | --- |
| **真实识别**（默认） | 不设 `RECOGNIZER_BACKEND` | 用 PP-FormulaNet-L 真模型，首次加载需几十秒，需装 `requirements-b.txt` |
| **仅联调** | `RECOGNIZER_BACKEND=mock` | 跳过模型，跑通「画板 → 停笔 → 识别 → 渲染」完整交互，结果只是占位 |

仅联调（Windows）：

```powershell
$env:RECOGNIZER_BACKEND = "mock"
./.venv/Scripts/python.exe -m streamlit run demo/app.py
```

## 调用链

```
st_canvas 画板
   └─ 停笔 1 秒（指纹不变）触发
        └─ recognizer.recognize(path)     B 层：图片 → LaTeX 候选列表
             └─ reasoner.refine(path, c)  C 层：去重 / 规范化 / 结构检查
                  └─ st.latex(latex)      渲染（KaTeX）
```

## 关键实现点

- **停笔判定**：对 `st_canvas` 返回的 `json_data["objects"]` 做内容指纹（哈希），
  指纹保持不变满 `_IDLE_SECONDS`（默认 1.0s）才触发识别；同一指纹只识别一次，
  避免 Streamlit 每次 rerun 都重复调模型。
- **模型缓存**：`recognizer.get_model` 进程内缓存 + `@st.cache_resource` 双重缓存，
  避免 Streamlit 每次交互都重建模型。
- **图像预处理**：画布 RGBA → 白底 RGB PNG，再交给 B 层（手写识别对白底黑字最友好）。
- **不破坏契约**：demo 只调用 B / C 层的公开函数 `recognize` / `refine`，
  不 import A 的 FastAPI / Vue 代码，不触碰 `schemas.py`。

## 识别速度优化

CPU 上 `PP-FormulaNet-L` 单张要 6~8 秒，demo 做了三层提速：

1. **裁到笔迹包围盒**（`_crop_to_ink`）：画布 720×320，用户写的公式往往只占中间一小块。
   识别前按笔迹范围裁剪并留 24px 边距，实测一笔中等长度的公式从 230,400 像素降到
   约 13,800 像素（**6%**），模型输入面积减少 94%。
2. **模型档位可切换**：侧边栏「快速」档用 `PP-FormulaNet-S`（体积约为 L 的 1/5，
   CPU 上快数倍），适合演示和反复试写；「精准」档用 `-L`。两档模型各自缓存，
   切换不会反复重建。
3. **结果缓存**：`(画布指纹, 模型档位) → 结果`。擦掉重画回原样、或切档位再切回来，
   直接命中缓存不再推理。

界面上会显示**识别耗时**，方便对比两档差异。

进一步提速的可选做法（未实现）：

- 有 NVIDIA 显卡时把 `RECOGNIZER_DEVICE` 设为 `gpu:0`，提速最明显。
- 调小 `_CANVAS_WIDTH` / `_CANVAS_HEIGHT`，从源头减少像素量。
- 用 `PP-FormulaNet-S` 演示、正式评测再换 `-L`。

## 文件

- `app.py`：Streamlit 主程序
- `requirements-demo.txt`：demo 额外依赖
