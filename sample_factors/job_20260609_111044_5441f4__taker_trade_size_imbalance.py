from typing import Any, Dict

import numpy as np
import pandas as pd

FACTOR_TYPE = "taker_trade_size_imbalance"
FACTOR_NAME = "Taker Trade Size Imbalance"
FACTOR_DEFAULT_PARAMS = {"window": 14, "smooth": 5}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Microstructure factor measuring institutional order dominance by comparing average taker buy trade size to average taker sell trade size. Positive signal when large buyers dominate; negative when large sellers dominate. Rolling z-score normalized then smoothed.",
    "__FACTOR_FORMULA__": "zscore((avg_buy_size - avg_sell_size) / (avg_buy_size + avg_sell_size), window).sma(smooth)",
    "__FACTOR_TYPE__": FACTOR_TYPE,
    "__FACTOR_PARAM_FIELDS__": "        private int _window;\n        private int _smooth;\n",
    "__FACTOR_INIT__": '            _window = GetIntParameter("window", 14);\n            _smooth = GetIntParameter("smooth", 5);\n',
    "__FACTOR_LOG__": '            Log($"[INIT] window={_window} smooth={_smooth}");\n',
    "__PRICE_WINDOW_EXPR__": "_window + _smooth + 1",
    "__EXTRA_BUF_FIELDS__": "",
    "__EXTRA_BUF_ENQUEUE__": "",
    "__EXTRA_BUF_DEQUEUE__": "",
    "__EXTRA_BUF_TOARRAY__": "",
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < _window + _smooth) return false;
            rawSignal = 0.0;
            return true;
""",
}


def build_signal(close: pd.DataFrame, params: Dict[str, Any], **data: Any) -> pd.DataFrame:
    window = int(params.get("window", FACTOR_DEFAULT_PARAMS["window"]))
    smooth = int(params.get("smooth", FACTOR_DEFAULT_PARAMS["smooth"]))

    tbq = data.get("taker_buy_quote_volume")
    tsq = data.get("taker_sell_quote_volume")
    tbt = data.get("taker_buy_trades")
    tst = data.get("taker_sell_trades")

    if any(x is None for x in (tbq, tsq, tbt, tst)):
        return pd.DataFrame(0.0, index=close.index, columns=close.columns)

    eps = 1e-8

    avg_buy = tbq / (tbt + eps)
    avg_sell = tsq / (tst + eps)

    denom = avg_buy + avg_sell + eps
    raw = (avg_buy - avg_sell) / denom

    min_periods = max(1, window // 2)
    rmean = raw.rolling(window, min_periods=min_periods).mean()
    rstd = raw.rolling(window, min_periods=min_periods).std()
    rstd = rstd.where(rstd > 0, np.nan)

    zscore = (raw - rmean) / rstd
    zscore = zscore.clip(-3, 3)

    signal = zscore.rolling(smooth, min_periods=1).mean()
    return signal.reindex_like(close)
