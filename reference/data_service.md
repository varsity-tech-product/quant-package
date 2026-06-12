# 数据服务（exchange-gateway，只用 1d）

实盘信号在本地用 Python 跑 `build_signal`，数据走我们自己的数据服务
（项目 `varsity-tech-product/exchange-gateway`），**不连币安行情**。

## 前置
- 本机装了 `grpcurl`
- **不再需要** exchange-gateway 仓库：参考客户端与 proto 已内置进
  `quantkit/data/_gateway/`（见该子包说明）。可直接发给外部用户。
- 数据服务 gRPC 地址（prod 默认）：
  - `KLINE_TARGET`（K 线 + feature）= 新 aggtrade-kline-gateway，`13.231.65.185:8778`
    （dev 本机 `127.0.0.1:8878`）
  - `FUNDING_TARGET`（funding）= 旧 market gateway，`13.231.65.185:8777`

## 两个服务、两个端口（重要）
`8778` 不是 `8777` 换了个号，而是**另一个服务** `AggTradeKlineGatewayService`：

| | 8777 `MarketDataService` | 8778 `AggTradeKlineGatewayService` |
|---|---|---|
| K 线语义 | 币安官方 Kline | aggTrade 合成 K 线 |
| 取 bars | `GetHistoricalBars` | `GetHistoricalKlines`（**≤300**，只 1h/1d） |
| readiness | `GetHistoricalBarsReadiness` | `GetHistoricalKlineReadiness` |
| feature 历史 | 只有 streaming | `GetHistoricalFeatureBars`（unary） |
| funding | `GetHistoricalFundingRates` | ❌ 无 |
| proto | `marketdata.proto`(+`decimal`) | `aggtrade_kline.proto`(→import 上面两个) |

本包据此把 **bars/readiness/feature 走 8778**，**funding 走 8777**。

## 字段来源
所有 plugin 字段都在 `market_features` 1d schema 里，列名与 `build_signal` 入参名一致。

| 字段类 | 接口（服务/端口） | 本包方法 |
|---|---|---|
| K 线类（close/volume/taker_buy_volume/taker_sell_volume/taker_buy_quote_volume/taker_sell_quote_volume/taker_buy_trades/taker_sell_trades） | `GetHistoricalKlines`（8778，unary，1d×≤300） | `GatewayClient.fetch_bars_panel` |
| OI / premium / 大户多空比 历史 | `GetHistoricalFeatureBars`（8778，unary，market_features 1d） | `GatewayClient.fetch_features_panel` |
| funding 历史 | `GetHistoricalFundingRates`（8777，unary） | `GatewayClient.fetch_funding` |

## 用法
```python
from quantkit.data.gateway_client import GatewayClient
from quantkit.data.panels import run_build_signal
from quantkit.plugins import load_plugin

gw = GatewayClient()                       # 默认 klines/features=8778, funding=8777
print(gw.is_ready(["BTCUSDT"]))            # readiness 健康检查（ready=true 才用）
bars = gw.fetch_bars_panel(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"], limit=300)

p = load_plugin("example_plugin/flow_confirmed_smooth_trend_momentum.py")
sig = run_build_signal(p, bars)            # [date x symbol] 信号

# carry 类因子（需要 OI/premium/大户多空比 历史）：
feats = gw.fetch_features_panel(["BTCUSDT","ETHUSDT"], limit=300)
# run_build_signal(carry_plugin, bars, features=feats)
```

- 失败关闭语义：`GetHistoricalKlines` / `GetHistoricalFeatureBars` 返回带 `statuses[]`
  （缺口/不足）时该 symbol 视为不可用，自动跳过。
- `panels.build_panels(plugin, bars, features=...)`：按 `plugin.required_fields` 切列对齐。
- 实盘 `rebalancer` 会**按需**补取 feature：仅当某因子的 `required_fields` 含 bars
  提供不了的字段时才调 `fetch_features_panel`，纯 K 线策略不触发。

## feature 历史的成熟度
`8778` 的 `GetHistoricalFeatureBars` 提供了 OI/premium/大户多空比 的 **unary 历史**
（取代旧的"只能 streaming 按日累积"做法）。但上游文档标注 feature backfill/hotfill
"仍待完善"，历史窗口可能返回缺列。本包读 `missing_mask`，缺失列按 NaN 处理，
**不会**把缺失当真值；某因子字段全缺时会在 `build_panels` 抛 `MissingFieldError`。

K 线类因子（本仓多数动量/流量因子）不依赖 feature，开箱即用。

## 参考脚本（exchange-gateway 仓库内，供对照）
`examples/marketdata-fetch-client/`
- `fetch_aggtrade_kline_bars.md` / `fetch_historical_bars_readiness.md`（8778）
- `fetch_aggtrade_kline_slices.md` / `subscribe_market_data_slices.md`（8778 K+feature 对齐）
