import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "tail_rejection_flow_misalignment"

FACTOR_DEFAULT_PARAMS = {
    "window": 18,
    "shock_scale": 1.4,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "尾部拒绝与主动成交额失配：收盘接近一侧极值，但主动成交额冲击不支持该方向时做反转。",
    "__FACTOR_FORMULA__": "signal = -clv * (imbalance_now - avg_imbalance_prev_window) * shock_scale，其中 clv 为收盘在区间中的位置。",
    "__FACTOR_TYPE__": "tail_rejection_flow_misalignment",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _window;\n"
        "        private double _shockScale;\n"
        "        private readonly Queue<double> _highBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _lowBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellQuoteBuf = new Queue<double>();\n"
    ),
    "__FACTOR_INIT__": (
        '            _window = GetIntParameter("window", 18);\n'
        '            _shockScale = GetDoubleParameter("shock-scale", 1.4);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] window={_window} shock_scale={_shockScale}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_window",
    "__EXTRA_BUF_FIELDS__": "",
    "__EXTRA_BUF_ENQUEUE__": (
        "            _highBuf.Enqueue((double)bar.High);\n"
        "            _lowBuf.Enqueue((double)bar.Low);\n"
        "            _takerBuyQuoteBuf.Enqueue(bar.TakerBuyQuoteVolume);\n"
        "            _takerSellQuoteBuf.Enqueue(bar.TakerSellQuoteVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_highBuf.Count > requiredBars) _highBuf.Dequeue();\n"
        "            if (_lowBuf.Count > requiredBars) _lowBuf.Dequeue();\n"
        "            if (_takerBuyQuoteBuf.Count > requiredBars) _takerBuyQuoteBuf.Dequeue();\n"
        "            if (_takerSellQuoteBuf.Count > requiredBars) _takerSellQuoteBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var highs = _highBuf.ToArray();\n"
        "            var lows = _lowBuf.ToArray();\n"
        "            var takerBuyQuotes = _takerBuyQuoteBuf.ToArray();\n"
        "            var takerSellQuotes = _takerSellQuoteBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < _window || _window < 2) return false;

            var highNow = highs[n - 1];
            var lowNow = lows[n - 1];
            var closeNow = prices[n - 1];
            var rangeNow = highNow - lowNow;
            if (rangeNow < 1e-12)
            {
                rawSignal = 0.0;
                return true;
            }

            var clv = ((closeNow - lowNow) - (highNow - closeNow)) / rangeNow;

            double prevImbalanceMean = 0.0;
            for (int i = 0; i < n - 1; i++)
            {
                var totalPrev = takerBuyQuotes[i] + takerSellQuotes[i];
                var imbalancePrev = totalPrev > 1e-12 ? (takerBuyQuotes[i] - takerSellQuotes[i]) / totalPrev : 0.0;
                prevImbalanceMean += imbalancePrev;
            }
            prevImbalanceMean /= (n - 1);

            var totalNow = takerBuyQuotes[n - 1] + takerSellQuotes[n - 1];
            var imbalanceNow = totalNow > 1e-12 ? (takerBuyQuotes[n - 1] - takerSellQuotes[n - 1]) / totalNow : 0.0;
            var imbalanceShock = imbalanceNow - prevImbalanceMean;

            rawSignal = -clv * imbalanceShock * _shockScale;
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    high: pd.DataFrame,
    low: pd.DataFrame,
    taker_buy_quote_volume: pd.DataFrame,
    taker_sell_quote_volume: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    window = int(params.get("window", 18))
    shock_scale = float(params.get("shock_scale", 1.4))

    range_now = (high - low).replace(0.0, np.nan)
    clv = ((close - low) - (high - close)) / range_now

    total_quote = taker_buy_quote_volume + taker_sell_quote_volume
    imbalance = (taker_buy_quote_volume - taker_sell_quote_volume) / total_quote.replace(0.0, np.nan)
    imbalance = imbalance.fillna(0.0)

    prev_mean = imbalance.shift(1).rolling(window - 1, min_periods=window - 1).mean()
    signal = -clv * (imbalance - prev_mean) * shock_scale
    signal = signal.where(range_now.notna())
    signal.iloc[: max(window - 1, 0)] = np.nan
    return signal.reindex_like(close)
