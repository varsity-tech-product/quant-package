# 因子组合 → Lean 实盘 C# 策略（binance_direct 速查）

把用户的截面因子 plugin 组合**渲染成一个 Lean C# 策略**，交给 exchange-gateway 的
`binance_direct` 执行通道直连币安 USD-M Futures 下单。与 `quantkit.live`（Python 直连）
是**两条不同的实盘 rail**，本条经过 gateway 的 Lean。

代码：`quantkit/compose_csharp/`（拼接层）+ `quantkit/live/gateway_launch.py`（启动胶水）。
口径来源：回测服务端 `quantai-service/strategy_composer`，本包**逐字 vendored** 其拼接
逻辑，去掉 S3/EFS/job_id（走 content 模式，plugin 直接来自 `quantkit.plugins`）。

## 它做什么 / 不做什么

- **做**：把每个 plugin 的 `FACTOR_SECTIONS`（C# 片段）拼成一个完整 Lean 策略类，
  每标的一份 `FactorState`，每根 bar 更新；调仓时**每因子截面 z-score → 按权重加权
  composite → 排序取 top/bot k → SetHoldings**。这套因子逻辑 + 调仓数学与回测**字节
  级一致**，所以实盘交易的是和回测同一个 composite 信号。
- **不做**：不在 Python 里算信号下单（那是 `quantkit.live`）。信号在 Lean(C#) 内算，
  执行经 gateway。

## 为什么不能直接拿回测的 .cs 跑实盘

回测模板用 `FactorCsvBar : BaseData` 读**本地 zip 历史切片** + `AddData`（自定义数据，
**不可下单**）。实盘 `binance_direct` 需要：

| | 回测 | 实盘 |
|---|---|---|
| 行情 | 本地 zip CSV | 8778 实时流（`ExchangeGatewayDataQueueHandler`） |
| 交易标的 | `AddData<FactorCsvBar>`（不可交易） | `AddCryptoFuture(…, Market.Binance)`（真实合约） |
| 额外列 | 全打包在一根 bar | OHLCV 走 `TradeBar`；taker/OI/funding 走独立 `market_features` 流 |

所以本包提供两套模板：`render_backtest_strategy`（复刻回测，用于对账）与
`render_live_strategy`（实盘外壳）。**因子逻辑半边两者共用、逐字相同**。

## 用本包跑

```python
from quantkit.compose_csharp import StrategySpec, Weighting, Ranking, render_live_strategy
from quantkit.plugins import load_plugin

plugins = [load_plugin("momentum.py"), load_plugin("taker_flow.py")]
spec = StrategySpec(
    weighting=Weighting("custom", [0.6, 0.4]),
    ranking=Ranking("percent", 20),   # 多空各 20%；或 Ranking("N", 5)
    strategy_type="neutral",          # long_only / short_only / neutral
    rebalance_bars=1,                 # 每日调仓
)
# 任一因子有 futures/on-chain 额外列就订 market_features
need_feat = any(p.sections.get("__EXTRA_BUF_TOARRAY__", "").strip() for p in plugins)
source, class_name = render_live_strategy(
    plugins, spec, ["btcusdt", "ethusdt", "solusdt"],
    subscribe_features=need_feat, bar_size="1d",
)
```

样例：`examples/06_compose_live_csharp.py`。

## 启动（经 paper-runner）

`quantkit.live.gateway_launch` 负责渲染 → 写 `.cs` → 拼 env → 起 paper-runner：

```python
from quantkit.live.gateway_launch import GatewayLaunchConfig, launch

cfg = GatewayLaunchConfig.from_env("binance-direct-live-001")  # 读 EXCHANGE_GATEWAY_REPO 等
launch(plugins, spec, symbols, cfg, workdir=Path("~/quant_runs/run_xxx"),
       subscribe_features=need_feat, dry_run=True)              # 先 dry-run
```

底层等价于 runbook 的：

```bash
export EXCHANGE_GATEWAY_REPO=/path/to/exchange-gateway
export LEAN_ROOT=/path/to/lean   LEAN_PLUGIN_DIR=/path/to/lean/plugins
export INSTANCE_ID=binance-direct-live-001
export LEAN_EXECUTION_PROFILE=binance_direct
export EXCHANGE_GATEWAY_EXCHANGE=binance-usdm
export EXCHANGE_GATEWAY_SECURITY_MODEL=binance_crypto_future
export EXCHANGE_GATEWAY_BINANCE_API_KEY_ENV=BINANCE_API_KEY
export EXCHANGE_GATEWAY_BINANCE_API_SECRET_ENV=BINANCE_API_SECRET
export BINANCE_FAPI_URL=https://fapi.binance.com
export BINANCE_FWEBSOCKET_URL=wss://fstream.binance.com/ws
export EXCHANGE_GATEWAY_AGGTRADE_KLINE_URL=127.0.0.1:8778
export LEAN_STRATEGY_CLASS_NAME=<ClassName>
export LEAN_STRATEGY_SOURCE_PATH=<workdir>/<ClassName>.cs
export LEAN_STRATEGY_PARAMETERS_JSON='{"dry-run":"true"}'

uv run --project services/paper-runner python -m paper_runner
```

- 凭证：`read -r -s` 交互读入 `BINANCE_API_KEY`/`SECRET`，传给 Lean 的只是**变量名**，
  真实 key 不入仓库/命令行/日志。`gateway_launch` 同理（只设 `*_ENV` 变量名）。
- `LEAN_PLUGIN_DIR` 必须含 `ExchangeGateway.LeanPlugin.dll` 和
  `QuantConnect.BinanceBrokerage.dll`，否则 binance_direct 启动前 fail fast。

## dry-run 安全闸（默认开）

live 模板有 `dry-run` 参数（`LEAN_STRATEGY_PARAMETERS_JSON`），**默认 true**：每期照常
算多空桶和目标权重并 `Log`，但**不下任何单**。确认无误再设 `dry-run=false` 真实下单。
`launch(dry_run=False)` 还会做凭证预检（key/secret 变量未设直接报错，不触网）。

## market_features：字段与路由（关键）

- 实盘 DQH 只在数据类型**名为 `MatchXKlineWithCoinglassBar`**（或 `CoinGlassFeatureBar`）
  时才路由到 feature 流（`IsFeatureDataType` 硬编码），再用反射把
  `taker_buy_quote_volume`/`open_interest_*`/`funding_rate_*`/`*_long_short_ratio`/
  `liquidation_*`/`binance_premium_index_*` 填到**同名 decimal 属性**。所以 live 模板里
  的 feature 载体类必须叫这个名字（已处理）。
- 缺失列 → `MissingValue (-999999999)`；模板的 `FeatVal` 转成 `NaN`，触发因子片段里
  自动注入的 **NaN 守卫**，该 symbol 当期被干净跳过（不会拿垃圾信号下单）。
- **纯量价因子**（只用 close/OHLCV）`subscribe_features=False` 即可，只订 kline。
  **需要 taker/OI/funding 的因子必须** `subscribe_features=True`，否则额外列恒为 NaN、
  每期被跳过 = 没信号。

## 限制 / 注意（上线前确认）

1. **冷启动**：`binance_direct` **没有** IHistoryProvider（只有 gateway/hyperliquid
   入口有），`SetWarmUp` 不回放历史。ring buffer 从实时 bar 前向填充，未填满的 symbol
   按 insufficient-bars 跳过。1d、长 lookback 因子 = **多日冷启动**。要更快可加第二步：
   用 8778 历史 RPC（可给 ≤1000 根 + 对齐 feature）在 Initialize 预热缓冲。
2. **feature 符号的 market 映射**：`AddData<MatchXKlineWithCoinglassBar>(pair, …)` 的
   symbol market 要和 gateway 期望一致，smoke 时确认 feature 真有数据到。
3. **binance_direct 不写 trading-agent 持久库**、不进 order-gateway 历史查询。要统一
   session/账本得改用 `ExchangeGatewayBrokerage`（gateway 入口）。
4. 先验通 `BinanceDirectLiveSmokeStrategy`（小额远离市价限价单→撤单）再上组合策略。

## 模块

| 模块 | 作用 |
|---|---|
| `quantkit.compose_csharp.rewriter` | 因子 C# 片段改造（参数内联 + NaN 守卫），vendored |
| `quantkit.compose_csharp.spec` | 权重/ranking/strategy_type 校验（无 pydantic） |
| `quantkit.compose_csharp.renderer` | 渲染 `render_backtest_strategy` / `render_live_strategy` |
| `quantkit.compose_csharp.templates` | `cross_sectional_backtest.cs.j2`（对账）/ `cross_sectional_live.cs.j2`（实盘） |
| `quantkit.live.gateway_launch` | 渲染 → 写 .cs → 拼 binance_direct env → 起 paper-runner |
