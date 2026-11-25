import unittest

import torch

from reasoning.risk_mlp import RiskMLP
from reasoning.train_risk import train_risk


class TrainRiskTests(unittest.TestCase):
    def setUp(self):
        self.features = torch.tensor(
            [
                [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            ]
        )
        self.labels = torch.tensor([[0.0], [0.0], [1.0], [1.0]])

    def test_training_updates_parameters_and_reduces_teaching_loss(self):
        torch.manual_seed(0)
        model, loss_history = train_risk(
            self.features, self.labels, epochs=200, learning_rate=0.05
        )

        self.assertEqual(len(loss_history), 200)
        self.assertLess(loss_history[-1], loss_history[0])
        self.assertLess(loss_history[-1], 0.1)
        self.assertTrue(all(torch.isfinite(torch.tensor(loss_history))))
        self.assertEqual(model(self.features).shape, (4, 1))

    def test_one_training_step_changes_weights(self):
        torch.manual_seed(0)
        untrained_model = RiskMLP()
        torch.manual_seed(0)
        model, _ = train_risk(self.features, self.labels, epochs=1)

        trained_parameters = list(model.parameters())
        untrained_parameters = list(untrained_model.parameters())

        self.assertTrue(
            any(
                not torch.equal(trained, untrained)
                for trained, untrained in zip(trained_parameters, untrained_parameters)
            )
        )

    def test_invalid_shapes_and_empty_samples_are_rejected(self):
        invalid_cases = [
            (torch.zeros(2, 7), torch.zeros(2, 1)),
            (torch.zeros(2, 8), torch.zeros(2)),
            (torch.zeros(0, 8), torch.zeros(0, 1)),
        ]
        for features, labels in invalid_cases:
            with self.subTest(features=features.shape, labels=labels.shape):
                with self.assertRaises(ValueError):
                    train_risk(features, labels)

    def test_invalid_labels_and_hyperparameters_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 or 1"):
            train_risk(self.features, self.labels + 2)
        with self.assertRaisesRegex(ValueError, "finite"):
            train_risk(self.features, torch.full_like(self.labels, float("nan")))
        with self.assertRaisesRegex(ValueError, "epochs"):
            train_risk(self.features, self.labels, epochs=0)
        with self.assertRaisesRegex(ValueError, "learning_rate"):
            train_risk(self.features, self.labels, learning_rate=0)

    def test_non_tensor_inputs_are_rejected(self):
        with self.assertRaises(TypeError):
            train_risk(self.features.tolist(), self.labels)


if __name__ == "__main__":
    unittest.main()
