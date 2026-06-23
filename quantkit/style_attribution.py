"""CS 预测值风格归因（vendored）。

口径来源：外部文档 `cs_style_attribution.md`。本模块**逐字搬运**该文档的自包含
实现，逻辑不做改动，以便与外部口径对账。唯一的本地适配：

* 顶部强制 matplotlib 使用无头 ``Agg`` 后端（服务器无显示）。
* :func:`plot_prediction_style_exposure` 增加 ``save_path`` 参数，可存图而非
  ``plt.show()``（最小侵入，默认行为不变）。

只做一件事：在每个 ``timestamp`` 横截面内，按模型预测值排序，取最高一组为多头
bucket、最低一组为空头 bucket，统计多空两边对基础风格因子的暴露。

package 胶水层（compose composite -> pred_df、bars panel -> base_df）见
:mod:`quantkit.attribution`。
"""
from __future__ import annotations

from collections.abc import Sequence

import matplotlib

matplotlib.use("Agg")  # 无头环境：必须在 import pyplot 之前设置

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


DEFAULT_STYLE_COLS = [
    "style_liquidity",
    "style_volatility",
    "style_momentum",
    "style_reversal",
    "style_volume_momentum",
    "style_funding",
    "style_beta",
]


def to_utc_datetime(values: pd.Series) -> pd.Series:
    """Convert a Series-like timestamp column to timezone-aware UTC datetime."""
    return pd.to_datetime(values, utc=True, errors="coerce")


def _cs_standardize_style_factors(
    df: pd.DataFrame,
    style_cols: Sequence[str],
    time_col: str = "timestamp",
) -> pd.DataFrame:
    """Cross-sectionally z-score style columns at each timestamp."""
    out = df.copy()
    for col in style_cols:
        vals = pd.to_numeric(out[col], errors="coerce")
        grp = vals.groupby(out[time_col])
        mu = grp.transform("mean")
        sigma = grp.transform("std")
        out[col] = (vals - mu) / (sigma + 1e-9)
    return out


