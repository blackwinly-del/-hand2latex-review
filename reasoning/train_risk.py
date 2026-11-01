import math

import torch
from torch import nn

from reasoning.risk_mlp import RiskMLP


def train_risk(
    features: torch.Tensor,
    labels: torch.Tensor,
    *,
    epochs: int = 100,
    learning_rate: float = 0.01,
) -> tuple[RiskMLP, list[float]]:
    if not isinstance(features, torch.Tensor) or not isinstance(labels, torch.Tensor):
        raise TypeError("features and labels must be torch tensors")
    if features.ndim != 2 or features.shape[1] != 8:
        raise ValueError("features must have shape (n, 8)")
    if labels.shape != (features.shape[0], 1):
        raise ValueError("labels must have shape (n, 1)")
    if features.shape[0] == 0:
        raise ValueError("training samples must not be empty")
    if not isinstance(epochs, int) or epochs <= 0:
        raise ValueError("epochs must be a positive integer")
    if not math.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("learning_rate must be positive and finite")

    features = features.to(dtype=torch.float32)
    labels = labels.to(dtype=torch.float32)
    if not torch.isfinite(features).all() or not torch.isfinite(labels).all():
        raise ValueError("features and labels must be finite")
    if not torch.all((labels == 0) | (labels == 1)):
        raise ValueError("labels must be 0 or 1")

    model = RiskMLP()
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_history = []

    model.train()
    for _ in range(epochs):
        optimizer.zero_grad()
        logits = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        loss_history.append(loss.item())

    return model, loss_history
