import numpy as np
import pandas as pd
from typing import Any, Dict

FACTOR_TYPE = "auto_aggressive_slippage_alignment_v2_20260419i"

FACTOR_DEFAULT_PARAMS = {
    "short_window": 6,
    "long_window": 24,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "主动成交滑点一致性增强：保留滑点压力强度，仅在收盘接受度与单笔成交规模同向时放大，并用短长窗差分筛选新鲜冲击。",
    "__FACTOR_FORMULA__": "base=tanh(((buy_px-sell_px)/(high-low))*participation); active=clip((buy_quote+sell_quote)/quote_volume,0.05,2.5); size_edge=tanh(log((buy_quote/buy_trades+1)/(sell_quote/sell_trades+1))); clv=((2*close)-high-low)/(high-low); conviction=sqrt(active)*(1+0.9*max(base*clv,0)+0.45*max(base*size_edge,0))/(1+0.8*max(-(base*clv),0)+0.35*max(-(base*size_edge),0)); bar_score=tanh(base*conviction); signal=tanh((mean(bar_score,s)-0.3*mean(bar_score,l))*sqrt(mean(active,s)/mean(active,l))*(0.75+same_sign_ratio(bar_score,s)))",
    "__FACTOR_TYPE__": "auto_aggressive_slippage_alignment_v2_20260419i",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _shortWindow;\n"
        "        private int _longWindow;\n"
    ),
    "__FACTOR_INIT__": (
        '            _shortWindow = GetIntParameter("short-window", 6);\n'
        '            _longWindow = GetIntParameter("long-window", 24);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] short_window={_shortWindow} long_window={_longWindow}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "Math.Max(_longWindow, _shortWindow)",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _highBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _lowBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _quoteVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerBuyTradesBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellTradesBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _highBuf.Enqueue((double)bar.High);\n"
        "            _lowBuf.Enqueue((double)bar.Low);\n"
        "            _quoteVolumeBuf.Enqueue(bar.QuoteVolume);\n"
        "            _takerBuyVolumeBuf.Enqueue(bar.TakerBuyVolume);\n"
        "            _takerSellVolumeBuf.Enqueue(bar.TakerSellVolume);\n"
        "            _takerBuyQuoteBuf.Enqueue(bar.TakerBuyQuoteVolume);\n"
        "            _takerSellQuoteBuf.Enqueue(bar.TakerSellQuoteVolume);\n"
        "            _takerBuyTradesBuf.Enqueue(bar.TakerBuyTrades);\n"
        "            _takerSellTradesBuf.Enqueue(bar.TakerSellTrades);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_highBuf.Count > requiredBars) _highBuf.Dequeue();\n"
        "            if (_lowBuf.Count > requiredBars) _lowBuf.Dequeue();\n"
        "            if (_quoteVolumeBuf.Count > requiredBars) _quoteVolumeBuf.Dequeue();\n"
        "            if (_takerBuyVolumeBuf.Count > requiredBars) _takerBuyVolumeBuf.Dequeue();\n"
        "            if (_takerSellVolumeBuf.Count > requiredBars) _takerSellVolumeBuf.Dequeue();\n"
        "            if (_takerBuyQuoteBuf.Count > requiredBars) _takerBuyQuoteBuf.Dequeue();\n"
        "            if (_takerSellQuoteBuf.Count > requiredBars) _takerSellQuoteBuf.Dequeue();\n"
        "            if (_takerBuyTradesBuf.Count > requiredBars) _takerBuyTradesBuf.Dequeue();\n"
        "            if (_takerSellTradesBuf.Count > requiredBars) _takerSellTradesBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var highs = _highBuf.ToArray();\n"
        "            var lows = _lowBuf.ToArray();\n"
        "            var quoteVolumes = _quoteVolumeBuf.ToArray();\n"
        "            var takerBuyVolumes = _takerBuyVolumeBuf.ToArray();\n"
        "            var takerSellVolumes = _takerSellVolumeBuf.ToArray();\n"
        "            var takerBuyQuotes = _takerBuyQuoteBuf.ToArray();\n"
        "            var takerSellQuotes = _takerSellQuoteBuf.ToArray();\n"
        "            var takerBuyTrades = _takerBuyTradesBuf.ToArray();\n"
        "            var takerSellTrades = _takerSellTradesBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var shortWindow = Math.Max(_shortWindow, 2);
            var longWindow = Math.Max(_longWindow, shortWindow);
            var n = prices.Length;
            if (n < longWindow) return false;

            var requiredLong = Math.Max(10, (longWindow + 1) / 2);
            var requiredShort = Math.Max(3, (shortWindow + 1) / 2);

            var barScores = new double[n];
            var activeShares = new double[n];
            var validFlags = new bool[n];

            for (int i = 0; i < n; i++)
            {
                var range = highs[i] - lows[i];
                var totalQuote = takerBuyQuotes[i] + takerSellQuotes[i];
                var buyVolume = takerBuyVolumes[i];
                var sellVolume = takerSellVolumes[i];

                if (Math.Abs(range) < 1e-12 || totalQuote < 1e-12 || buyVolume < 1e-12 || sellVolume < 1e-12)
                {
                    continue;
                }

                var buyPx = takerBuyQuotes[i] / buyVolume;
                var sellPx = takerSellQuotes[i] / sellVolume;
                var slip = (buyPx - sellPx) / range;
                var participation = (takerBuyQuotes[i] - takerSellQuotes[i]) / totalQuote;
                var baseSignal = Math.Tanh(slip * participation);

                var quoteVolume = quoteVolumes[i];
                var activeShare = quoteVolume > 1e-12 ? totalQuote / quoteVolume : 0.05;
                activeShare = Math.Max(0.05, Math.Min(2.5, activeShare));

                var buyTrades = takerBuyTrades[i] > 1.0 ? takerBuyTrades[i] : 1.0;
                var sellTrades = takerSellTrades[i] > 1.0 ? takerSellTrades[i] : 1.0;
                var buySize = takerBuyQuotes[i] / buyTrades;
                var sellSize = takerSellQuotes[i] / sellTrades;
                var sizeEdge = Math.Tanh(Math.Log((buySize + 1.0) / (sellSize + 1.0)));

                var clv = ((2.0 * prices[i]) - highs[i] - lows[i]) / range;
                var acceptanceAlign = Math.Max(baseSignal * clv, 0.0);
                var sizeAlign = Math.Max(baseSignal * sizeEdge, 0.0);
                var acceptanceConflict = Math.Max(-(baseSignal * clv), 0.0);
                var sizeConflict = Math.Max(-(baseSignal * sizeEdge), 0.0);

                var conviction = Math.Sqrt(activeShare)
                    * (1.0 + 0.9 * acceptanceAlign + 0.45 * sizeAlign)
                    / (1.0 + 0.8 * acceptanceConflict + 0.35 * sizeConflict);

                barScores[i] = Math.Tanh(baseSignal * conviction);
                activeShares[i] = activeShare;
                validFlags[i] = true;
            }

            double longScoreSum = 0.0;
            double longActiveSum = 0.0;
            int longValid = 0;
            double shortScoreSum = 0.0;
            double shortActiveSum = 0.0;
            int shortValid = 0;

            for (int i = 0; i < n; i++)
            {
                if (!validFlags[i]) continue;

                longScoreSum += barScores[i];
                longActiveSum += activeShares[i];
                longValid += 1;

                if (i >= n - shortWindow)
                {
                    shortScoreSum += barScores[i];
                    shortActiveSum += activeShares[i];
                    shortValid += 1;
                }
            }

            if (longValid < requiredLong || shortValid < requiredShort) return false;

            var shortMean = shortScoreSum / shortValid;
            var longMean = longScoreSum / longValid;
            var shortActiveMean = shortActiveSum / shortValid;
            var longActiveMean = longActiveSum / longValid;
            var activityRatio = shortActiveMean / (longActiveMean + 1e-6);
            activityRatio = Math.Max(0.67, Math.Min(1.8, activityRatio));

            double consistency = 0.5;
            if (Math.Abs(shortMean) >= 1e-12)
            {
                int sameSign = 0;
                for (int i = n - shortWindow; i < n; i++)
                {
                    if (!validFlags[i]) continue;
                    if (Math.Sign(barScores[i]) == Math.Sign(shortMean))
                    {
                        sameSign += 1;
                    }
                }
                consistency = (double)sameSign / shortValid;
            }

            rawSignal = Math.Tanh(
                (shortMean - 0.3 * longMean)
                * Math.Sqrt(activityRatio)
                * (0.75 + consistency)
            );
            return true;
""",
}


def _align_like_close(close: pd.DataFrame, frame: pd.DataFrame) -> pd.DataFrame:
    return frame.reindex(index=close.index, columns=close.columns)


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    high: pd.DataFrame,
    low: pd.DataFrame,
    quote_volume: pd.DataFrame,
    taker_buy_volume: pd.DataFrame,
    taker_sell_volume: pd.DataFrame,
    taker_buy_quote_volume: pd.DataFrame,
    taker_sell_quote_volume: pd.DataFrame,
    taker_buy_trades: pd.DataFrame,
    taker_sell_trades: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    short_window = max(2, int(params.get("short_window", 6)))
    long_window = max(int(params.get("long_window", 24)), short_window)
    required_long = max(10, (long_window + 1) // 2)
    required_short = max(3, (short_window + 1) // 2)

    high = _align_like_close(close, high)
    low = _align_like_close(close, low)
    quote_volume = _align_like_close(close, quote_volume)
    taker_buy_volume = _align_like_close(close, taker_buy_volume)
    taker_sell_volume = _align_like_close(close, taker_sell_volume)
    taker_buy_quote_volume = _align_like_close(close, taker_buy_quote_volume)
    taker_sell_quote_volume = _align_like_close(close, taker_sell_quote_volume)
    taker_buy_trades = _align_like_close(close, taker_buy_trades)
    taker_sell_trades = _align_like_close(close, taker_sell_trades)

    bar_range = high - low
    total_quote = taker_buy_quote_volume + taker_sell_quote_volume
    valid = (
        (bar_range.abs() > 1e-12)
        & (total_quote.abs() > 1e-12)
        & (taker_buy_volume.abs() > 1e-12)
        & (taker_sell_volume.abs() > 1e-12)
    )

    buy_px = taker_buy_quote_volume.divide(taker_buy_volume.where(valid))
    sell_px = taker_sell_quote_volume.divide(taker_sell_volume.where(valid))
    slip = (buy_px - sell_px).divide(bar_range.where(valid))
    participation = (taker_buy_quote_volume - taker_sell_quote_volume).divide(total_quote.where(valid))
    base_signal = np.tanh((slip * participation).replace([np.inf, -np.inf], np.nan)).where(valid)

    active_share = total_quote.divide(quote_volume.where(quote_volume.abs() > 1e-12))
    active_share = active_share.clip(lower=0.05, upper=2.5).where(valid)

    buy_size = taker_buy_quote_volume / taker_buy_trades.clip(lower=1.0)
    sell_size = taker_sell_quote_volume / taker_sell_trades.clip(lower=1.0)
    size_edge = np.tanh(np.log((buy_size + 1.0) / (sell_size + 1.0)))

    clv = ((2.0 * close) - high - low).divide(bar_range.where(valid))
    acceptance_align = (base_signal * clv).clip(lower=0.0)
    size_align = (base_signal * size_edge).clip(lower=0.0)
    acceptance_conflict = (-(base_signal * clv)).clip(lower=0.0)
    size_conflict = (-(base_signal * size_edge)).clip(lower=0.0)

    conviction = (
        np.sqrt(active_share)
        * (1.0 + 0.9 * acceptance_align + 0.45 * size_align)
        / (1.0 + 0.8 * acceptance_conflict + 0.35 * size_conflict)
    )
    bar_score = np.tanh(base_signal * conviction).where(valid)

    long_mean = bar_score.rolling(long_window, min_periods=required_long).mean()
    short_mean = bar_score.rolling(short_window, min_periods=required_short).mean()

    long_active_mean = active_share.rolling(long_window, min_periods=required_long).mean()
    short_active_mean = active_share.rolling(short_window, min_periods=required_short).mean()
    activity_ratio = (short_active_mean / (long_active_mean + 1e-6)).clip(lower=0.67, upper=1.8)

    same_sign = pd.DataFrame(np.nan, index=close.index, columns=close.columns, dtype=float)
    recent_sign = np.sign(short_mean)
    consistent_mask = valid & recent_sign.ne(0.0)
    same_sign[consistent_mask] = (
        np.sign(bar_score[consistent_mask]) == recent_sign[consistent_mask]
    ).astype(float)
    consistency = same_sign.rolling(short_window, min_periods=required_short).mean().fillna(0.5)
    consistency = consistency.where(short_mean.notna())

    raw = (
        (short_mean - 0.3 * long_mean).to_numpy()
        * np.sqrt(activity_ratio.to_numpy())
        * (0.75 + consistency.to_numpy())
    )
    signal = pd.DataFrame(np.tanh(raw), index=close.index, columns=close.columns)

    mask = (
        short_mean.isna()
        | long_mean.isna()
        | short_active_mean.isna()
        | long_active_mean.isna()
    )
    signal = signal.mask(mask)
    return signal.reindex_like(close)
