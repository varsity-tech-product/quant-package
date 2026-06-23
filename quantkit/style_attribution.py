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
