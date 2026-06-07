# 数据服务（exchange-gateway，只用 1d）

实盘信号在本地用 Python 跑 `build_signal`，数据走我们自己的数据服务
（项目 `varsity-tech-product/exchange-gateway`），**不连币安行情**。

## 前置
- 本机装了 `grpcurl`
- 能访问 exchange-gateway 仓库（含 proto）：环境变量 `EXCHANGE_GATEWAY_DIR`
  （默认 `/home/ec2-user/exchange-gateway`）
- 数据服务 gRPC 地址 `GATEWAY_TARGET`（prod 默认 `13.231.65.185:8777`；
  dev 走 SSH tunnel 后用 `127.0.0.1:8877`）

封装不重造 gRPC 管道——直接 import exchange-gateway 官方 ref client
（`examples/marketdata-fetch-client/exchange_gateway_ref_client.py`，内部 shell 调 grpcurl）。

## 字段来源
所有 plugin 字段都在 `market_features` 1d 的 35 列 schema 里，列名与 `build_signal`
入参名一致。取数路径：

| 字段类 | 接口 | 本包方法 |
|---|---|---|
| K 线类（close/volume/taker_buy_volume/taker_sell_volume/taker_buy_quote_volume/taker_sell_quote_volume/taker_buy_trades/taker_sell_trades） | `GetHistoricalBars`（unary，1d×1000） | `GatewayClient.fetch_bars_panel` |
| funding 历史 | `GetHistoricalFundingRates`（unary） | `GatewayClient.fetch_funding` |
| OI / premium / 大户多空比 历史 | market_features 1d（streaming `SubscribeMarketDataSlices`，公开 client 暂无 unary 历史） | 见下「feature 历史」 |

## 用法
```python
from quantkit.data.gateway_client import GatewayClient
from quantkit.data.panels import run_build_signal
from quantkit.plugins import load_plugin

gw = GatewayClient()                       # 默认 prod target
print(gw.is_ready(["BTCUSDT"]))            # readiness 健康检查（ready=true 才用）
bars = gw.fetch_bars_panel(["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT"], limit=1000)

p = load_plugin("example_plugin/flow_confirmed_smooth_trend_momentum.py")
sig = run_build_signal(p, bars)            # [date x symbol] 信号
```

- 失败关闭语义：`GetHistoricalBars` 返回带 `statuses[]`（缺口/不足）时该 symbol 视为不可用，自动跳过。
- `panels.build_panels(plugin, bars, features=...)`：按 `plugin.required_fields` 切列对齐。

## feature 历史（OI/premium/大户多空比）
这些字段的**历史**目前公开 client 只有 streaming（market_features 1d slices），没有
unary 历史接口。两种做法：
1. **本地按日累积**：每天订阅 `SubscribeMarketDataSlices`（feature_interval=1d）拿当日 feature 行，
   落盘累积，像 quanton 累积 taker 笔数那样，攒够窗口后喂给 carry 类因子。
2. 等数据服务补 feature 历史 unary 接口后直接拉。

K 线类因子（本仓 3 个样例里的 2 个 + 多数动量/流量因子）不受影响，开箱即用。

参考脚本：`exchange-gateway/examples/marketdata-fetch-client/`
- `fetch_historical_bars.md` / `fetch_historical_bars_readiness.md`
- `subscribe_market_data_slices.md`
