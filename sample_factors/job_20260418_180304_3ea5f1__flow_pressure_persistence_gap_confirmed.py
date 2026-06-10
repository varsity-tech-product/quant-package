import numpy as np
import pandas as pd
from typing import Any, Dict

FACTOR_TYPE = "flow_pressure_persistence_gap_confirmed"

FACTOR_DEFAULT_PARAMS = {
    "flow_window": 24,
    "confirm_window": 6,
    "surprise_window": 72,
    "impact_window": 8,
    "residual_cap": 1.5,
    "clip": 2.0,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "主动成交额持续失衡且近期同向确认、同向加速，同时价格尚未充分兑现该压力时，顺着残余压力方向交易。",
    "__FACTOR_FORMULA__": "signal=tanh(imbalance_mean/0.10)*sqrt(persistence*confirmation)*acceleration*surprise_gate*residual_gap*clip",
    "__FACTOR_TYPE__": "flow_pressure_persistence_gap_confirmed",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _flowWindow;\n"
        "        private int _confirmWindow;\n"
        "        private int _surpriseWindow;\n"
        "        private int _impactWindow;\n"
        "        private double _residualCap;\n"
        "        private double _clip;\n"
    ),
    "__FACTOR_INIT__": (
        '            _flowWindow = GetIntParameter("flow-window", 24);\n'
        '            _confirmWindow = GetIntParameter("confirm-window", 6);\n'
        '            _surpriseWindow = GetIntParameter("surprise-window", 72);\n'
        '            _impactWindow = GetIntParameter("impact-window", 8);\n'
        '            _residualCap = GetDoubleParameter("residual-cap", 1.5);\n'
        '            _clip = GetDoubleParameter("clip", 2.0);\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] flow_window={_flowWindow} confirm_window={_confirmWindow} surprise_window={_surpriseWindow} impact_window={_impactWindow} residual_cap={_residualCap} clip={_clip}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "Math.Max(Math.Max(_surpriseWindow, _flowWindow), _impactWindow + 1)",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _takerBuyQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _takerSellQuoteBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _takerBuyQuoteBuf.Enqueue(bar.TakerBuyQuoteVolume);\n"
        "            _takerSellQuoteBuf.Enqueue(bar.TakerSellQuoteVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_takerBuyQuoteBuf.Count > requiredBars) _takerBuyQuoteBuf.Dequeue();\n"
        "            if (_takerSellQuoteBuf.Count > requiredBars) _takerSellQuoteBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var takerBuyQuotes = _takerBuyQuoteBuf.ToArray();\n"
        "            var takerSellQuotes = _takerSellQuoteBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var flowWindow = Math.Max(4, _flowWindow);
            var confirmWindow = Math.Max(2, Math.Min(_confirmWindow, flowWindow / 2));
            var surpriseWindow = Math.Max(flowWindow, _surpriseWindow);
            var impactWindow = Math.Max(1, _impactWindow);
            var n = prices.Length;
            if (n < surpriseWindow || n < impactWindow + 1) return false;

            double imbalanceSum = 0.0;
            double imbalanceAbsSum = 0.0;
            double confirmSum = 0.0;
            double confirmAbsSum = 0.0;
            double totalQuoteFlowSum = 0.0;
            double totalQuoteSurpriseSum = 0.0;
            int confirmStart = n - confirmWindow;
            int flowStart = n - flowWindow;
            for (int i = n - surpriseWindow; i < n; i++)
            {
                var totalQuote = takerBuyQuotes[i] + takerSellQuotes[i];
                totalQuoteSurpriseSum += totalQuote;
                if (i < flowStart) continue;

                totalQuoteFlowSum += totalQuote;
                var imbalance = totalQuote > 1e-12 ? (takerBuyQuotes[i] - takerSellQuotes[i]) / totalQuote : 0.0;
                imbalanceSum += imbalance;
                imbalanceAbsSum += Math.Abs(imbalance);

                if (i >= confirmStart)
                {
                    confirmSum += imbalance;
                    confirmAbsSum += Math.Abs(imbalance);
                }
            }

            var imbalanceMean = imbalanceSum / flowWindow;
            var imbalanceAbsMean = imbalanceAbsSum / flowWindow;
            if (imbalanceAbsMean < 1e-12) return false;

            var persistence = Math.Min(1.0, Math.Abs(imbalanceMean) / imbalanceAbsMean);
            var flowStrength = Math.Tanh(imbalanceMean / 0.10);

            var confirmMean = confirmSum / confirmWindow;
            var confirmAbsMean = confirmAbsSum / confirmWindow;
            if (confirmAbsMean < 1e-12) return false;

            var direction = Math.Sign(imbalanceMean);
            if (direction == 0.0) return false;

            var confirmation = direction * confirmMean / confirmAbsMean;
            confirmation = Math.Max(0.0, Math.Min(1.0, confirmation));

            var priorDenom = Math.Max(flowWindow - confirmWindow, 1);
            var priorMean = (imbalanceSum - confirmSum) / priorDenom;
            var acceleration = direction * (confirmMean - priorMean) / 0.08;
            acceleration = Math.Max(0.0, Math.Min(1.0, acceleration));

            var avgFlowQuote = totalQuoteFlowSum / flowWindow;
            var avgSurpriseQuote = totalQuoteSurpriseSum / surpriseWindow;
            if (avgSurpriseQuote < 1e-12) return false;

            var surprise = avgFlowQuote / avgSurpriseQuote - 1.0;
            if (surprise < 0.0) surprise = 0.0;
            var surpriseGate = 0.5 + 0.5 * Math.Tanh(surprise);

            double absRetSum = 0.0;
            for (int i = n - impactWindow; i < n; i++)
            {
                var prevPrice = prices[i - 1];
                if (Math.Abs(prevPrice) < 1e-12) continue;
                absRetSum += Math.Abs(prices[i] / prevPrice - 1.0);
            }

            var basePrice = prices[n - impactWindow - 1];
            if (Math.Abs(basePrice) < 1e-12) return false;

            var priceMove = prices[n - 1] / basePrice - 1.0;
            var avgAbsRet = absRetSum / impactWindow;
            var denom = Math.Max(avgAbsRet * Math.Sqrt(impactWindow), 1e-6);
            var signedMove = direction * priceMove / denom;
            var residualCap = Math.Max(0.5, Math.Abs(_residualCap));
            var residualGap = Math.Max(0.0, Math.Min(residualCap, residualCap - Math.Max(0.0, signedMove)));
            residualGap /= residualCap;

            var quality = Math.Sqrt(Math.Max(0.0, persistence * confirmation));
            var scale = Math.Max(Math.Abs(_clip), 1e-6);
            var signal = flowStrength * quality * acceleration * surpriseGate * residualGap * scale;
            rawSignal = Math.Max(-1.0, Math.Min(1.0, signal));
            return true;
""",
}


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    taker_buy_quote_volume: pd.DataFrame,
    taker_sell_quote_volume: pd.DataFrame,
    **_kwargs: Any,
) -> pd.DataFrame:
    flow_window = max(4, int(params.get("flow_window", 24)))
    confirm_window = max(2, min(int(params.get("confirm_window", 6)), flow_window // 2))
    surprise_window = max(flow_window, int(params.get("surprise_window", 72)))
    impact_window = max(1, int(params.get("impact_window", 8)))
    residual_cap = max(0.5, abs(float(params.get("residual_cap", 1.5))))
    clip = float(params.get("clip", 2.0))

    total_quote = taker_buy_quote_volume + taker_sell_quote_volume
    imbalance = (taker_buy_quote_volume - taker_sell_quote_volume) / total_quote.replace(0.0, np.nan)
    imbalance = imbalance.fillna(0.0)

    imbalance_mean = imbalance.rolling(flow_window, min_periods=flow_window).mean()
    imbalance_abs_mean = imbalance.abs().rolling(flow_window, min_periods=flow_window).mean()
    persistence = (imbalance_mean.abs() / imbalance_abs_mean.replace(0.0, np.nan)).clip(upper=1.0)
    flow_strength = np.tanh(imbalance_mean / 0.10)

    confirm_mean = imbalance.rolling(confirm_window, min_periods=confirm_window).mean()
    confirm_abs_mean = imbalance.abs().rolling(confirm_window, min_periods=confirm_window).mean()
    direction = np.sign(imbalance_mean)
    confirmation = (direction * confirm_mean / confirm_abs_mean.replace(0.0, np.nan)).clip(lower=0.0, upper=1.0)

    prior_window = max(flow_window - confirm_window, 1)
    prior_mean = (
        imbalance.shift(confirm_window)
        .rolling(prior_window, min_periods=prior_window)
        .mean()
    )
    acceleration = (direction * (confirm_mean - prior_mean) / 0.08).clip(lower=0.0, upper=1.0)

    avg_flow_quote = total_quote.rolling(flow_window, min_periods=flow_window).mean()
    avg_surprise_quote = total_quote.rolling(surprise_window, min_periods=surprise_window).mean()
    surprise = (avg_flow_quote / avg_surprise_quote.replace(0.0, np.nan) - 1.0).clip(lower=0.0)
    surprise_gate = 0.5 + 0.5 * np.tanh(surprise)

    price_move = close / close.shift(impact_window) - 1.0
    avg_abs_ret = close.pct_change().abs().rolling(impact_window, min_periods=impact_window).mean()
    denom = (avg_abs_ret * np.sqrt(impact_window)).replace(0.0, np.nan)
    signed_move = direction * price_move / denom
    residual_gap = (residual_cap - signed_move.clip(lower=0.0)).clip(lower=0.0, upper=residual_cap) / residual_cap

    quality = np.sqrt((persistence * confirmation).clip(lower=0.0))
    scale = max(abs(clip), 1e-6)
    signal = flow_strength * quality * acceleration * surprise_gate * residual_gap * scale
    signal = signal.clip(-1.0, 1.0)

    valid = (
        imbalance_mean.notna()
        & imbalance_abs_mean.notna()
        & confirm_mean.notna()
        & confirm_abs_mean.notna()
        & prior_mean.notna()
        & avg_surprise_quote.notna()
        & price_move.notna()
        & avg_abs_ret.notna()
    )
    signal = signal.where(valid)
    return signal.reindex_like(close)
