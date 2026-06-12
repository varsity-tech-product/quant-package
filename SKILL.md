---
name: quant-package
description: >-
  Compose cross-sectional crypto factors (quant-factor-loop plugins) into a
  strategy, submit it to the backtest service, read results, and deploy it to
  Binance Futures live trading. Use when the user wants to combine factors into
  a strategy, run a strategy backtest, inspect backtest results, or deploy a
  composed factor strategy to live trading. Data comes from the in-house
  exchange-gateway service (1d; klines/features via 8778, funding via 8777),
  not Binance market feeds. 取数依赖已内置，只需本机装 grpcurl。
---

# quant-package

把用户挖到的**截面因子 plugin** 组合成策略 → 提交回测 → 取结果 → 部署币安实盘。

代码在本仓 `quantkit/`，样例在 `examples/`，细节文档在 `reference/`，
**可直接回测的样例因子**（带 job_id）在 `sample_factors/`。

## 何时用
- 「把因子 A、B 组合成策略回测一下」→ 能力 ①②
- 「这个策略部署到实盘」→ 能力 ③
- 「看看这个 plugin 需要哪些数据 / 怎么组合多因子」→ 能力 ①

## 开工前：建独立工作目录（带时间戳）
**每次任务先建一个带时间戳的独立目录**，所有产出（strategy.json、提交脚本、
回测结果、实盘日志、笔记）都写进去，互不覆盖、可追溯：
```bash
WORKDIR="$HOME/quant_runs/run_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$WORKDIR"     # 之后所有文件写这里
```
不要把产出散在 package 目录里。

## 用户没有自己的 job_id / plugin？用 sample_factors/
真实回测需要 `{job_id, plugin}`。用户没有的话，直接用本仓 `sample_factors/` 里的
归档因子（文件名 = `<job_id>__<plugin>.py`，清单见 `sample_factors/catalog.json`）。
- 优先选 `catalog.json` 里 `live_ready=true` 的**纯量价**因子。
- 用法见 `sample_factors/README.md`。

## 三条主路径

### ① + ② 组合因子 → 提交回测 → 取结果
回测**不在本地算信号**：服务端用 plugin 的 C# 片段编译跑 Lean，本地只给
`{job_id, plugin}`。job_id 来自 quant-factor-loop 归档（找法见
`reference/backtest_submit.md`）。

```python
from quantkit.backtest import BacktestClient, Factor
bt = BacktestClient()                                   # http://13.215.186.241:8001
resp = bt.submit_cs(
    factors=[Factor("job_xxx","factor_a.py"), Factor("job_yyy","factor_b.py")],
    weighting={"mode":"custom","weights":[0.6,0.4]},
    ranking={"mode":"N","value":5}, strategy_type="neutral",
)
sid = resp["strategy_id"]; bt.wait(sid)
print(bt.summary(sid)["metrics"])
```
样例：`examples/01_compose_and_backtest.py`。细节：`reference/backtest_submit.md`。

> 样例 `example_plugin/` 只演示插件格式；真实回测提交用**已归档有 job_id** 的因子。

### ③ 部署币安实盘（日度调仓）
实盘**在本地跑 `build_signal`**，数据走 exchange-gateway（只用 1d；bars/feature=8778、
funding=8777，≤300 根）。取数依赖已内置，无需 exchange-gateway 仓库，只需本机装 grpcurl。
组合口径与回测 CS 语义一致，回测/实盘可比。

**实盘前先向用户要 API key**：本包不内置任何密钥。部署前 **AI 主动问用户**要
Binance API key/secret，并帮其写入 `.env`：
- 默认 testnet（`BINANCE_TESTNET=true`）。testnet key 在
  <https://testnet.binancefuture.com> 注册后生成，与主网**不通用**，资金是模拟的。
- 要上主网才用主网 key（需开「合约交易」权限）。
- 拿到后写进 `.env` 的 `BINANCE_API_KEY` / `BINANCE_API_SECRET`（`.env` 在 .gitignore，
  不会提交）。没有 key 时 `--once` 会在预检直接报错。

```bash
cp .env.example .env                              # 填币安 key(先testnet)、CMC_API_KEY；数据地址用默认即可
cp examples/strategy.example.json strategy.json   # 改成你的因子组合（可用 sample_factors/ 里的）
python -m quantkit.live.main --strategy strategy.json --once   # 先验证一次
python -m quantkit.live.main --strategy strategy.json          # 常驻每日调仓
```
样例：`examples/04_deploy_live.py`。细节：`reference/live_deploy.md`。
> 注意：`python -m quantkit.live.main` 须在 package 根目录下跑，`.env` 也放这里
> （只从 cwd 读）；`strategy.json` 可用绝对路径指向你的工作目录。

## 因子字段是自省的（不写死）
不同 plugin 需要的数据字段不同（carry 因子要 funding/OI/大户多空比）。用
`inspect.signature(build_signal)` 自动得出，数据层据此从 market_features 1d 切面板。
```python
from quantkit.plugins import load_plugin
load_plugin("example_plugin/carry_dislocation_positioning_mean_reversion.py").required_fields
```
样例：`examples/02_inspect_plugin.py` / `examples/03_fetch_data.py`。
细节：`reference/plugin_contract.md`、`reference/data_service.md`。

## 模块地图
| 模块 | 作用 |
|---|---|
| `quantkit.plugins` | 加载 plugin + 自省所需字段 |
| `quantkit.backtest` | 回测服务客户端（submit_cs/ts + 轮询 + 取结果） |
| `quantkit.data.gateway_client` | 取 1d bars/readiness/feature(8778) + funding(8777)；取数依赖内置于 `_gateway/` |
| `quantkit.data.panels` | 切面板 + 本地跑 build_signal |
| `quantkit.compose` | 多因子截面 z-score 加权 composite → 截面权重 |
| `quantkit.live.*` | 币安实盘日度调仓引擎 |

## 关键约束
- 回测 `factors` 1..5、`(job_id,plugin)` 不重复、custom 权重和=1.0、CS percent∈(0,50]
- 实盘默认 `BINANCE_TESTNET=true`，确认无误再切主网
- 数据服务只需本机 `grpcurl`（取数依赖已内置）；只用 1d，bars 上限 300 根
- 卡住先查 `reference/troubleshooting.md`（服务探活 / grpcurl 安装 / 字段缺失 / cwd 依赖）
