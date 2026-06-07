"""orchestrator generated plugin

session_id:       s_20260606T062048_a4b396
task_id:          task_07_momentum
factor_type:      flow_confirmed_smooth_trend_momentum
model_requested:  openrouter:openai/gpt-5.5
model_served:     openai/gpt-5.5-20260423
runtime_provider: openrouter
runtime_model:    openai/gpt-5.5
billing_source:   platform
generation_backend: api_llm
agent_id:          orchestrator-llm-v1
model_slug:       openrouter_openai_gpt-5-5
variant:          0
generated_at:     2026-06-06T06:21:20.276Z
prompt_tokens:    5492
completion_tokens:2585
llm_cost_usd:     0.105010
llm_latency_ms:   30539
validation_ok:    True
compute_body_hash:02d857ad7d80abe9ab4a80306e7f38fe93922d643781593fb61103f26492c614
openrouter_request_id: gen-1780726849-yKsj3evnfFbQ7XrwmfjW
provider_request_id: gen-1780726849-yKsj3evnfFbQ7XrwmfjW
"""
import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "flow_confirmed_smooth_trend_momentum"

FACTOR_DEFAULT_PARAMS = {
    "trend_window": 28,
    "quality_window": 14,
    "volume_window": 42,
    "smooth_window": 7,
    "flow_weight": 60.0,
    "quality_power": 1.0,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Flow-confirmed smooth trend momentum: risk-adjusted price trend gated by trend smoothness and confirmed by taker-buy capital pressure plus relative volume.",
    "__FACTOR_FORMULA__": "ret = close/close[t-w]-1; trend = ret / realized_vol; quality = abs(net_return)/(sum_abs_returns); flow = mean(taker_buy/(buy+sell)-0.5); vol_confirm = mean(volume)/mean(volume_baseline)-1; raw = trend * quality^p * (1 + flow_weight*flow) * max(0.25, 1+vol_confirm); signal = EMA(raw, smooth_window)",
    "__FACTOR_TYPE__": "flow_confirmed_smooth_trend_momentum",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _trendWindow;\n"
        "        private int _qualityWindow;\n"
        "        private int _volumeWindow;\n"
        "        private int _smoothWindow;\n"
        "        private double _flowWeight;\n"
        "        private double _qualityPower;\n"
        "        private double _factorSmoothedSignal;\n"
        "        private bool _factorSignalInitialized;\n"
    ),
    "__FACTOR_INIT__": (
        '            _trendWindow = GetIntParameter("trend-window", 28);\n'
        '            _qualityWindow = GetIntParameter("quality-window", 14);\n'
        '            _volumeWindow = GetIntParameter("volume-window", 42);\n'
        '            _smoothWindow = GetIntParameter("smooth-window", 7);\n'
        '            _flowWeight = GetDoubleParameter("flow-weight", 60.0);\n'
        '            _qualityPower = GetDoubleParameter("quality-power", 1.0);\n'
        '            _factorSmoothedSignal = 0.0;\n'
        '            _factorSignalInitialized = false;\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] trend_window={_trendWindow} quality_window={_qualityWindow} volume_window={_volumeWindow} smooth_window={_smoothWindow} flow_weight={_flowWeight} quality_power={_qualityPower}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_trendWindow + _volumeWindow",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _factorVolumeBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorTakerBuyBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorTakerSellBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _factorVolumeBuf.Enqueue((double)bar.Volume);\n"
        "            _factorTakerBuyBuf.Enqueue(bar.TakerBuyVolume);\n"
        "            _factorTakerSellBuf.Enqueue(bar.TakerSellVolume);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_factorVolumeBuf.Count > requiredBars) _factorVolumeBuf.Dequeue();\n"
        "            if (_factorTakerBuyBuf.Count > requiredBars) _factorTakerBuyBuf.Dequeue();\n"
        "            if (_factorTakerSellBuf.Count > requiredBars) _factorTakerSellBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var factorVolumes = _factorVolumeBuf.ToArray();\n"
        "            var factorTakerBuys = _factorTakerBuyBuf.ToArray();\n"
        "            var factorTakerSells = _factorTakerSellBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            int n = prices.Length;
            int required = _trendWindow + _volumeWindow;
            if (n < required) return false;
            if (_trendWindow < 2 || _qualityWindow < 2 || _volumeWindow < 2 || _smoothWindow < 1) return false;

            int trendStart = n - 1 - _trendWindow;
            double startPrice = prices[trendStart];
            double endPrice = prices[n - 1];
            if (Math.Abs(startPrice) < 1e-12 || Math.Abs(endPrice) < 1e-12) return false;

            double netReturn = endPrice / startPrice - 1.0;

            double sumRet = 0.0;
            double sumRetSq = 0.0;
            for (int i = trendStart + 1; i < n; i++)
            {
                double prev = prices[i - 1];
                double r = Math.Abs(prev) > 1e-12 ? prices[i] / prev - 1.0 : 0.0;
                sumRet += r;
                sumRetSq += r * r;
            }
            double meanRet = sumRet / _trendWindow;
            double varRet = sumRetSq / _trendWindow - meanRet * meanRet;
            if (varRet < 0.0) varRet = 0.0;
            double realizedVol = Math.Sqrt(varRet * _trendWindow);
            double trendScore = realizedVol > 1e-12 ? netReturn / realizedVol : 0.0;

            int qualityLen = _qualityWindow;
            if (qualityLen > _trendWindow) qualityLen = _trendWindow;
            int qualityStart = n - 1 - qualityLen;
            double pathAbs = 0.0;
            for (int i = qualityStart + 1; i < n; i++)
            {
                double prev = prices[i - 1];
                double r = Math.Abs(prev) > 1e-12 ? prices[i] / prev - 1.0 : 0.0;
                pathAbs += Math.Abs(r);
            }
            double qualityNet = Math.Abs(prices[n - 1] / prices[qualityStart] - 1.0);
            double quality = pathAbs > 1e-12 ? qualityNet / pathAbs : 0.0;
            if (quality < 0.0) quality = 0.0;
            if (quality > 1.0) quality = 1.0;
            double qualityGate = Math.Pow(quality, _qualityPower);

            double flowSum = 0.0;
            for (int i = n - _trendWindow; i < n; i++)
            {
                double total = factorTakerBuys[i] + factorTakerSells[i];
                double ratio = total > 1e-12 ? factorTakerBuys[i] / total : 0.5;
                flowSum += ratio - 0.5;
            }
            double flowPressure = flowSum / _trendWindow;
            double flowConfirm = 1.0 + _flowWeight * flowPressure;
            if (flowConfirm < 0.25) flowConfirm = 0.25;
            if (flowConfirm > 2.50) flowConfirm = 2.50;

            double recentVol = 0.0;
            for (int i = n - _trendWindow; i < n; i++)
            {
                recentVol += factorVolumes[i];
            }
            recentVol /= _trendWindow;

            double baseVol = 0.0;
            for (int i = n - _trendWindow - _volumeWindow; i < n - _trendWindow; i++)
            {
                baseVol += factorVolumes[i];
            }
            baseVol /= _volumeWindow;

            double volumeConfirm = 1.0;
            if (baseVol > 1e-12)
            {
                volumeConfirm = recentVol / baseVol;
            }
            if (volumeConfirm < 0.25) volumeConfirm = 0.25;
            if (volumeConfirm > 2.00) volumeConfirm = 2.00;

            double raw = trendScore * qualityGate * flowConfirm * volumeConfirm;
            if (raw > 5.0) raw = 5.0;
            if (raw < -5.0) raw = -5.0;

            double alpha = 2.0 / (_smoothWindow + 1.0);
            if (!_factorSignalInitialized)
            {
                _factorSmoothedSignal = raw;
                _factorSignalInitialized = true;
            }
            else
            {
                _factorSmoothedSignal = alpha * raw + (1.0 - alpha) * _factorSmoothedSignal;
            }

            rawSignal = _factorSmoothedSignal;
            return true;
""",
}


def _ema_state_like(x: pd.DataFrame, period: int) -> pd.DataFrame:
    # ema state like
    alpha = 2.0 / (period + 1.0)
    out = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    if len(x) == 0:
        return out
    prev = pd.Series(np.nan, index=x.columns, dtype=float)
    for i in range(len(x)):
        cur = x.iloc[i]
        initialized = prev.notna()
        prev = cur.where(~initialized, cur * alpha + prev * (1.0 - alpha))
        valid = cur.notna()
        prev = prev.where(valid, np.nan)
        out.iloc[i] = prev
    return out


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    volume: pd.DataFrame,
    taker_buy_volume: pd.DataFrame,
    taker_sell_volume: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    # build signal
    trend_window = int(params.get("trend_window", 28))
    quality_window = int(params.get("quality_window", 14))
    volume_window = int(params.get("volume_window", 42))
    smooth_window = int(params.get("smooth_window", 7))
    flow_weight = float(params.get("flow_weight", 60.0))
    quality_power = float(params.get("quality_power", 1.0))

    returns = close.pct_change()
    net_return = close / close.shift(trend_window) - 1.0
    realized_vol = returns.rolling(trend_window).std() * np.sqrt(float(trend_window))
    trend_score = net_return / realized_vol.replace(0.0, np.nan)

    quality_len = min(quality_window, trend_window)
    quality_net = (close / close.shift(quality_len) - 1.0).abs()
    path_abs = returns.abs().rolling(quality_len).sum()
    quality = (quality_net / path_abs.replace(0.0, np.nan)).clip(lower=0.0, upper=1.0)
    quality_gate = quality.pow(quality_power)

    total_taker = taker_buy_volume + taker_sell_volume
    buy_ratio = taker_buy_volume / total_taker.replace(0.0, np.nan)
    flow_pressure = (buy_ratio - 0.5).rolling(trend_window).mean()
    flow_confirm = (1.0 + flow_weight * flow_pressure).clip(lower=0.25, upper=2.50)

    recent_vol = volume.rolling(trend_window).mean()
    base_vol = volume.shift(trend_window).rolling(volume_window).mean()
    volume_confirm = (recent_vol / base_vol.replace(0.0, np.nan)).clip(lower=0.25, upper=2.00)

    raw = (trend_score * quality_gate * flow_confirm * volume_confirm).clip(lower=-5.0, upper=5.0)
    signal = _ema_state_like(raw, smooth_window)

    required = trend_window + volume_window
    signal.iloc[: required - 1] = np.nan
    return signal.reindex_like(close)
