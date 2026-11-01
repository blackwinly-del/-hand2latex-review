import torch
from torch import nn


class RiskMLP(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(8, 16),
            nn.ReLU(),
            nn.Linear(16, 8),
            nn.ReLU(),
            nn.Linear(8, 1),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.network(features)

    @torch.no_grad()
    def risk_score(self, features: torch.Tensor) -> torch.Tensor:
        """Return an uncalibrated experimental score; never rewrite LaTeX."""
        return torch.sigmoid(self(features))
