"""多因子组合：把若干 plugin 的信号合成 composite，再生成截面权重。

口径对齐策略回测服务的截面（CS）语义（见 strategy_submit.md §1）：

1. 每个因子各自跑 ``build_signal`` 得到 ``[date x symbol]`` 信号
2. 在**每个截面**（每一天，跨 symbol）做 z-score 标准化
3. 按因子权重加权求和 → composite
4. 按 composite 排名取多空：top k 做多 / bottom k 做空

这样实盘的组合方式与提交回测时服务端的组合方式一致，回测/实盘可比。

回测提交路径不用这里——那条路只需把 ``{job_id, plugin}`` + ``weighting`` 交给
服务端，由服务端组合（见 :mod:`quantkit.backtest`）。这里是**实盘本地**用的。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data.panels import run_build_signal
from .plugins import FactorPlugin


@dataclass
class WeightedFactor:
    plugin: FactorPlugin
    weight: float = 1.0
    params: dict | None = None


def cross_section_zscore(signal: pd.DataFrame) -> pd.DataFrame:
    # 对每一行（截面）跨 symbol 做 z-score。std 为 0 的行输出 0。
    """对每一行（截面）跨 symbol 做 z-score。std 为 0 的行输出 0。"""
    mu = signal.mean(axis=1)
    sd = signal.std(axis=1, ddof=0)
    z = signal.sub(mu, axis=0).div(sd.replace(0.0, np.nan), axis=0)
    return z


def composite_signal(
    factors: list[WeightedFactor],
    bars_panel: dict[str, pd.DataFrame],
    *,
    features: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    # 合成 composite 信号 ``[date x symbol]``。
    """合成 composite 信号 ``[date x symbol]``。

    每个因子：build_signal -> 截面 z-score；再按归一化权重加权求和。
    """
    if not factors:
        raise ValueError("至少需要一个因子")

    total_w = sum(abs(f.weight) for f in factors)
    if total_w == 0:
        raise ValueError("权重之和不能为 0")

    composite: pd.DataFrame | None = None
    for f in factors:
        raw = run_build_signal(f.plugin, bars_panel, features=features, params=f.params)
        z = cross_section_zscore(raw)
        contrib = z * (f.weight / total_w)
        composite = contrib if composite is None else composite.add(contrib, fill_value=0.0)
    return composite


def cross_section_weights(
    latest: pd.Series,
    *,
    ranking: dict,
    strategy_type: str = "neutral",
    gross: float = 1.0,
    max_single: float = 0.40,
) -> pd.Series:
    """给定最新截面 composite 值，生成目标权重。

    Args:
        latest: 每个 symbol 一个 composite 值。
        ranking: ``{"mode": "N", "value": 5}`` 或 ``{"mode": "percent", "value": 10}``。
                 口径同回测服务：percent 时 k = round(n * value / 100)，N 时 k 收缩到
                 floor(n/2) 防多空重叠。
        strategy_type: ``neutral`` / ``long_only`` / ``short_only``。
        gross: 总绝对敞口占资金比例。
        max_single: 单 symbol 最大权重绝对值。

    Returns: ``{symbol: weight}``，正=多，负=空，0=不持仓。
    """
    valid = latest.dropna()
    n = len(valid)
    if n == 0:
        return pd.Series(0.0, index=latest.index)

    k = _resolve_k(ranking, n)
    ranked = valid.rank(ascending=True)  # 1 = 最低
    long_mask = ranked >= (n - k + 1)
    short_mask = ranked <= k

    w = pd.Series(0.0, index=valid.index)
    if strategy_type in ("neutral", "long_only") and long_mask.sum() > 0:
        side = gross if strategy_type == "long_only" else gross / 2.0
        w[long_mask] = min(side / long_mask.sum(), max_single)
    if strategy_type in ("neutral", "short_only") and short_mask.sum() > 0:
        side = gross if strategy_type == "short_only" else gross / 2.0
        w[short_mask] = -min(side / short_mask.sum(), max_single)

    return w.reindex(latest.index, fill_value=0.0)


def _resolve_k(ranking: dict, n: int) -> int:
    mode = ranking.get("mode")
    value = ranking.get("value")
    if mode == "N":
        k = int(value)
    elif mode == "percent":
        k = round(n * float(value) / 100.0)
    else:
        raise ValueError(f"未知 ranking.mode: {mode}")
    k = max(1, min(k, n // 2 if n >= 2 else 1))
    return k


def target_weights(
    factors: list[WeightedFactor],
    bars_panel: dict[str, pd.DataFrame],
    *,
    ranking: dict,
    features: dict[str, pd.DataFrame] | None = None,
    strategy_type: str = "neutral",
    gross: float = 1.0,
    max_single: float = 0.40,
) -> tuple[pd.Series, dict]:
    """一步从 plugins + 数据到最新截面目标权重（实盘入口）。

    Returns: (weights Series, debug dict)。
    """
    comp = composite_signal(factors, bars_panel, features=features)
    latest = comp.iloc[-1]
    weights = cross_section_weights(
        latest, ranking=ranking, strategy_type=strategy_type,
        gross=gross, max_single=max_single,
    )
    debug = {
        "date": str(comp.index[-1].date()),
        "composite": latest.round(4).to_dict(),
        "weights": weights[weights != 0].round(4).to_dict(),
    }
    return weights, debug
