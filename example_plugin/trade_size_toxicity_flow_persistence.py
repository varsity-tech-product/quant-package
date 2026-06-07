"""orchestrator generated plugin

session_id:       s_20260606T062349_87cc5d
task_id:          task_05_orderflow
factor_type:      trade_size_toxicity_flow_persistence
model_requested:  openrouter:openai/gpt-5.5
model_served:     openai/gpt-5.5-20260423
runtime_provider: openrouter
runtime_model:    openai/gpt-5.5
billing_source:   platform
generation_backend: api_llm
agent_id:          orchestrator-llm-v1
model_slug:       openrouter_openai_gpt-5-5
variant:          0
generated_at:     2026-06-06T06:24:17.769Z
prompt_tokens:    6109
completion_tokens:2575
llm_cost_usd:     0.090515
llm_latency_ms:   26800
validation_ok:    True
compute_body_hash:74123cc8474976ec8f042f4f7ffc7803f82955ac64c295726121e1d512511441
openrouter_request_id: gen-1780727030-1TeMy8yFpXUw7WTASmM8
provider_request_id: gen-1780727030-1TeMy8yFpXUw7WTASmM8
"""
import pandas as pd
import numpy as np
from typing import Any, Dict

FACTOR_TYPE = "trade_size_toxicity_flow_persistence"

FACTOR_DEFAULT_PARAMS = {
    "flow_window": 18,
    "baseline_window": 72,
    "smooth_window": 8,
    "toxicity_power": 1.0,
    "price_lead_weight": 0.5,
}

