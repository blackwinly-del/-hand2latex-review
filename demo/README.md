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

## 文件

- `app.py`：Streamlit 主程序
- `requirements-demo.txt`：demo 额外依赖
