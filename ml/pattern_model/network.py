"""Lightweight non-causal temporal convolutional network.

The recording is scored offline, so each layer looks both backward and forward.
One shared network reads a single hand. Independent sigmoids produce that
hand's tremor and impairment scores. Nothing in the head
forces those scores to add up to 100.
"""

import torch
from torch import nn

from ml.pattern_model.config import DROPOUT, HAND_CHANNELS, HAND_SCORES, HIDDEN, KERNEL, LEVELS


class TemporalBlock(nn.Module):
    def __init__(self, channels: int, kernel: int, dilation: int, dropout: float):
        super().__init__()
        padding = dilation * (kernel - 1) // 2
        self.conv1 = nn.Conv1d(channels, channels, kernel, padding=padding, dilation=dilation)
        self.norm1 = nn.GroupNorm(_groups(channels), channels)
        self.conv2 = nn.Conv1d(channels, channels, kernel, padding=padding, dilation=dilation)
        self.norm2 = nn.GroupNorm(_groups(channels), channels)
        self.drop = nn.Dropout(dropout)
        self.act = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.drop(self.act(self.norm1(self.conv1(x))))
        y = self.drop(self.act(self.norm2(self.conv2(y))))
        if y.shape[-1] != x.shape[-1]:
            y = y[..., : x.shape[-1]]
        return self.act(x + y)


class PatternTCN(nn.Module):
    def __init__(
        self,
        in_channels: int,
        hidden: int = HIDDEN,
        levels: int = LEVELS,
        kernel: int = KERNEL,
        dropout: float = DROPOUT,
        n_scores: int = len(HAND_SCORES),
    ):
        super().__init__()
        self.in_channels = in_channels
        self.hidden = hidden
        self.levels = levels
        self.kernel = kernel
        self.dropout = dropout
        self.in_proj = nn.Conv1d(in_channels, hidden, kernel_size=1)
        self.blocks = nn.ModuleList(
            TemporalBlock(hidden, kernel, 2**level, dropout) for level in range(levels)
        )
        # Tremor reads the gyroscope on top of the shared features. Impairment
        # reads this hand's speed and whether later reaches got smaller.
        # Stroke is the gap between the two hands' impairment, so a speed
        # difference becomes a stroke score. Parkinson is the impairment
        # they share.
        self.tremor_head = nn.Linear(hidden + 1, 1)
        self.impair_head = nn.Linear(hidden + 2, 1)
        self.gyro_index = HAND_CHANNELS.index("gyro_level")
        self.speed_index = HAND_CHANNELS.index("move_speed")
        self.shrink_index = HAND_CHANNELS.index("shrink_ratio")
        # A little gyroscope noise should not count as tremor. Slowness should
        # count before the reach is extremely slow. These terms stay in the
        # forward pass so training cannot drop them.
        self.gyro_floor = 0.85
        self.gyro_trait = 0.45
        self.speed_trait = 2.6
        _favor(self.tremor_head, [0.6])
        _favor(self.impair_head, [2.4, -1.2])
        if n_scores != 2:
            raise ValueError("The pattern network scores tremor and impairment.")

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        """Score a batch of single-hand stretches.

        `x` is (batch, channels, time). `mask` is (batch, time), 1 on real
        samples and 0 on padding. Returns (batch, n_scores) scores in (0, 100).
        """
        hidden = self.in_proj(x)
        for block in self.blocks:
            hidden = block(hidden)
        if mask is None:
            pooled = hidden.mean(dim=-1)
        else:
            weights = mask.unsqueeze(1)
            pooled = (hidden * weights).sum(dim=-1) / weights.sum(dim=-1).clamp(min=1.0)
        gyro = x[:, self.gyro_index].abs().mean(dim=-1, keepdim=True)
        speed = x[:, self.speed_index].mean(dim=-1, keepdim=True)
        shrink = x[:, self.shrink_index].mean(dim=-1, keepdim=True)
        # Ignore the quiet part of the gyroscope. Count only speed below the
        # training average, and count it more than once.
        gyro_drive = torch.relu(gyro - self.gyro_floor)
        slow = torch.relu(-speed)
        tremor = self.tremor_head(torch.cat([pooled, gyro_drive], dim=1)) + self.gyro_trait * gyro_drive
        impairment = self.impair_head(torch.cat([pooled, slow, shrink], dim=1)) + self.speed_trait * slow
        return torch.sigmoid(torch.cat([tremor, impairment], dim=1)) * 100.0


def _favor(layer: nn.Linear, feature_weights: list[float]) -> None:
    """Start with a normal readout, then give the trait columns a head start."""
    nn.init.xavier_uniform_(layer.weight)
    nn.init.zeros_(layer.bias)
    count = len(feature_weights)
    with torch.no_grad():
        layer.weight[:, -count:] = 0.0
        for index, weight in enumerate(feature_weights):
            layer.weight[0, -count + index] = weight


def _groups(channels: int) -> int:
    for size in (8, 4, 2, 1):
        if channels % size == 0:
            return size
    return 1