FACTOR_SECTIONS = {
    "__FACTOR_DESCRIPTION__": "Trade-size toxicity flow persistence: persistent aggressive taker imbalance weighted by relative buy/sell trade size and damped when price has already moved.",
    "__FACTOR_FORMULA__": "imb=(buy_quote-sell_quote)/(buy_quote+sell_quote); size_edge=log(avg_buy_trade_size/avg_sell_trade_size); toxic=imb*tanh(size_edge); flow=mean(toxic, flow_window); activity=mean(aggr_quote, flow_window)/mean(aggr_quote, baseline_window); price_damp=1/(1+price_lead_weight*abs(ret)/vol); signal=EMA(flow*sqrt(activity)*price_damp, smooth_window)",
    "__FACTOR_TYPE__": "trade_size_toxicity_flow_persistence",
    "__FACTOR_PARAM_FIELDS__": (
        "        private int _flowWindow;\n"
        "        private int _baselineWindow;\n"
        "        private int _smoothWindow;\n"
        "        private double _toxicityPower;\n"
        "        private double _priceLeadWeight;\n"
        "        private double _factorSmoothedSignal;\n"
        "        private bool _factorSmoothInitialized;\n"
    ),
    "__FACTOR_INIT__": (
        '            _flowWindow = GetIntParameter("flow-window", 18);\n'
        '            _baselineWindow = GetIntParameter("baseline-window", 72);\n'
        '            _smoothWindow = GetIntParameter("smooth-window", 8);\n'
        '            _toxicityPower = GetDoubleParameter("toxicity-power", 1.0);\n'
        '            _priceLeadWeight = GetDoubleParameter("price-lead-weight", 0.5);\n'
        '            _factorSmoothedSignal = 0.0;\n'
        '            _factorSmoothInitialized = false;\n'
    ),
    "__FACTOR_LOG__": (
        '            Log($"[INIT] flow_window={_flowWindow} baseline_window={_baselineWindow} smooth_window={_smoothWindow} toxicity_power={_toxicityPower} price_lead_weight={_priceLeadWeight}");\n'
    ),
    "__PRICE_WINDOW_EXPR__": "_baselineWindow",
    "__EXTRA_BUF_FIELDS__": (
        "        private readonly Queue<double> _factorBuyQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorSellQuoteBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorBuyTradesBuf = new Queue<double>();\n"
        "        private readonly Queue<double> _factorSellTradesBuf = new Queue<double>();\n"
    ),
    "__EXTRA_BUF_ENQUEUE__": (
        "            _factorBuyQuoteBuf.Enqueue(bar.TakerBuyQuoteVolume);\n"
        "            _factorSellQuoteBuf.Enqueue(bar.TakerSellQuoteVolume);\n"
        "            _factorBuyTradesBuf.Enqueue(bar.TakerBuyTrades);\n"
        "            _factorSellTradesBuf.Enqueue(bar.TakerSellTrades);\n"
    ),
    "__EXTRA_BUF_DEQUEUE__": (
        "            if (_factorBuyQuoteBuf.Count > requiredBars) _factorBuyQuoteBuf.Dequeue();\n"
        "            if (_factorSellQuoteBuf.Count > requiredBars) _factorSellQuoteBuf.Dequeue();\n"
        "            if (_factorBuyTradesBuf.Count > requiredBars) _factorBuyTradesBuf.Dequeue();\n"
        "            if (_factorSellTradesBuf.Count > requiredBars) _factorSellTradesBuf.Dequeue();\n"
    ),
    "__EXTRA_BUF_TOARRAY__": (
        "            var factorBuyQuotes = _factorBuyQuoteBuf.ToArray();\n"
        "            var factorSellQuotes = _factorSellQuoteBuf.ToArray();\n"
        "            var factorBuyTrades = _factorBuyTradesBuf.ToArray();\n"
        "            var factorSellTrades = _factorSellTradesBuf.ToArray();\n"
    ),
    "__FACTOR_COMPUTE_BODY__": """
            int n = prices.Length;
            if (n < _baselineWindow || _flowWindow < 2 || _baselineWindow < _flowWindow) return false;

            double toxicSum = 0.0;
            double recentActivitySum = 0.0;
            int recentStart = n - _flowWindow;
            for (int i = recentStart; i < n; i++)
            {
                double buyQuote = factorBuyQuotes[i];
                double sellQuote = factorSellQuotes[i];
                double totalQuote = buyQuote + sellQuote;
                double imbalance = totalQuote > 1e-12 ? (buyQuote - sellQuote) / totalQuote : 0.0;

                double buyTrades = factorBuyTrades[i];
                double sellTrades = factorSellTrades[i];
                double avgBuySize = buyTrades > 1e-12 ? buyQuote / buyTrades : 0.0;
                double avgSellSize = sellTrades > 1e-12 ? sellQuote / sellTrades : 0.0;
                double sizeEdge = 0.0;
                if (avgBuySize > 1e-12 && avgSellSize > 1e-12)
                {
                    sizeEdge = Math.Log(avgBuySize / avgSellSize);
                }

                double toxicBar = imbalance * Math.Tanh(sizeEdge);
                if (_toxicityPower != 1.0)
                {
                    double sign = toxicBar >= 0.0 ? 1.0 : -1.0;
                    toxicBar = sign * Math.Pow(Math.Abs(toxicBar), _toxicityPower);
                }
                toxicSum += toxicBar;
                recentActivitySum += totalQuote;
            }

            double baselineActivitySum = 0.0;
            for (int i = 0; i < n; i++)
            {
                baselineActivitySum += factorBuyQuotes[i] + factorSellQuotes[i];
            }

            double flow = toxicSum / _flowWindow;
            double recentActivity = recentActivitySum / _flowWindow;
            double baselineActivity = baselineActivitySum / n;
            double activityRatio = baselineActivity > 1e-12 ? recentActivity / baselineActivity : 1.0;
            if (activityRatio < 0.0) activityRatio = 0.0;
            double activityScale = Math.Sqrt(Math.Min(activityRatio, 4.0));

            double ret = prices[n - 1] / Math.Max(prices[recentStart], 1e-12) - 1.0;
            double volSum = 0.0;
            int volCount = 0;
            for (int i = recentStart + 1; i < n; i++)
            {
                if (prices[i - 1] > 1e-12)
                {
                    double r = prices[i] / prices[i - 1] - 1.0;
                    volSum += r * r;
                    volCount++;
                }
            }
            double realizedVol = volCount > 1 ? Math.Sqrt(volSum) : 0.0;
            double moveScore = realizedVol > 1e-12 ? Math.Abs(ret) / realizedVol : 0.0;
            double priceDamp = 1.0 / (1.0 + _priceLeadWeight * moveScore);

            double currentRaw = flow * activityScale * priceDamp;
            double alpha = 2.0 / (_smoothWindow + 1.0);
            if (!_factorSmoothInitialized)
            {
                _factorSmoothedSignal = currentRaw;
                _factorSmoothInitialized = true;
            }
            else
            {
                _factorSmoothedSignal = alpha * currentRaw + (1.0 - alpha) * _factorSmoothedSignal;
            }

            rawSignal = Math.Tanh(4.0 * _factorSmoothedSignal);
            return true;
""",
}


