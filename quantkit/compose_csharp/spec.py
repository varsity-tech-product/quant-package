"""Strategy composition spec + validation (plain Python, no pydantic).

Mirrors the weighting / ranking / strategy_type rules of
``quantai-service/strategy_composer/schema.py`` so a strategy composed here is
accepted on the same terms as a backtest submission. Kept dependency-free on
purpose — quant-package ships with stdlib + pandas/numpy only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

WeightingMode = Literal["equal", "custom"]
RankMode = Literal["N", "percent"]
StrategyType = Literal["long_only", "short_only", "neutral"]


@dataclass
class Weighting:
    """How per-factor signals combine. ``custom`` weights must be >0 and sum to 1."""

    mode: WeightingMode = "equal"
    weights: Optional[List[float]] = None

    def validate(self, n_factors: int) -> None:
        if self.mode == "custom":
            ws = self.weights or []
            if len(ws) != n_factors:
                raise ValueError(
                    f"weighting.weights length ({len(ws)}) must equal factors length ({n_factors})"
                )
            if any(w <= 0 for w in ws):
                raise ValueError("weighting.weights entries must be positive")
            if abs(sum(ws) - 1.0) > 1e-6:
                raise ValueError(f"weighting.weights must sum to 1.0 (got {sum(ws)})")
        else:  # equal
            if self.weights is not None:
                raise ValueError("weighting.weights must be omitted when mode='equal'")

    def resolved(self, n_factors: int) -> List[float]:
        if self.mode == "equal":
            return [1.0 / n_factors] * n_factors
        return list(self.weights or [])


@dataclass
class Ranking:
    """Basket selection: top/bottom N names, or top/bottom ``value`` percent."""

    mode: RankMode = "N"
    value: float = 5

    def validate(self) -> None:
        if self.value <= 0:
            raise ValueError("ranking.value must be > 0")
        if self.mode == "percent":
            if not (0 < self.value <= 50):
                raise ValueError("ranking.value must be in (0, 50] when mode='percent'")
        else:  # N
            if self.value < 1 or self.value != int(self.value):
                raise ValueError("ranking.value must be a positive integer when mode='N'")


@dataclass
class StrategySpec:
    """Everything the renderer needs beyond the factor plugins themselves.

    ``n_factors`` is supplied to :meth:`validate` by the renderer (it owns the
    plugin list); the spec only carries the knobs.
    """

    weighting: Weighting = field(default_factory=Weighting)
    ranking: Ranking = field(default_factory=lambda: Ranking(mode="N", value=5))
    strategy_type: StrategyType = "neutral"
    rebalance_bars: int = 1
    initial_cash: float = 100000.0
    start_date: str = "2024-01-01"
    end_date: str = "2026-03-01"

    def validate(self, n_factors: int) -> None:
        if not 1 <= n_factors <= 20:
            raise ValueError(f"factors count must be in 1..20 (got {n_factors})")
        if self.strategy_type not in ("long_only", "short_only", "neutral"):
            raise ValueError(f"invalid strategy_type: {self.strategy_type}")
        if self.rebalance_bars < 1:
            raise ValueError("rebalance_bars must be >= 1")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be > 0")
        self.weighting.validate(n_factors)
        self.ranking.validate()

    def resolved_weights(self, n_factors: int) -> List[float]:
        return self.weighting.resolved(n_factors)
