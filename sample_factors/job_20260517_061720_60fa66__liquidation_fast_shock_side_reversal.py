import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "liquidation_fast_shock_side_reversal"

FACTOR_DEFAULT_PARAMS = {
    "shock_window": 3,
    "baseline_window": 21,
    "panic_amp": 600,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": (
        "Fast liquidation shock-side reversal: short-window liquidation side shock with stronger panic alignment"
    ),
    "__FACTOR_FORMULA__": (
        "side = (recent_long_liq - recent_short_liq)/(recent_long_liq + recent_short_liq); "
        "shock = log(1 + recent_liq_intensity / prior_liq_intensity); signal = side * shock * strong_panic_alignment"
    ),
    "__FACTOR_TYPE__": "liquidation_fast_shock_side_reversal",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _shockWindow;\n"
        "        private int _baselineWindow;\n"
        "        private double _panicAmp;\n"
    ),
    "__FACTOR_INIT__": (
        '            _shockWindow = GetIntParameter("shock-window", 3);\n'
        '            _baselineWindow = GetIntParameter("baseline-window", 21);\n'
        '            _panicAmp = GetDoubleParameter("panic-amp", 600.0) / 100.0;\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] shock_window={_shockWindow} baseline_window={_baselineWindow} panic_amp={_panicAmp}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_baselineWindow",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _longLiqBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _shortLiqBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _quoteVolumeBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _longLiqBuf.Enqueue(bar.LiquidationLongUsd);\n"
        "            _shortLiqBuf.Enqueue(bar.LiquidationShortUsd);\n"
        "            _quoteVolumeBuf.Enqueue(bar.QuoteVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_longLiqBuf.Count > requiredBars) _longLiqBuf.Dequeue();\n"
        "            if (_shortLiqBuf.Count > requiredBars) _shortLiqBuf.Dequeue();\n"
        "            if (_quoteVolumeBuf.Count > requiredBars) _quoteVolumeBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var longLiqs = _longLiqBuf.ToArray();\n"
        "            var shortLiqs = _shortLiqBuf.ToArray();\n"
        "            var quoteVolumes = _quoteVolumeBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < _baselineWindow || _shockWindow >= _baselineWindow) return false;
            var recentStart = n - _shockWindow;

            double recentLong = 0.0, recentShort = 0.0, recentQuote = 0.0;
            double priorLong = 0.0, priorShort = 0.0, priorQuote = 0.0;
            for (int i = 0; i < n; i++)
            {
                if (i >= recentStart)
                {
                    recentLong += longLiqs[i];
                    recentShort += shortLiqs[i];
                    recentQuote += quoteVolumes[i];
                }
                else
                {
                    priorLong += longLiqs[i];
                    priorShort += shortLiqs[i];
                    priorQuote += quoteVolumes[i];
                }
            }

            var recentTotal = recentLong + recentShort;
            var priorTotal = priorLong + priorShort;
            if (recentTotal <= 0.0 || recentQuote <= 0.0 || priorQuote <= 0.0) return false;
            if (prices[recentStart] <= 0.0 || prices[n - 1] <= 0.0) return false;

            var side = (recentLong - recentShort) / (recentTotal + 1e-12);
            var recentIntensity = recentTotal / recentQuote;
            var priorIntensity = priorTotal / priorQuote;
            var shock = Math.Log(1.0 + recentIntensity / (priorIntensity + 1e-8));
            var priceMove = Math.Log(prices[n - 1] / prices[recentStart]);
            var alignedPanic = side >= 0.0 ? -priceMove : priceMove;
            var boost = 1.0 + Math.Min(3.0, Math.Max(0.0, alignedPanic) * _panicAmp);
            rawSignal = side * shock * boost;
            return true;
""",
}


def _to_float_frame(x: pd.DataFrame) -> pd.DataFrame:
    return x.apply(pd.to_numeric, errors="coerce")


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    liquidation_long_usd: pd.DataFrame,
    liquidation_short_usd: pd.DataFrame,
    quote_volume: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    shock_window = int(params.get("shock_window", 3))
    baseline_window = int(params.get("baseline_window", 21))
    panic_amp = float(params.get("panic_amp", 600.0)) / 100.0

    close = _to_float_frame(close)
    liquidation_long_usd = _to_float_frame(liquidation_long_usd)
    liquidation_short_usd = _to_float_frame(liquidation_short_usd)
    quote_volume = _to_float_frame(quote_volume)

    total_liq = liquidation_long_usd + liquidation_short_usd
    recent_long = liquidation_long_usd.rolling(shock_window, min_periods=shock_window).sum()
    recent_short = liquidation_short_usd.rolling(shock_window, min_periods=shock_window).sum()
    recent_total = total_liq.rolling(shock_window, min_periods=shock_window).sum()
    recent_quote = quote_volume.rolling(shock_window, min_periods=shock_window).sum()

    baseline_total = total_liq.rolling(baseline_window, min_periods=baseline_window).sum()
    baseline_quote = quote_volume.rolling(baseline_window, min_periods=baseline_window).sum()
    prior_total = baseline_total - recent_total
    prior_quote = baseline_quote - recent_quote

    side = (recent_long - recent_short) / (recent_total + 1e-12)
    recent_intensity = recent_total / recent_quote.replace(0.0, np.nan)
    prior_intensity = prior_total / prior_quote.replace(0.0, np.nan)
    shock = np.log1p(recent_intensity / (prior_intensity + 1e-8))
    price_move = np.log(close / close.shift(shock_window - 1))
    aligned_panic = price_move.where(side < 0.0, -price_move)
    boost = 1.0 + (aligned_panic.clip(lower=0.0) * panic_amp).clip(upper=3.0)
    signal = side * shock * boost
    signal = signal.mask(recent_total <= 0.0).mask(recent_quote <= 0.0).mask(prior_quote <= 0.0)
    return signal.reindex_like(close)
