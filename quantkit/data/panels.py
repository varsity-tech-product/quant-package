"""把数据服务取回的原始 bars 拼成 build_signal 需要的面板。

build_signal 的入参是一组 ``[date x symbol]`` 的 DataFrame，参数名即字段名
（如 ``close``、``volume``、``taker_buy_volume``、``open_interest_close`` …）。
这些名字与数据服务 market_features 35 列 schema 一一对应。

输入：
* ``bars_panel``  —— ``{symbol: DataFrame}``，每个 DataFrame 是该 symbol 的 1d bars
                     （列含 close/volume/taker_*），来自 ``GatewayClient.fetch_bars_panel``
* ``features``    —— 可选 ``{symbol: DataFrame}``，含 OI/premium/大户多空比/funding_rate_close
                     等 feature 列（来自 market_features 1d）

输出：``{field: [date x symbol] DataFrame}``，所有面板 index/columns 对齐。
某个 plugin 需要的字段在任何数据源都找不到时，抛 :class:`MissingFieldError`。
"""
from __future__ import annotations

import pandas as pd

from ..plugins import FactorPlugin


class MissingFieldError(KeyError):
    """plugin 需要的字段在数据源里找不到。"""


def _field_table(
    field: str,
    bars_panel: dict[str, pd.DataFrame],
    features: dict[str, pd.DataFrame] | None,
) -> pd.DataFrame:
    # 把所有 symbol 在某个字段上的列拼成一张 [date x symbol] 表。
    """把所有 symbol 在某个字段上的列拼成一张 [date x symbol] 表。"""
    series: dict[str, pd.Series] = {}
    for sym, df in bars_panel.items():
        if field in df.columns:
            series[sym] = df[field]
        elif features and sym in features and field in features[sym].columns:
            series[sym] = features[sym][field]
    if not series:
        raise MissingFieldError(
            f"字段 '{field}' 在 bars 和 features 里都没有。"
            f"K 线类字段来自 GetHistoricalBars；OI/premium/大户多空比/funding_rate_close "
            f"来自 market_features 1d，需提供 features 参数。"
        )
    table = pd.DataFrame(series)
    table.index = pd.DatetimeIndex(table.index)
    return table.sort_index()


def build_panels(
    plugin: FactorPlugin,
    bars_panel: dict[str, pd.DataFrame],
    *,
    features: dict[str, pd.DataFrame] | None = None,
) -> dict[str, pd.DataFrame]:
    """为单个 plugin 构建它需要的所有面板（含 close）。

    所有面板对齐到共同的日期 index 和 symbol columns。
    """
    needed = ["close", *plugin.required_fields]
    tables = {f: _field_table(f, bars_panel, features) for f in dict.fromkeys(needed)}

    # 对齐到共同 index（日期交集）和共同 columns（symbol 交集）
    common_index = None
    common_cols = None
    for t in tables.values():
        common_index = t.index if common_index is None else common_index.intersection(t.index)
        common_cols = t.columns if common_cols is None else common_cols.intersection(t.columns)

    aligned = {
        f: t.loc[common_index, common_cols].sort_index()
        for f, t in tables.items()
    }
    return aligned


def run_build_signal(
    plugin: FactorPlugin,
    bars_panel: dict[str, pd.DataFrame],
    *,
    features: dict[str, pd.DataFrame] | None = None,
    params: dict | None = None,
) -> pd.DataFrame:
    """构建面板并跑该 plugin 的 build_signal，返回信号 ``[date x symbol]``。"""
    panels = build_panels(plugin, bars_panel, features=features)
    close = panels.pop("close")
    use_params = {**plugin.default_params, **(params or {})}
    return plugin.build_signal(close, use_params, **panels)
