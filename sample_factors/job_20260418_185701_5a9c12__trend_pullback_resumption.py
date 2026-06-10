from typing import Any, Dict

import numpy as np
import pandas as pd

FACTOR_TYPE = "trend_pullback_resumption"

FACTOR_DEFAULT_PARAMS = {
    "trend_window": 48,
    "pullback_window": 8,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "趋势回撤恢复：在中期趋势明确时，只对短期逆向回撤后的顺势恢复给出信号。",
    "__FACTOR_FORMULA__": "signal = long_log * (abs(long_log)/long_path) * max(0, -sign(long_log)*short_log/short_path) * max(0, 1-abs(short_log)/abs(long_log))",
    "__FACTOR_TYPE__": "trend_pullback_resumption",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _trendWindow;\n"
        "        private int _pullbackWindow;\n"
    ),
    "__FACTOR_INIT__": (
        '            _trendWindow = GetIntParameter("trend-window", 48);\n'
        '            _pullbackWindow = GetIntParameter("pullback-window", 8);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] trend_window={_trendWindow} pullback_window={_pullbackWindow}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "Math.Max(_trendWindow, _pullbackWindow) + 1",
    "__EXTRA_BUF_FIELDS__": "",
    "__EXTRA_BUF_ENQUEUE__": "",
    "__EXTRA_BUF_DEQUEUE__": "",
    "__EXTRA_BUF_TOARRAY__": "",
    "__FACTOR_COMPUTE_BODY__": """
            int requiredBars = Math.Max(_trendWindow, _pullbackWindow) + 1;
            var n = prices.Length;
            if (_trendWindow < 2 || _pullbackWindow < 2 || _trendWindow <= _pullbackWindow) return false;
            if (n < requiredBars) return false;

            var last = prices[n - 1];
            var trendBase = prices[n - 1 - _trendWindow];
            var pullbackBase = prices[n - 1 - _pullbackWindow];
            if (last <= 0.0 || trendBase <= 0.0 || pullbackBase <= 0.0) return false;

            var longLog = Math.Log(last / trendBase);
            var shortLog = Math.Log(last / pullbackBase);

            double longPath = 0.0;
            for (int i = n - _trendWindow; i < n; i++)
            {
                var prev = prices[i - 1];
                var curr = prices[i];
                if (prev <= 0.0 || curr <= 0.0) return false;
                longPath += Math.Abs(Math.Log(curr / prev));
            }

            double shortPath = 0.0;
            for (int i = n - _pullbackWindow; i < n; i++)
            {
                var prev = prices[i - 1];
                var curr = prices[i];
                if (prev <= 0.0 || curr <= 0.0) return false;
                shortPath += Math.Abs(Math.Log(curr / prev));
            }

            if (longPath < 1e-12 || shortPath < 1e-12)
            {
                rawSignal = 0.0;
                return true;
            }

            var trendDirection = Math.Sign(longLog);
            if (trendDirection == 0.0)
            {
                rawSignal = 0.0;
                return true;
            }

            var countertrendFraction = Math.Max(0.0, -trendDirection * shortLog / shortPath);
            var continuationGate = Math.Max(0.0, 1.0 - Math.Abs(shortLog) / (Math.Abs(longLog) + 1e-12));
            var trendStrength = longLog * (Math.Abs(longLog) / longPath);

            rawSignal = trendStrength * countertrendFraction * continuationGate;
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    **_kwargs: Any,
) -> pd.DataFrame:
    trend_window = int(params.get("trend_window", 48))
    pullback_window = int(params.get("pullback_window", 8))

    if trend_window < 2 or pullback_window < 2 or trend_window <= pullback_window:
        raise ValueError("Require trend_window > pullback_window >= 2")

    long_log = np.log(close / close.shift(trend_window))
    short_log = np.log(close / close.shift(pullback_window))
    step_log = np.log(close / close.shift(1))

    long_path = step_log.abs().rolling(trend_window).sum()
    short_path = step_log.abs().rolling(pullback_window).sum()

    trend_direction = np.sign(long_log)
    countertrend_fraction = (-trend_direction * short_log / short_path.replace(0.0, np.nan)).clip(lower=0.0)
    continuation_gate = (1.0 - short_log.abs() / (long_log.abs() + 1e-12)).clip(lower=0.0)
    trend_strength = long_log * (long_log.abs() / long_path.replace(0.0, np.nan))

    signal = trend_strength * countertrend_fraction * continuation_gate
    signal = signal.replace([np.inf, -np.inf], np.nan)
    return signal.reindex_like(close)
