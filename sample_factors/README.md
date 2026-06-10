# 内置样例因子库（已归档，带 job_id）

给**没有自己 job_id / plugin** 的用户：这里 12 个因子都来自 quant-factor-loop 归档，
**可直接用于回测提交**（回测需要 `{job_id, plugin}`，已编进文件名）。

## 文件名约定
```
<job_id>__<plugin>.py
例：job_20260418_185701_5a9c12__trend_pullback_resumption.py
   └── job_id ────────────┘   └── plugin = trend_pullback_resumption.py
```
机器可读清单见 `catalog.json`（每条含 job_id / plugin / factor_type / required_fields /
是否纯量价）。

## 怎么用

### 回测（推荐入口，无需本地数据）
直接拿 job_id + plugin 提交，信号由服务端算：
```python
from quantkit.backtest import BacktestClient, Factor
bt = BacktestClient()
resp = bt.submit_cs(
    factors=[
        Factor("job_20260418_185701_5a9c12", "trend_pullback_resumption.py"),
        Factor("job_20260418_185743_02d1a2", "range_quote_inefficiency_reversal.py"),
    ],
    weighting={"mode": "custom", "weights": [0.6, 0.4]},
    ranking={"mode": "N", "value": 5}, strategy_type="neutral",
)
bt.wait(resp["strategy_id"]); print(bt.summary(resp["strategy_id"])["metrics"])
```

### 实盘 / 本地跑信号
本地 `build_signal` 用文件路径加载即可：
```python
from quantkit.plugins import load_plugin
load_plugin("sample_factors/job_20260418_185701_5a9c12__trend_pullback_resumption.py")
```
实盘 `strategy.json` 的 `factors[].plugin` 直接填这里的文件路径。

## 选因子提示
- `catalog.json` 里 `live_ready=true` 的是**纯量价**因子（只用 OHLCV + taker 量/笔数），
  实盘开箱即用。当前数据服务下**优先选这些**。
- `live_ready=false`（如 `liquidation_*` / `funding_*`）需要清算/资金费/OI 等特殊数据，
  回测能跑，但实盘需先解决这些字段的历史数据来源（见 `reference/data_service.md`）。
- ⚠️ `required_fields` 为 `[]` 不一定真不需要数据：个别因子从 `**kwargs` 取数导致自省为空
  （如 `taker_trade_size_imbalance`），回测不受影响，实盘前请打开 .py 确认。
