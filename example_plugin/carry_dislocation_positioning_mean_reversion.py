"""orchestrator generated plugin

session_id:       s_20260606T063423_396adf
task_id:          task_06_auction
factor_type:      carry_dislocation_positioning_mean_reversion
model_requested:  openrouter:openai/gpt-5.5
model_served:     openai/gpt-5.5-20260423
runtime_provider: openrouter
runtime_model:    openai/gpt-5.5
billing_source:   platform
generation_backend: api_llm
agent_id:          orchestrator-llm-v1
model_slug:       openrouter_openai_gpt-5-5
variant:          0
generated_at:     2026-06-06T06:35:01.924Z
prompt_tokens:    7294
completion_tokens:3254
llm_cost_usd:     0.112202
llm_latency_ms:   36687
validation_ok:    True
compute_body_hash:a7b73e0337865e76b3f843019626a126ac8aa6973b2007c8c92dd20b9a2e7c35
openrouter_request_id: gen-1780727664-6Ln73ziDoXzLz7zdMdGe
provider_request_id: gen-1780727664-6Ln73ziDoXzLz7zdMdGe
"""
import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "carry_dislocation_positioning_mean_reversion"

FACTOR_DEFAULT_PARAMS = {
    "short_window": 12,
    "long_window": 72,
    "trend_window": 24,
    "smooth_window": 8,
    "position_weight": 1.0,
    "premium_weight": 0.8,
    "oi_weight": 0.6,
    "trend_damp": 0.35,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Carry dislocation positioning mean reversion: fades persistent funding and premium dislocations when top-account crowding and open-interest leverage confirm one-sided perp demand.",
    "__FACTOR_FORMULA__": "fund_z=(mean(funding,s)-mean(funding,l))/std(funding,l); prem_z=(mean(premium,s)-mean(premium,l))/std(premium,l); pos=top_account_long-top_account_short; oi=log(mean(OI,s)/mean(OI,l)); trend=log(close/close[t-trend])/sqrt(sum(logret^2)); raw=-(fund_z+premium_weight*prem_z)*(1+oi_weight*max(oi,0)) - position_weight*pos - trend_damp*trend; signal=EMA(tanh(raw), smooth)",
    "__FACTOR_TYPE__": "carry_dislocation_positioning_mean_reversion",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _shortWindow;\n"
        "        private int _longWindow;\n"
        "        private int _trendWindow;\n"
        "        private int _smoothWindow;\n"
        "        private double _positionWeight;\n"
        "        private double _premiumWeight;\n"
        "        private double _oiWeight;\n"
        "        private double _trendDamp;\n"
        "        private double _factorSmoothedSignal;\n"
        "        private bool _factorSmoothInitialized;\n"
    ),
    "__FACTOR_INIT__": (
        '            _shortWindow = GetIntParameter("short-window", 12);\n'
        '            _longWindow = GetIntParameter("long-window", 72);\n'
        '            _trendWindow = GetIntParameter("trend-window", 24);\n'
        '            _smoothWindow = GetIntParameter("smooth-window", 8);\n'
        '            _positionWeight = GetDoubleParameter("position-weight", 1.0);\n'
        '            _premiumWeight = GetDoubleParameter("premium-weight", 0.8);\n'
        '            _oiWeight = GetDoubleParameter("oi-weight", 0.6);\n'
        '            _trendDamp = GetDoubleParameter("trend-damp", 0.35);\n'
        '            _factorSmoothedSignal = 0.0;\n'
        '            _factorSmoothInitialized = false;\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] short_window={_shortWindow} long_window={_longWindow} trend_window={_trendWindow} smooth_window={_smoothWindow} position_weight={_positionWeight} premium_weight={_premiumWeight} oi_weight={_oiWeight} trend_damp={_trendDamp}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_longWindow",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _factorFundingBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorPremiumBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorOiBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorTopLongBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorTopShortBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _factorFundingBuf.Enqueue(bar.FundingRateClose);\n"
        "            _factorPremiumBuf.Enqueue(bar.BinancePremiumIndexClose);\n"
        "            _factorOiBuf.Enqueue(bar.OpenInterestClose);\n"
        "            _factorTopLongBuf.Enqueue(bar.TopAccountLongPercent);\n"
        "            _factorTopShortBuf.Enqueue(bar.TopAccountShortPercent);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_factorFundingBuf.Count > requiredBars) _factorFundingBuf.Dequeue();\n"
        "            if (_factorPremiumBuf.Count > requiredBars) _factorPremiumBuf.Dequeue();\n"
        "            if (_factorOiBuf.Count > requiredBars) _factorOiBuf.Dequeue();\n"
        "            if (_factorTopLongBuf.Count > requiredBars) _factorTopLongBuf.Dequeue();\n"
        "            if (_factorTopShortBuf.Count > requiredBars) _factorTopShortBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var factorFundings = _factorFundingBuf.ToArray();\n"
        "            var factorPremiums = _factorPremiumBuf.ToArray();\n"
        "            var factorOis = _factorOiBuf.ToArray();\n"
        "            var factorTopLongs = _factorTopLongBuf.ToArray();\n"
        "            var factorTopShorts = _factorTopShortBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            var n = prices.Length;
            if (n < _longWindow) return false;
            if (_shortWindow < 2 || _longWindow < _shortWindow || _trendWindow < 2 || n < _trendWindow + 1) return false;

            int shortStart = n - _shortWindow;

            double fundShortSum = 0.0;
            double premShortSum = 0.0;
            double oiShortSum = 0.0;
            double fundLongSum = 0.0;
            double premLongSum = 0.0;
            double oiLongSum = 0.0;
            double fundLongSq = 0.0;
            double premLongSq = 0.0;

            for (int i = 0; i < n; i++)
            {
                double f = factorFundings[i];
                double p = factorPremiums[i];
                double oi = factorOis[i];
                fundLongSum += f;
                premLongSum += p;
                oiLongSum += oi;
                fundLongSq += f * f;
                premLongSq += p * p;
                if (i >= shortStart)
                {
                    fundShortSum += f;
                    premShortSum += p;
                    oiShortSum += oi;
                }
            }

            double fundShortMean = fundShortSum / _shortWindow;
            double premShortMean = premShortSum / _shortWindow;
            double oiShortMean = oiShortSum / _shortWindow;
            double fundLongMean = fundLongSum / n;
            double premLongMean = premLongSum / n;
            double oiLongMean = oiLongSum / n;

            double fundVar = fundLongSq / n - fundLongMean * fundLongMean;
            double premVar = premLongSq / n - premLongMean * premLongMean;
            double fundStd = fundVar > 1e-18 ? Math.Sqrt(fundVar) : 0.0;
            double premStd = premVar > 1e-18 ? Math.Sqrt(premVar) : 0.0;

            double fundZ = fundStd > 1e-9 ? (fundShortMean - fundLongMean) / fundStd : 0.0;
            double premZ = premStd > 1e-9 ? (premShortMean - premLongMean) / premStd : 0.0;

            double topLongMean = 0.0;
            double topShortMean = 0.0;
            for (int i = shortStart; i < n; i++)
            {
                topLongMean += factorTopLongs[i];
                topShortMean += factorTopShorts[i];
            }
            topLongMean /= _shortWindow;
            topShortMean /= _shortWindow;

            double posSkew = topLongMean - topShortMean;
            if (Math.Abs(posSkew) > 2.0)
            {
                posSkew = posSkew / 100.0;
            }
            if (posSkew > 1.0) posSkew = 1.0;
            if (posSkew < -1.0) posSkew = -1.0;

            double oiExpansion = 0.0;
            if (oiShortMean > 1e-12 && oiLongMean > 1e-12)
            {
                oiExpansion = Math.Log(oiShortMean / oiLongMean);
            }
            double oiAmplifier = 1.0 + _oiWeight * Math.Max(oiExpansion, 0.0);

            double netLogRet = 0.0;
            if (prices[n - _trendWindow - 1] > 1e-12 && prices[n - 1] > 1e-12)
            {
                netLogRet = Math.Log(prices[n - 1] / prices[n - _trendWindow - 1]);
            }

            double rvSq = 0.0;
            for (int i = n - _trendWindow; i < n; i++)
            {
                if (prices[i - 1] > 1e-12 && prices[i] > 1e-12)
                {
                    double r = Math.Log(prices[i] / prices[i - 1]);
                    rvSq += r * r;
                }
            }
            double trend = rvSq > 1e-18 ? netLogRet / Math.Sqrt(rvSq) : 0.0;
            if (trend > 3.0) trend = 3.0;
            if (trend < -3.0) trend = -3.0;

            double carryCrowding = (fundZ + _premiumWeight * premZ) * oiAmplifier;
            double raw = -carryCrowding - _positionWeight * posSkew - _trendDamp * trend;
            double bounded = Math.Tanh(raw / 2.0);

            double alpha = 2.0 / (_smoothWindow + 1.0);
            if (!_factorSmoothInitialized)
            {
                _factorSmoothedSignal = bounded;
                _factorSmoothInitialized = true;
            }
            else
            {
                _factorSmoothedSignal = alpha * bounded + (1.0 - alpha) * _factorSmoothedSignal;
            }

            rawSignal = _factorSmoothedSignal;
            return true;
""",
}


def _ema_from_first_valid(x: pd.DataFrame, span: int) -> pd.DataFrame:
    alpha = 2.0 / (span + 1.0)
    out = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    prev = None
    for i in range(len(x)):
        row = x.iloc[i]
        valid = row.notna()
        if prev is None:
            prev = row.copy()
            out.iloc[i] = prev
        else:
            prev = row * alpha + prev * (1.0 - alpha)
            prev = prev.where(valid, np.nan)
            out.iloc[i] = prev
    return out


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    funding_rate_close: pd.DataFrame,
    binance_premium_index_close: pd.DataFrame,
    open_interest_close: pd.DataFrame,
    top_account_long_percent: pd.DataFrame,
    top_account_short_percent: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    short_window = int(params.get("short_window", 12))
    long_window = int(params.get("long_window", 72))
    trend_window = int(params.get("trend_window", 24))
    smooth_window = int(params.get("smooth_window", 8))
    position_weight = float(params.get("position_weight", 1.0))
    premium_weight = float(params.get("premium_weight", 0.8))
    oi_weight = float(params.get("oi_weight", 0.6))
    trend_damp = float(params.get("trend_damp", 0.35))

    fund_s = funding_rate_close.rolling(short_window).mean()
    fund_l = funding_rate_close.rolling(long_window).mean()
    fund_std = funding_rate_close.rolling(long_window).std(ddof=0)
    fund_z = (fund_s - fund_l) / fund_std.replace(0.0, np.nan)

    prem_s = binance_premium_index_close.rolling(short_window).mean()
    prem_l = binance_premium_index_close.rolling(long_window).mean()
    prem_std = binance_premium_index_close.rolling(long_window).std(ddof=0)
    prem_z = (prem_s - prem_l) / prem_std.replace(0.0, np.nan)

    oi_s = open_interest_close.rolling(short_window).mean()
    oi_l = open_interest_close.rolling(long_window).mean()
    oi_expansion = np.log(oi_s / oi_l.replace(0.0, np.nan))
    oi_amplifier = 1.0 + oi_weight * oi_expansion.clip(lower=0.0)

    pos_skew = (
        top_account_long_percent.rolling(short_window).mean()
        - top_account_short_percent.rolling(short_window).mean()
    )
    pos_skew = pos_skew.where(pos_skew.abs() <= 2.0, pos_skew / 100.0).clip(-1.0, 1.0)

    log_close = np.log(close.where(close > 0.0))
    logret = log_close.diff()
    net_logret = log_close - log_close.shift(trend_window)
    rv = np.sqrt((logret * logret).rolling(trend_window).sum())
    trend = (net_logret / rv.replace(0.0, np.nan)).clip(-3.0, 3.0)

    carry_crowding = (fund_z.fillna(0.0) + premium_weight * prem_z.fillna(0.0)) * oi_amplifier
    raw = -carry_crowding - position_weight * pos_skew.fillna(0.0) - trend_damp * trend.fillna(0.0)
    bounded = np.tanh(raw / 2.0)

    signal = _ema_from_first_valid(bounded, smooth_window)
    valid = (
        close.notna()
        & funding_rate_close.notna()
        & binance_premium_index_close.notna()
        & open_interest_close.notna()
        & top_account_long_percent.notna()
        & top_account_short_percent.notna()
        & (funding_rate_close.rolling(long_window).count() >= long_window)
        & (binance_premium_index_close.rolling(long_window).count() >= long_window)
        & (open_interest_close.rolling(long_window).count() >= long_window)
        & (close.rolling(long_window).count() >= long_window)
    )
    signal = signal.where(valid, np.nan)
    return signal.reindex_like(close)
