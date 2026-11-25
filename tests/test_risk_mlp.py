import unittest

import torch
from torch import nn

from reasoning.risk_mlp import RiskMLP


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
