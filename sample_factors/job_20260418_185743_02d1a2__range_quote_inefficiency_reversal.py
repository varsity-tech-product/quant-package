import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "range_quote_inefficiency_reversal"

FACTOR_DEFAULT_PARAMS = {
    "window": 24,
    "clip": 3.0,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "价格扩张与成交额参与度错配：价格波动扩张大于 quote volume 扩张时，倾向反转；反之顺势。",
    "__FACTOR_FORMULA__": "body=(close-open)/(high-low); ineff=clip((high-low)/avg_range - quote_volume/avg_quote, -clip, clip); signal=-body*ineff/clip",
    "__FACTOR_TYPE__": "range_quote_inefficiency_reversal",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _window;\n"
        "        private double _clip;\n"
    ),
    "__FACTOR_INIT__": (
        '            _window = GetIntParameter("window", 24);\n'
        '            _clip = GetDoubleParameter("clip", 3.0);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] window={_window} clip={_clip}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_window",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _openBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _highBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _lowBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _quoteVolumeBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _openBuf.Enqueue((double)bar.Open);\n"
        "            _highBuf.Enqueue((double)bar.High);\n"
        "            _lowBuf.Enqueue((double)bar.Low);\n"
        "            _quoteVolumeBuf.Enqueue(bar.QuoteVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_openBuf.Count > requiredBars) _openBuf.Dequeue();\n"
        "            if (_highBuf.Count > requiredBars) _highBuf.Dequeue();\n"
        "            if (_lowBuf.Count > requiredBars) _lowBuf.Dequeue();\n"
        "            if (_quoteVolumeBuf.Count > requiredBars) _quoteVolumeBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var opens = _openBuf.ToArray();\n"
        "            var highs = _highBuf.ToArray();\n"
        "            var lows = _lowBuf.ToArray();\n"
        "            var quoteVolumes = _quoteVolumeBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (_window <= 0 || n < _window) return false;

            double rangeSum = 0.0;
            double quoteSum = 0.0;
            for (int i = 0; i < n; i++)
            {
                rangeSum += Math.Max(highs[i] - lows[i], 0.0);
                quoteSum += quoteVolumes[i];
            }

            var avgRange = rangeSum / n;
            var avgQuote = quoteSum / n;
            var currentRange = highs[n - 1] - lows[n - 1];
            if (avgRange < 1e-12 || avgQuote < 1e-12 || currentRange < 1e-12)
            {
                rawSignal = 0.0;
                return true;
            }

            var bodyFrac = (prices[n - 1] - opens[n - 1]) / currentRange;
            var rangeRatio = currentRange / avgRange;
            var quoteRatio = quoteVolumes[n - 1] / avgQuote;
            var inefficiency = rangeRatio - quoteRatio;
            var scale = Math.Max(Math.Abs(_clip), 1e-6);

            if (inefficiency > scale) inefficiency = scale;
            else if (inefficiency < -scale) inefficiency = -scale;

            rawSignal = -bodyFrac * inefficiency / scale;
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    open: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    quote_volume: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    window = max(1, int(params.get("window", 24)))
    clip = float(params.get("clip", 3.0))
    scale = max(abs(clip), 1e-6)

    bar_range = (high - low).clip(lower=0.0)
    avg_range = bar_range.rolling(window, min_periods=window).mean()
    avg_quote = quote_volume.rolling(window, min_periods=window).mean()

    body_frac = (close - open) / bar_range.replace(0.0, np.nan)
    range_ratio = bar_range / avg_range.replace(0.0, np.nan)
    quote_ratio = quote_volume / avg_quote.replace(0.0, np.nan)
    inefficiency = (range_ratio - quote_ratio).clip(lower=-scale, upper=scale)

    signal = -body_frac * inefficiency / scale
    valid = avg_range.notna() & avg_quote.notna() & bar_range.gt(0.0)
    signal = signal.where(valid)
    return signal.reindex_like(close)