def build_base_style_factors(
    base_df: pd.DataFrame,
    time_col: str = "timestamp",
    symbol_col: str = "symbol",
    price_col: str = "close",
    amount_col: str = "amount",
    funding_col: str = "funding_rate",
    momentum_window: int = 20,
    reversal_window: int = 3,
    volatility_window: int = 20,
    liquidity_window: int = 20,
    funding_window: int = 7,
    beta_window: int = 60,
    market_symbol: str = "BTCUSDT",
) -> pd.DataFrame:
    """Build base style factors from bar data.

    Required columns: timestamp, symbol, close.
    Optional columns: amount, funding_rate.
    Output beta column is named style_beta.
    """
    required = {time_col, symbol_col, price_col}
    missing = required.difference(base_df.columns)
    if missing:
        raise ValueError(f"base_df missing columns: {sorted(missing)}")

    d = base_df.copy()
    d[time_col] = to_utc_datetime(d[time_col])
    d = d.sort_values([symbol_col, time_col]).reset_index(drop=True)

    price = pd.to_numeric(d[price_col], errors="coerce")
    ret = np.log(price.where(price > 0)).groupby(d[symbol_col], sort=False).diff()

    if amount_col in d.columns:
        amount = pd.to_numeric(d[amount_col], errors="coerce")
        liq = amount.groupby(d[symbol_col], sort=False).transform(
            lambda s: s.rolling(
                liquidity_window,
                min_periods=max(2, liquidity_window // 4),
            ).mean()
        )
        d["style_liquidity"] = np.log(liq.where(liq > 0))

        volume_momentum = amount.groupby(d[symbol_col], sort=False).pct_change(liquidity_window)
        d["style_volume_momentum"] = np.log1p(
            volume_momentum.replace([np.inf, -np.inf], np.nan)
        )
    else:
        d["style_liquidity"] = np.nan
        d["style_volume_momentum"] = np.nan

    d["style_volatility"] = ret.groupby(d[symbol_col], sort=False).transform(
        lambda s: s.rolling(
            volatility_window,
            min_periods=max(2, volatility_window // 4),
        ).std()
    )
    d["style_momentum"] = price.groupby(d[symbol_col], sort=False).pct_change(momentum_window)
    d["style_reversal"] = -price.groupby(d[symbol_col], sort=False).pct_change(reversal_window)

    if funding_col in d.columns:
        funding = pd.to_numeric(d[funding_col], errors="coerce")
        d["style_funding"] = funding.groupby(d[symbol_col], sort=False).transform(
            lambda s: s.rolling(funding_window, min_periods=1).mean()
        )
    else:
        d["style_funding"] = np.nan

    wide_ret = (
        pd.DataFrame({time_col: d[time_col], symbol_col: d[symbol_col], "_ret": ret})
        .pivot_table(index=time_col, columns=symbol_col, values="_ret", aggfunc="last")
        .sort_index()
    )
    if market_symbol in wide_ret.columns:
        market_ret = wide_ret[market_symbol]
        market_var = market_ret.rolling(
            beta_window,
            min_periods=max(5, beta_window // 4),
        ).var()
        beta_series = []
        for sym in wide_ret.columns:
            cov = wide_ret[sym].rolling(
                beta_window,
                min_periods=max(5, beta_window // 4),
            ).cov(market_ret)
            beta_series.append(cov.div(market_var).rename(sym))

        beta_wide = pd.concat(beta_series, axis=1) if beta_series else pd.DataFrame(index=wide_ret.index)
        beta_wide.index.name = time_col
        beta_wide.columns.name = symbol_col
        beta_long = beta_wide.reset_index().melt(
            id_vars=time_col,
            var_name=symbol_col,
            value_name="style_beta",
        )
        d = d.merge(beta_long, on=[time_col, symbol_col], how="left")
    else:
        d["style_beta"] = np.nan

    cols = [time_col, symbol_col] + DEFAULT_STYLE_COLS
    return d[cols].sort_values([time_col, symbol_col]).reset_index(drop=True)


def calc_prediction_style_exposure(
    eval_df: pd.DataFrame,
    pred_col: str,
    style_df: pd.DataFrame,
    style_cols: Sequence[str] | None = None,
    top_pct: float = 0.1,
    time_col: str = "timestamp",
    symbol_col: str = "symbol",
    min_cs_size: int = 20,
    roll_window: int = 60,
) -> dict:
    """Measure prediction long/short buckets against style factors."""
    if not 0 < top_pct < 0.5:
        raise ValueError("top_pct must be in (0, 0.5)")

    styles = style_df.copy()
    styles[time_col] = to_utc_datetime(styles[time_col])

    if style_cols is None:
        style_cols = [
            c
            for c in DEFAULT_STYLE_COLS
            if c in styles.columns and pd.api.types.is_numeric_dtype(styles[c])
        ]
    style_cols = list(style_cols)
    if not style_cols:
        raise ValueError("No style columns found for attribution")

    styles = _cs_standardize_style_factors(
        styles[[time_col, symbol_col] + style_cols].copy(),
        style_cols,
        time_col=time_col,
    )

    required = {time_col, symbol_col, pred_col}
    missing = required.difference(eval_df.columns)
    if missing:
        raise ValueError(f"eval_df missing columns: {sorted(missing)}")

    d = eval_df[[time_col, symbol_col, pred_col]].copy()
    d[time_col] = to_utc_datetime(d[time_col])
    d[pred_col] = pd.to_numeric(d[pred_col], errors="coerce")
    d = d.dropna(subset=[pred_col]).merge(styles, on=[time_col, symbol_col], how="left")

    long_rows, short_rows, corr_rows = [], [], []
    for t, g in d.groupby(time_col, sort=True):
        valid_pred = g.dropna(subset=[pred_col])
        if len(valid_pred) < min_cs_size:
            continue

        n = len(valid_pred)
        k = max(int(n * top_pct), 1)
        rank = valid_pred[pred_col].rank(method="first")
        long_g = valid_pred.loc[rank > (n - k)]
        short_g = valid_pred.loc[rank <= k]

        row_l = {time_col: t}
        row_s = {time_col: t}
        row_c = {time_col: t}
        for col in style_cols:
            row_l[col] = float(long_g[col].mean()) if not long_g[col].isna().all() else np.nan
            row_s[col] = float(short_g[col].mean()) if not short_g[col].isna().all() else np.nan

            valid = valid_pred[pred_col].notna() & valid_pred[col].notna()
            row_c[col] = (
                float(valid_pred.loc[valid, pred_col].corr(valid_pred.loc[valid, col], method="spearman"))
                if valid.sum() >= min_cs_size
                else np.nan
            )

        long_rows.append(row_l)
        short_rows.append(row_s)
        corr_rows.append(row_c)

    long_ts = pd.DataFrame(long_rows)
    short_ts = pd.DataFrame(short_rows)
    roll_corr = pd.DataFrame(corr_rows)
    if not roll_corr.empty:
        roll_corr = roll_corr.sort_values(time_col).set_index(time_col)
        roll_corr = roll_corr.rolling(
            roll_window,
            min_periods=min(10, roll_window),
        ).mean().reset_index()

    long_exp = long_ts[style_cols].mean() if not long_ts.empty else pd.Series(dtype=float)
    short_exp = short_ts[style_cols].mean() if not short_ts.empty else pd.Series(dtype=float)
    long_short_exp = (
        long_exp - short_exp
        if not long_exp.empty and not short_exp.empty
        else pd.Series(dtype=float)
    )

    return {
        "long_exposure": long_exp,
        "short_exposure": short_exp,
        "long_short_exposure": long_short_exp,
        "long_ts": long_ts,
        "short_ts": short_ts,
        "roll_corr": roll_corr,
        "style_frame": styles,
        "style_cols": style_cols,
        "top_pct": top_pct,
        "roll_window": roll_window,
        "attribution_type": "prediction",
    }
