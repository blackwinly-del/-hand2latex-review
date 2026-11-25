"""本地风险模型（RiskMLP）的结构与推理测试。

**这组测试需要 torch，而 torch 是可选依赖。**
`requirements-app.txt`（随包运行的 Python 装的就是这一份）故意不装 torch：
`package.ps1` 会把 `runtime/python` 整个复制进交付包，装上 torch 会让包从
57 MB 涨到几百 MB，而 torch 只被 `reasoning/risk_mlp.py`、`reasoning/train_risk.py`
和 `recognizer.py` 用到，这三处都不在「上传 → 整页识别 → 编译 → 复核」主链路上，
且在 `recognizer.py` 里是函数内延迟导入。

**为什么不能只给测试方法加 `@skipUnless`**：`reasoning/risk_mlp.py` 第 1 行就是
`import torch`，那是个内核文件（`AGENTS.md` 清单内），不能为了测试把它改成延迟导入。
所以只要本文件执行到 `from reasoning.risk_mlp import RiskMLP`，模块加载阶段就会抛
`ModuleNotFoundError`，unittest 把它记成 **ERROR（红）**——看起来像代码坏了，
其实只是"这台机器没装可选依赖"。

也不能在模块级 `raise unittest.SkipTest(...)`：unittest 的 loader 会把模块级异常
一律记成 ERROR，而不是 skip。所以这里用 try/except 把导入包起来，让模块**正常加载**，
再在测试类上用 skipUnless 表达"跳过"。
"""

import importlib.util
import unittest

_HAS_TORCH = importlib.util.find_spec("torch") is not None

if _HAS_TORCH:
    import torch
    from torch import nn

    from reasoning.risk_mlp import RiskMLP


@unittest.skipUnless(_HAS_TORCH, "torch 未安装（requirements.txt，本地风险模型支线），跳过")
class RiskMLPTests(unittest.TestCase):
    def test_architecture_is_8_16_8_1_with_relu_hidden_layers(self):
        model = RiskMLP()

        linear_layers = [layer for layer in model.network if isinstance(layer, nn.Linear)]
        relu_layers = [layer for layer in model.network if isinstance(layer, nn.ReLU)]

        self.assertEqual(
            [(layer.in_features, layer.out_features) for layer in linear_layers],
            [(8, 16), (16, 8), (8, 1)],
        )
        self.assertEqual(len(relu_layers), 2)
        self.assertEqual(
            [type(layer) for layer in model.network],
            [nn.Linear, nn.ReLU, nn.Linear, nn.ReLU, nn.Linear],
        )

    def test_forward_returns_one_logit_per_sample(self):
        model = RiskMLP()

        logits = model(torch.zeros(3, 8))

        self.assertEqual(logits.shape, (3, 1))

    def test_forward_does_not_apply_sigmoid(self):
        model = RiskMLP()
        with torch.no_grad():
            for parameter in model.parameters():
                parameter.fill_(1.0)
        features = torch.ones(1, 8)

        logits = model(features)
        risk_score = model.risk_score(features)

        self.assertGreater(logits.item(), 1.0)
        self.assertTrue(torch.allclose(risk_score, torch.sigmoid(logits)))
        self.assertTrue(torch.all((risk_score >= 0) & (risk_score <= 1)))

    def test_zero_logit_displays_as_point_five_without_probability_claim(self):
        model = RiskMLP()
        with torch.no_grad():
            for parameter in model.parameters():
                parameter.zero_()

        logits = model(torch.ones(1, 8))
        risk_score = model.risk_score(torch.ones(1, 8))

        self.assertEqual(logits.item(), 0.0)
        self.assertEqual(risk_score.item(), 0.5)

    def test_risk_score_display_does_not_build_gradient_graph(self):
        model = RiskMLP()

        risk_score = model.risk_score(torch.ones(1, 8))

        self.assertFalse(risk_score.requires_grad)


if __name__ == "__main__":
    unittest.main()
