# 因子 plugin 契约

每个因子 plugin 是一个 `.py` 文件，统一导出：

| 导出 | 类型 | 用途 |
|---|---|---|
| `FACTOR_TYPE` | str | 因子名 |
| `FACTOR_DEFAULT_PARAMS` | dict | 默认参数 |
| `FACTOR_SECTIONS` | dict | 给回测引擎渲染 C# 策略的占位符片段（回测路径用） |
| `build_signal(close, params, <若干具名 DataFrame>, **_kwargs) -> DataFrame` | 函数 | Python 版信号计算（实盘路径用） |

## build_signal 的输入/输出
- 输入：`close` + 一组 `[date x symbol]` 的 DataFrame，**参数名即数据字段名**。
- 输出：`[date x symbol]` 的信号 DataFrame，对齐 `close`。

字段名与数据服务 `market_features` 1d 的 35 列 schema 一一对应，常见的有：

```
close volume
taker_buy_volume taker_sell_volume
taker_buy_quote_volume taker_sell_quote_volume
taker_buy_trades taker_sell_trades
open_interest_close funding_rate_close
binance_premium_index_close
top_account_long_percent top_account_short_percent
global_account_long_percent global_account_short_percent
top_position_long_percent top_position_short_percent
```

## 字段自省（不写死）
不同 plugin 需要的字段不同。代码用 `inspect.signature(build_signal)` 自动得出：

```python
from quantkit.plugins import load_plugin
p = load_plugin("example_plugin/carry_dislocation_positioning_mean_reversion.py")
p.required_fields
# ['funding_rate_close','binance_premium_index_close','open_interest_close',
#  'top_account_long_percent','top_account_short_percent']
```

数据层据此从 market_features 切出对应列，拼成面板再喂给 `build_signal`。
某字段在数据源里找不到时抛 `MissingFieldError`，不会静默填 0。

## 两条路径用 plugin 的方式不同
- **回测提交**：服务端用 `FACTOR_SECTIONS`（C#）编译跑 Lean。本地只需 `{job_id, plugin}`，**不跑 build_signal**。
- **实盘**：本地跑 `build_signal`（见 `quantkit.data.panels.run_build_signal` / `quantkit.compose`）。
