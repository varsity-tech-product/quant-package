import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "execution_premium_asymmetry"

FACTOR_DEFAULT_PARAMS = {
    "window": 16,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "执行溢价不对称：比较主动买入和主动卖出相对总体成交均价的执行溢价，配合成交额失衡判断方向压力。",
    "__FACTOR_FORMULA__": "buy_vwap=sum(buy_quote,w)/sum(buy_vol,w); sell_vwap=sum(sell_quote,w)/sum(sell_vol,w); total_vwap=sum(quote,w)/sum(volume,w); asym=((buy_vwap-total_vwap)-(total_vwap-sell_vwap))/range_w; imbalance=(sum(buy_quote,w)-sum(sell_quote,w))/sum(quote,w); signal=asym+0.5*imbalance",
    "__FACTOR_TYPE__": "execution_premium_asymmetry",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _window;\n"
    ),
    "__FACTOR_INIT__": (
        '            _window = GetIntParameter("window", 16);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] window={_window}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_window",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _highBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _lowBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _volumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _quoteVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyQuoteVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellQuoteVolumeBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _highBuf.Enqueue((double)bar.High);\n"
        "            _lowBuf.Enqueue((double)bar.Low);\n"
        "            _volumeBuf.Enqueue((double)bar.Volume);\n"
        "            _quoteVolumeBuf.Enqueue(bar.QuoteVolume);\n"
        "            _takerBuyVolumeBuf.Enqueue(bar.TakerBuyVolume);\n"
        "            _takerSellVolumeBuf.Enqueue(bar.TakerSellVolume);\n"
        "            _takerBuyQuoteVolumeBuf.Enqueue(bar.TakerBuyQuoteVolume);\n"
        "            _takerSellQuoteVolumeBuf.Enqueue(bar.TakerSellQuoteVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_highBuf.Count > requiredBars) _highBuf.Dequeue();\n"
        "            if (_lowBuf.Count > requiredBars) _lowBuf.Dequeue();\n"
        "            if (_volumeBuf.Count > requiredBars) _volumeBuf.Dequeue();\n"
        "            if (_quoteVolumeBuf.Count > requiredBars) _quoteVolumeBuf.Dequeue();\n"
        "            if (_takerBuyVolumeBuf.Count > requiredBars) _takerBuyVolumeBuf.Dequeue();\n"
        "            if (_takerSellVolumeBuf.Count > requiredBars) _takerSellVolumeBuf.Dequeue();\n"
        "            if (_takerBuyQuoteVolumeBuf.Count > requiredBars) _takerBuyQuoteVolumeBuf.Dequeue();\n"
        "            if (_takerSellQuoteVolumeBuf.Count > requiredBars) _takerSellQuoteVolumeBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var highs = _highBuf.ToArray();\n"
        "            var lows = _lowBuf.ToArray();\n"
        "            var volumes = _volumeBuf.ToArray();\n"
        "            var quoteVolumes = _quoteVolumeBuf.ToArray();\n"
        "            var takerBuyVolumes = _takerBuyVolumeBuf.ToArray();\n"
        "            var takerSellVolumes = _takerSellVolumeBuf.ToArray();\n"
        "            var takerBuyQuoteVolumes = _takerBuyQuoteVolumeBuf.ToArray();\n"
        "            var takerSellQuoteVolumes = _takerSellQuoteVolumeBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var window = Math.Max(2, _window);
            var n = prices.Length;
            if (n < window) return false;

            double rollingHigh = highs[0];
            double rollingLow = lows[0];
            double sumVolume = 0.0;
            double sumQuote = 0.0;
            double sumBuyVolume = 0.0;
            double sumSellVolume = 0.0;
            double sumBuyQuote = 0.0;
            double sumSellQuote = 0.0;

            for (int i = 0; i < n; i++)
            {
                if (highs[i] > rollingHigh) rollingHigh = highs[i];
                if (lows[i] < rollingLow) rollingLow = lows[i];
                sumVolume += volumes[i];
                sumQuote += quoteVolumes[i];
                sumBuyVolume += takerBuyVolumes[i];
                sumSellVolume += takerSellVolumes[i];
                sumBuyQuote += takerBuyQuoteVolumes[i];
                sumSellQuote += takerSellQuoteVolumes[i];
            }

            var rollingRange = rollingHigh - rollingLow;
            if (rollingRange < 1e-12 || sumVolume < 1e-12 || sumQuote < 1e-12 || sumBuyVolume < 1e-12 || sumSellVolume < 1e-12) return false;

            var totalVwap = sumQuote / sumVolume;
            var buyVwap = sumBuyQuote / sumBuyVolume;
            var sellVwap = sumSellQuote / sumSellVolume;

            var asymmetry = ((buyVwap - totalVwap) - (totalVwap - sellVwap)) / rollingRange;
            var imbalance = (sumBuyQuote - sumSellQuote) / sumQuote;

            rawSignal = asymmetry + 0.5 * imbalance;
            rawSignal = Math.Max(-1.0, Math.Min(1.0, rawSignal));
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    high: pd.DataFrame,
    low: pd.DataFrame,
    volume: pd.DataFrame,
    quote_volume: pd.DataFrame,
    taker_buy_volume: pd.DataFrame,
    taker_sell_volume: pd.DataFrame,
    taker_buy_quote_volume: pd.DataFrame,
    taker_sell_quote_volume: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    window = int(params.get("window", 16))
    if window < 2:
        return pd.DataFrame(np.nan, index=close.index, columns=close.columns)

    rolling_high = high.rolling(window, min_periods=window).max()
    rolling_low = low.rolling(window, min_periods=window).min()
    rolling_range = (rolling_high - rolling_low).replace(0.0, np.nan)

    sum_volume = volume.rolling(window, min_periods=window).sum()
    sum_quote = quote_volume.rolling(window, min_periods=window).sum()
    sum_buy_volume = taker_buy_volume.rolling(window, min_periods=window).sum()
    sum_sell_volume = taker_sell_volume.rolling(window, min_periods=window).sum()
    sum_buy_quote = taker_buy_quote_volume.rolling(window, min_periods=window).sum()
    sum_sell_quote = taker_sell_quote_volume.rolling(window, min_periods=window).sum()

    total_vwap = sum_quote / sum_volume.replace(0.0, np.nan)
    buy_vwap = sum_buy_quote / sum_buy_volume.replace(0.0, np.nan)
    sell_vwap = sum_sell_quote / sum_sell_volume.replace(0.0, np.nan)

    asymmetry = ((buy_vwap - total_vwap) - (total_vwap - sell_vwap)) / rolling_range
    imbalance = (sum_buy_quote - sum_sell_quote) / sum_quote.replace(0.0, np.nan)

    signal = (asymmetry + 0.5 * imbalance).clip(-1.0, 1.0)
    valid = rolling_range.notna() & total_vwap.notna() & buy_vwap.notna() & sell_vwap.notna() & imbalance.notna()
    signal = signal.where(valid)
    return signal.reindex_like(close)
