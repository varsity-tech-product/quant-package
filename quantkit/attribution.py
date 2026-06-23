"""策略预测值风格归因 —— compose / data 与 :mod:`quantkit.style_attribution` 的胶水层。

归因对象是**策略的预测值（composite 信号）**，不是回测盈亏。回测在服务端编译
C# 跑 Lean，其结果（summary/orders/charts）里没有"每期每币的 composite 预测值
面板"，所以这里用 :func:`quantkit.compose.composite_signal` 在本地按**同口径**
（每因子 build_signal -> 截面 z-score -> 按权重加权）复算预测面板，再喂给外部
口径的风格归因。

数据走 exchange-gateway 1d 面板，单 symbol ≤300 根 ≈ 300 天，所以本地归因窗口
最多覆盖最近 ~300 天；若回测窗口更长，这只是其近期子集。

用法::

    from quantkit.compose import WeightedFactor
    from quantkit.plugins import load_plugin
    from quantkit.data.gateway_client import GatewayClient
    from quantkit.attribution import attribute_strategy

    gw = GatewayClient()
    bars = gw.fetch_bars_panel(symbols, limit=300)
    factors = [
        WeightedFactor(load_plugin("momentum.py"), 0.6),
        WeightedFactor(load_plugin("taker_flow.py"), 0.4),
    ]
    res = attribute_strategy(factors, bars, save_path="attribution.png")
    print(res["long_short_exposure"].sort_values(key=abs, ascending=False).round(4))
"""
from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from .compose import WeightedFactor, composite_signal
from .style_attribution import (
    build_base_style_factors,
    calc_prediction_style_exposure,
    plot_prediction_style_exposure,
)

# exchange-gateway 1d bar 没有 "amount" 列；成交额（quote 计价）在 quote_volume。
DEFAULT_AMOUNT_FIELD = "quote_volume"


def composite_to_pred_df(
    composite: pd.DataFrame,
    *,
    time_col: str = "timestamp",
    symbol_col: str = "symbol",
    pred_col: str = "prediction",
) -> pd.DataFrame:
    """把 composite 信号 ``[date x symbol]`` 摊平成归因要的 long ``pred_df``。"""
    wide = composite.copy()
    wide.index = pd.Index(wide.index, name=time_col)
    long = wide.reset_index().melt(
        id_vars=time_col, var_name=symbol_col, value_name=pred_col
    )
    return long.dropna(subset=[pred_col]).reset_index(drop=True)


def _funding_to_long(
    funding: dict[str, pd.Series],
    time_col: str,
    symbol_col: str,
) -> pd.DataFrame:
    """把 {symbol: funding Series} 折算成日度 long，便于按 [timestamp, symbol] 并入。"""
    frames = []
    for sym, ser in funding.items():
        if ser is None or len(ser) == 0:
            continue
        idx = pd.to_datetime(ser.index, utc=True)
        daily = pd.Series(ser.to_numpy(), index=idx).resample("1D").mean()
        frames.append(
            pd.DataFrame(
                {time_col: daily.index, symbol_col: sym, "funding_rate": daily.to_numpy()}
            )
        )
    if not frames:
        return pd.DataFrame(columns=[time_col, symbol_col, "funding_rate"])
    return pd.concat(frames, ignore_index=True)


def bars_panel_to_base_df(
    bars_panel: dict[str, pd.DataFrame],
    *,
    amount_field: str = DEFAULT_AMOUNT_FIELD,
    funding: dict[str, pd.Series] | None = None,
    time_col: str = "timestamp",
    symbol_col: str = "symbol",
) -> pd.DataFrame:
    """把 {symbol: bar DataFrame} 拼成归因要的 long ``base_df``。

    取 close（必需）与成交额（``amount_field`` -> ``amount``，缺则跳过对应风格）。
    ``funding`` 为 ``{symbol: Series}`` 时按日折算并入 ``funding_rate``（可选）。
    """
    frames = []
    for sym, df in bars_panel.items():
        if df is None or df.empty or "close" not in df.columns:
            continue
        cols = {time_col: pd.to_datetime(df.index, utc=True), symbol_col: sym, "close": df["close"].to_numpy()}
        if amount_field in df.columns:
            cols["amount"] = df[amount_field].to_numpy()
        frames.append(pd.DataFrame(cols))
    if not frames:
        raise ValueError("bars_panel 里没有可用的 close 数据")
    base = pd.concat(frames, ignore_index=True)

    if funding:
        fund_long = _funding_to_long(funding, time_col, symbol_col)
        if not fund_long.empty:
            base = base.merge(fund_long, on=[time_col, symbol_col], how="left")

    return base


def attribute_strategy(
    factors: list[WeightedFactor],
    bars_panel: dict[str, pd.DataFrame],
    *,
    features: dict[str, pd.DataFrame] | None = None,
    funding: dict[str, pd.Series] | None = None,
    amount_field: str = DEFAULT_AMOUNT_FIELD,
    style_cols: Sequence[str] | None = None,
    top_pct: float = 0.2,
    min_cs_size: int = 20,
    roll_window: int = 60,
    market_symbol: str = "BTCUSDT",
    save_path: str | None = None,
    title_prefix: str = "Strategy",
) -> dict:
    """对一个因子组合做预测值风格归因。

    1. ``composite_signal(factors, bars_panel)`` 复算策略预测面板（与回测同口径）。
    2. 从 ``bars_panel`` 构造 base 风格因子。
    3. 在每个截面按预测值分多空桶，统计风格暴露。

    返回 :func:`calc_prediction_style_exposure` 的结果 dict，额外带上 ``pred_df`` /
    ``base_df`` 便于复查。``save_path`` 给定时顺带存三联图。
    """
    composite = composite_signal(factors, bars_panel, features=features)
    pred_df = composite_to_pred_df(composite)
    base_df = bars_panel_to_base_df(bars_panel, amount_field=amount_field, funding=funding)
    style_df = build_base_style_factors(base_df, market_symbol=market_symbol)

    result = calc_prediction_style_exposure(
        eval_df=pred_df,
        pred_col="prediction",
        style_df=style_df,
        style_cols=style_cols,
        top_pct=top_pct,
        min_cs_size=min_cs_size,
        roll_window=roll_window,
    )
    result["pred_df"] = pred_df
    result["base_df"] = base_df

    if save_path is not None:
        plot_prediction_style_exposure(result, save_path=save_path, title_prefix=title_prefix)

    return result
