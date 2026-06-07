"""实盘信号层：把 strategy.json 的因子组合算成最新截面目标权重。

复用 :mod:`quantkit.compose`（与回测服务相同的 CS 组合口径），数据由
:mod:`quantkit.data.gateway_client` 从 exchange-gateway 取（只用 1d）。
"""
from __future__ import annotations

import logging

import pandas as pd

from ..compose import WeightedFactor, target_weights
from ..plugins import load_plugin
from . import config
from .config import StrategyConfig

logger = logging.getLogger("factor")


def build_weighted_factors(strategy: StrategyConfig) -> list[WeightedFactor]:
    # 把 strategy.json 里的 factor specs 加载成 WeightedFactor 列表。
    """把 strategy.json 里的 factor specs 加载成 WeightedFactor 列表。"""
    factors: list[WeightedFactor] = []
    for spec in strategy.factors:
        plugin = load_plugin(spec.plugin)
        factors.append(WeightedFactor(plugin=plugin, weight=spec.weight, params=spec.params or None))
        logger.info("加载因子 %s (w=%.3f) 需要字段 %s",
                    plugin.factor_type, spec.weight, plugin.required_fields)
    return factors


def compute_target_weights(
    strategy: StrategyConfig,
    bars_panel: dict[str, pd.DataFrame],
    *,
    features: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.Series, dict]:
    # 从策略配置 + 行情面板，算最新截面目标权重。
    """从策略配置 + 行情面板，算最新截面目标权重。"""
    factors = build_weighted_factors(strategy)
    weights, debug = target_weights(
        factors, bars_panel,
        ranking=strategy.ranking,
        features=features,
        strategy_type=strategy.strategy_type,
        gross=strategy.gross,
        max_single=config.MAX_SINGLE_WEIGHT,
    )
    logger.info("信号日期 %s 目标权重 %s", debug["date"], debug["weights"])
    return weights, debug
