import pandas as pd
from typing import Any, Dict

FACTOR_TYPE = "trend_vol_expansion_flow_40_14_90_20"
FACTOR_DEFAULT_PARAMS = {"trend_window": 20, "short_vol_window": 10, "long_vol_window": 60, "flow_window": 14}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Trend continuation gated by volatility expansion and aggressive taker-flow confirmation.",
    "__FACTOR_FORMULA__": "signal = ret20 * max(vol10/vol60 - 1,0) * flow_pressure14",
    "__FACTOR_TYPE__": FACTOR_TYPE,
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _trendWindow;\n"
        "        private int _shortVolWindow;\n"
        "        private int _longVolWindow;\n"
        "        private int _flowWindow;\n"
        "        private readonly Queue<double> _buyBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _sellBuf = new Queue<double>();\n"
    ),
    "__FACTOR_INIT__": (
        '            _trendWindow = GetIntParameter("trend-window", 20);\n'
        '            _shortVolWindow = GetIntParameter("short-vol-window", 10);\n'
        '            _longVolWindow = GetIntParameter("long-vol-window", 60);\n'
        '            _flowWindow = GetIntParameter("flow-window", 14);\n'
    ),
    "__FACTOR_LOG__": '            Log($"[INIT] trend={_trendWindow}, shortVol={_shortVolWindow}, longVol={_longVolWindow}, flow={_flowWindow}");\n',
    "__PRICE_WINDOW_EXPR__": "Math.Max(Math.Max(_trendWindow, _longVolWindow), _flowWindow) + 1",
    "__EXTRA_BUF_FIELDS__": "",
    "__EXTRA_BUF_ENQUEUE__": "            _buyBuf.Enqueue(bar.TakerBuyVolume);\n            _sellBuf.Enqueue(bar.TakerSellVolume);\n",
    "__EXTRA_BUF_DEQUEUE__": "            if (_buyBuf.Count > requiredBars) _buyBuf.Dequeue();\n            if (_sellBuf.Count > requiredBars) _sellBuf.Dequeue();\n",
    "__EXTRA_BUF_TOARRAY__": "            var buys = _buyBuf.ToArray();\n            var sells = _sellBuf.ToArray();\n",
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < Math.Max(Math.Max(_trendWindow, _longVolWindow), _flowWindow) + 1) return false;
            var basePrice = prices[n - 1 - _trendWindow];
            if (Math.Abs(basePrice) < 1e-12) return false;
            var trend = (prices[n - 1] - basePrice) / Math.Abs(basePrice);
            double shortSum = 0.0, shortSumSq = 0.0, longSum = 0.0, longSumSq = 0.0;
            for (int i = n - _shortVolWindow; i < n; i++) {
                var prev = prices[i - 1]; if (Math.Abs(prev) < 1e-12) return false;
                var r = (prices[i] - prev) / Math.Abs(prev); shortSum += r; shortSumSq += r * r;
            }
            for (int i = n - _longVolWindow; i < n; i++) {
                var prev = prices[i - 1]; if (Math.Abs(prev) < 1e-12) return false;
                var r = (prices[i] - prev) / Math.Abs(prev); longSum += r; longSumSq += r * r;
            }
            var shortMean = shortSum / _shortVolWindow;
            var longMean = longSum / _longVolWindow;
            var shortVol = Math.Sqrt(Math.Max(shortSumSq / _shortVolWindow - shortMean * shortMean, 0.0));
            var longVol = Math.Sqrt(Math.Max(longSumSq / _longVolWindow - longMean * longMean, 0.0));
            if (longVol < 1e-12) return false;
            double buySum = 0.0, sellSum = 0.0;
            for (int i = n - _flowWindow; i < n; i++) { buySum += buys[i]; sellSum += sells[i]; }
            var flow = (buySum - sellSum) / (buySum + sellSum + 1e-6);
            rawSignal = trend * Math.Max(shortVol / longVol - 1.0, 0.0) * flow;
            return true;
    """,
}

def build_signal(close: pd.DataFrame, params: Dict[str, Any], taker_buy_volume: pd.DataFrame, taker_sell_volume: pd.DataFrame, **_kwargs) -> pd.DataFrame:
    close = close.apply(pd.to_numeric, errors="coerce")
    taker_buy_volume = taker_buy_volume.apply(pd.to_numeric, errors="coerce")
    taker_sell_volume = taker_sell_volume.apply(pd.to_numeric, errors="coerce")
    trend_window = int(params.get("trend_window", 20))
    short_vol_window = int(params.get("short_vol_window", 10))
    long_vol_window = int(params.get("long_vol_window", 60))
    flow_window = int(params.get("flow_window", 14))
    returns = close.pct_change(fill_method=None)
    trend = (close - close.shift(trend_window)) / close.shift(trend_window).abs()
    short_vol = returns.rolling(short_vol_window, min_periods=short_vol_window).std(ddof=0)
    long_vol = returns.rolling(long_vol_window, min_periods=long_vol_window).std(ddof=0)
    vol_expansion = (short_vol / long_vol - 1.0).clip(lower=0.0)
    buy_sum = taker_buy_volume.rolling(flow_window, min_periods=flow_window).sum()
    sell_sum = taker_sell_volume.rolling(flow_window, min_periods=flow_window).sum()
    flow = (buy_sum - sell_sum) / (buy_sum + sell_sum + 1e-6)
    return (trend * vol_expansion * flow).reindex_like(close)
