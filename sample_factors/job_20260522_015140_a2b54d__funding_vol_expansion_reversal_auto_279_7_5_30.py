import pandas as pd
from typing import Any, Dict

FACTOR_TYPE = "funding_vol_expansion_reversal_auto_279_7_5_30"
FACTOR_DEFAULT_PARAMS = {"window": 14, "short_vol_window": 10, "long_vol_window": 60, "funding_weight": 10000.0, "premium_weight": 100.0}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Crowding reversal that strengthens when short-term volatility expands above its baseline.",
    "__FACTOR_FORMULA__": "signal = -(10000*mean(funding,14)+100*mean(premium,14)) * max(vol10/vol60 - 1,0)",
    "__FACTOR_TYPE__": FACTOR_TYPE,
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _window;\n        private int _shortVolWindow;\n        private int _longVolWindow;\n"
        "        private double _fundingWeight;\n        private double _premiumWeight;\n"
        "        private readonly Queue<double> _fundingBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _premiumBuf = new Queue<double>();\n"
    ),
    "__FACTOR_INIT__": (
        '            _window = GetIntParameter("window", 14);\n'
        '            _shortVolWindow = GetIntParameter("short-vol-window", 10);\n'
        '            _longVolWindow = GetIntParameter("long-vol-window", 60);\n'
        '            _fundingWeight = GetDoubleParameter("funding-weight", 10000.0);\n'
        '            _premiumWeight = GetDoubleParameter("premium-weight", 100.0);\n'
    ),
    "__FACTOR_LOG__": '            Log($"[INIT] window={_window}, shortVol={_shortVolWindow}, longVol={_longVolWindow}");\n',
    "__PRICE_WINDOW_EXPR__": "Math.Max(_window, _longVolWindow) + 1",
    "__EXTRA_BUF_FIELDS__": "",
    "__EXTRA_BUF_ENQUEUE__": "            _fundingBuf.Enqueue(bar.FundingRateClose);\n            _premiumBuf.Enqueue(bar.BinancePremiumIndexClose);\n",
    "__EXTRA_BUF_DEQUEUE__": "            if (_fundingBuf.Count > requiredBars) _fundingBuf.Dequeue();\n            if (_premiumBuf.Count > requiredBars) _premiumBuf.Dequeue();\n",
    "__EXTRA_BUF_TOARRAY__": "            var fundings = _fundingBuf.ToArray();\n            var premiums = _premiumBuf.ToArray();\n",
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < Math.Max(_window, _longVolWindow) + 1) return false;
            double fundingSum = 0.0, premiumSum = 0.0;
            for (int i = n - _window; i < n; i++) { fundingSum += fundings[i]; premiumSum += premiums[i]; }
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
            var crowding = _fundingWeight * fundingSum / _window + _premiumWeight * premiumSum / _window;
            rawSignal = -crowding * Math.Max(shortVol / longVol - 1.0, 0.0);
            return true;
    """,
}

def build_signal(close: pd.DataFrame, params: Dict[str, Any], funding_rate_close: pd.DataFrame, binance_premium_index_close: pd.DataFrame, **_kwargs) -> pd.DataFrame:
    close = close.apply(pd.to_numeric, errors="coerce")
    funding_rate_close = funding_rate_close.apply(pd.to_numeric, errors="coerce")
    binance_premium_index_close = binance_premium_index_close.apply(pd.to_numeric, errors="coerce")
    window = int(params.get("window", 14))
    short_vol_window = int(params.get("short_vol_window", 10))
    long_vol_window = int(params.get("long_vol_window", 60))
    funding_weight = float(params.get("funding_weight", 10000.0))
    premium_weight = float(params.get("premium_weight", 100.0))
    returns = close.pct_change(fill_method=None)
    short_vol = returns.rolling(short_vol_window, min_periods=short_vol_window).std(ddof=0)
    long_vol = returns.rolling(long_vol_window, min_periods=long_vol_window).std(ddof=0)
    vol_expansion = (short_vol / long_vol - 1.0).clip(lower=0.0)
    crowding = funding_weight * funding_rate_close.rolling(window, min_periods=window).mean() + premium_weight * binance_premium_index_close.rolling(window, min_periods=window).mean()
    return (-crowding * vol_expansion).reindex_like(close)