def _ema_from_first_valid(x: pd.DataFrame, span: int) -> pd.DataFrame:
    # ema from first valid
    alpha = 2.0 / (span + 1.0)
    out = pd.DataFrame(np.nan, index=x.index, columns=x.columns)
    prev = pd.Series(np.nan, index=x.columns, dtype="float64")
    for i in range(len(x)):
        cur = x.iloc[i]
        init = prev.isna() & cur.notna()
        prev.loc[init] = cur.loc[init]
        upd = prev.notna() & cur.notna() & (~init)
        prev.loc[upd] = alpha * cur.loc[upd] + (1.0 - alpha) * prev.loc[upd]
        out.iloc[i] = prev
    return out


def build_signal(
    close: pd.DataFrame,
    params: Dict[str, Any],
    taker_buy_quote_volume: pd.DataFrame,
    taker_sell_quote_volume: pd.DataFrame,
    taker_buy_trades: pd.DataFrame,
    taker_sell_trades: pd.DataFrame,
    **_kwargs,
) -> pd.DataFrame:
    # build signal
    flow_window = int(params.get("flow_window", 18))
    baseline_window = int(params.get("baseline_window", 72))
    smooth_window = int(params.get("smooth_window", 8))
    toxicity_power = float(params.get("toxicity_power", 1.0))
    price_lead_weight = float(params.get("price_lead_weight", 0.5))

    buy_quote = taker_buy_quote_volume.astype(float)
    sell_quote = taker_sell_quote_volume.astype(float)
    total_quote = buy_quote + sell_quote

    imbalance = (buy_quote - sell_quote) / total_quote.replace(0.0, np.nan)
    imbalance = imbalance.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    avg_buy_size = buy_quote / taker_buy_trades.replace(0.0, np.nan)
    avg_sell_size = sell_quote / taker_sell_trades.replace(0.0, np.nan)
    size_edge = np.log(avg_buy_size / avg_sell_size.replace(0.0, np.nan))
    size_edge = size_edge.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    toxic_bar = imbalance * np.tanh(size_edge)
    if toxicity_power != 1.0:
        toxic_bar = np.sign(toxic_bar) * (toxic_bar.abs() ** toxicity_power)

    flow = toxic_bar.rolling(flow_window, min_periods=flow_window).mean()
    recent_activity = total_quote.rolling(flow_window, min_periods=flow_window).mean()
    baseline_activity = total_quote.rolling(baseline_window, min_periods=baseline_window).mean()
    activity_ratio = (recent_activity / baseline_activity.replace(0.0, np.nan)).clip(lower=0.0, upper=4.0)
    activity_scale = np.sqrt(activity_ratio)

    ret = close / close.shift(flow_window - 1) - 1.0
    one_bar_ret = close.pct_change()
    realized_vol = np.sqrt((one_bar_ret * one_bar_ret).rolling(flow_window - 1, min_periods=flow_window - 1).sum())
    move_score = (ret.abs() / realized_vol.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    price_damp = 1.0 / (1.0 + price_lead_weight * move_score)

    raw = flow * activity_scale * price_damp
    raw = raw.where(baseline_activity.notna())
    smoothed = _ema_from_first_valid(raw, smooth_window)
    signal = np.tanh(4.0 * smoothed)
    signal = signal.where(baseline_activity.notna())
    return signal.reindex_like(close)
