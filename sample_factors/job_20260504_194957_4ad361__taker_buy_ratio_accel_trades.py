import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "taker_buy_ratio_accel_trades"

FACTOR_DEFAULT_PARAMS = {
    "ratio_window": 12,
    "delta_window": 4,
    "trades_window": 24,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "主动买入占比的加速度信号，并用主动成交笔数活跃度确认",
    "__FACTOR_FORMULA__": "signal=tanh((ma(buy_ratio,w)-ma(buy_ratio,w).shift(d))/std)*trade_activity",
    "__FACTOR_TYPE__": "taker_buy_ratio_accel_trades",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _ratioWindow;\n"
        "        private int _deltaWindow;\n"
        "        private int _tradesWindow;\n"
    ),
    "__FACTOR_INIT__": (
        '            _ratioWindow = GetIntParameter("ratio-window", 12);\n'
        '            _deltaWindow = GetIntParameter("delta-window", 4);\n'
        '            _tradesWindow = GetIntParameter("trades-window", 24);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] ratio_window={_ratioWindow} delta_window={_deltaWindow} trades_window={_tradesWindow}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_ratioWindow + _deltaWindow + _tradesWindow",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _takerBuyBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyTradesBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellTradesBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _takerBuyBuf.Enqueue(bar.TakerBuyVolume);\n"
        "            _takerSellBuf.Enqueue(bar.TakerSellVolume);\n"
        "            _takerBuyTradesBuf.Enqueue(bar.TakerBuyTrades);\n"
        "            _takerSellTradesBuf.Enqueue(bar.TakerSellTrades);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_takerBuyBuf.Count > requiredBars) _takerBuyBuf.Dequeue();\n"
        "            if (_takerSellBuf.Count > requiredBars) _takerSellBuf.Dequeue();\n"
        "            if (_takerBuyTradesBuf.Count > requiredBars) _takerBuyTradesBuf.Dequeue();\n"
        "            if (_takerSellTradesBuf.Count > requiredBars) _takerSellTradesBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var takerBuys = _takerBuyBuf.ToArray();\n"
        "            var takerSells = _takerSellBuf.ToArray();\n"
        "            var takerBuyTrades = _takerBuyTradesBuf.ToArray();\n"
        "            var takerSellTrades = _takerSellTradesBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            var required = _ratioWindow + _deltaWindow + _tradesWindow;
            if (n < required) return false;

            double recent = 0.0;
            double previous = 0.0;
            for (int i = n - _ratioWindow; i < n; i++)
            {
                var total = takerBuys[i] + takerSells[i];
                recent += total > 1e-12 ? takerBuys[i] / total : 0.5;
            }
            for (int i = n - _ratioWindow - _deltaWindow; i < n - _deltaWindow; i++)
            {
                var total = takerBuys[i] + takerSells[i];
                previous += total > 1e-12 ? takerBuys[i] / total : 0.5;
            }
            var ratioDelta = recent / _ratioWindow - previous / _ratioWindow;

            double ratioSum = 0.0;
            double ratioSq = 0.0;
            double tradesSum = 0.0;
            for (int i = n - _tradesWindow; i < n; i++)
            {
                var total = takerBuys[i] + takerSells[i];
                var ratio = total > 1e-12 ? takerBuys[i] / total : 0.5;
                ratioSum += ratio;
                ratioSq += ratio * ratio;
                tradesSum += takerBuyTrades[i] + takerSellTrades[i];
            }
            var ratioMean = ratioSum / _tradesWindow;
            var ratioStd = Math.Sqrt(Math.Max(ratioSq / _tradesWindow - ratioMean * ratioMean, 1e-8));
            var latestTrades = takerBuyTrades[n - 1] + takerSellTrades[n - 1];
            var avgTrades = Math.Max(tradesSum / _tradesWindow, 1e-8);
            var activity = Math.Min(latestTrades / avgTrades, 2.5) / 2.5;

            rawSignal = Math.Tanh(ratioDelta / ratioStd) * activity;
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    taker_buy_volume: pd.DataFrame,
    taker_sell_volume: pd.DataFrame,
    taker_buy_trades: pd.DataFrame,
    taker_sell_trades: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    ratio_window = int(params.get("ratio_window", 12))
    delta_window = int(params.get("delta_window", 4))
    trades_window = int(params.get("trades_window", 24))

    total = taker_buy_volume + taker_sell_volume
    ratio = taker_buy_volume / total.where(total.abs() > 1e-12)
    ratio = ratio.fillna(0.5)

    recent = ratio.rolling(ratio_window, min_periods=ratio_window).mean()
    previous = recent.shift(delta_window)
    ratio_std = ratio.rolling(trades_window, min_periods=trades_window).std(ddof=0)

    trades = taker_buy_trades + taker_sell_trades
    avg_trades = trades.rolling(trades_window, min_periods=trades_window).mean()
    activity = (trades / avg_trades.replace(0.0, np.nan)).clip(lower=0.0, upper=2.5) / 2.5

    signal = np.tanh((recent - previous) / ratio_std.replace(0.0, np.nan)) * activity
    return signal.reindex_like(close)
