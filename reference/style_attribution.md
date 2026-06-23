# 策略预测值风格归因（速查）

口径来源：外部文档 `cs_style_attribution.md`。核心算法 vendored 到
`quantkit/style_attribution.py`（逐字搬运，逻辑不改），package 胶水层在
`quantkit/attribution.py`。

## 它做什么 / 不做什么

- **做**：每个 `timestamp` 横截面内，按策略**预测值**排序，取最高 `top_pct` 为多头桶、
  最低 `top_pct` 为空头桶，统计两桶对 7 个基础风格因子的平均暴露（CS z 单位），并算
  `long - short` 风格倾向 + 预测值与各风格的 rolling Spearman 相关。回答
  **"策略选币偏向哪些风格"**。
- **不做**：不拆解回测盈亏（P&L attribution）。这是**预测值(信号)归因**，不是收益归因。

## 预测面板从哪来（关键）

回测在服务端编译 C# 跑 Lean，结果（`summary/orders/charts/result`）里**没有**每期每币
的 composite 预测值面板。所以这里用 `quantkit.compose.composite_signal` 在本地按
**与回测同口径**复算预测面板（每因子 `build_signal` → 截面 z-score → 按权重加权），
再喂给归因。归因对象因此与回测策略同口径，只是面板是本地重算的。

## 用本包跑

```python
from quantkit.compose import WeightedFactor
from quantkit.plugins import load_plugin
from quantkit.data.gateway_client import GatewayClient
from quantkit.attribution import attribute_strategy

gw = GatewayClient()
bars = gw.fetch_bars_panel(universe, limit=300)          # 票池要够宽
funding = {s: gw.fetch_funding(s) for s in bars}          # 可选；缺则 style_funding=NaN
factors = [
    WeightedFactor(load_plugin("momentum.py"), 0.6),
    WeightedFactor(load_plugin("taker_flow.py"), 0.4),
]
res = attribute_strategy(
    factors, bars, funding=funding,
    top_pct=0.2, min_cs_size=20, roll_window=60,
    market_symbol="BTCUSDT", save_path="attribution.png",
)
print(res["long_short_exposure"].sort_values(key=abs, ascending=False).round(4))
```

样例：`examples/05_style_attribution.py`（取宽票池→归因→存 png/json/csv）。

## 7 个基础风格

| 字段 | 计算口径 |
| --- | --- |
| `style_liquidity` | `rolling mean(amount)` 后 log |
| `style_volatility` | log return rolling std |
| `style_momentum` | `close.pct_change(20)` |
| `style_reversal` | `-close.pct_change(3)` |
| `style_volume_momentum` | `amount.pct_change(20)` 后 `log1p` |
| `style_funding` | rolling mean funding |
| `style_beta` | rolling cov(symbol, BTC)/var(BTC) |

每个风格归因前在同期截面内做 z-score，暴露值单位是横截面标准差。

## 数据映射 / 依赖

- gateway 1d bar **没有 `amount` 列**，成交额在 `quote_volume` → 胶水层默认
  `amount_field="quote_volume"` 映射为 `amount`。
- `style_beta` 需 universe 里含 `market_symbol`（默认 BTCUSDT）且 rolling 历史足够。
- funding 走 8777；当前网关常返回空，缺则 `style_funding=NaN`（已优雅处理）。
- 画图 + Spearman 相关需 `pip install matplotlib scipy`。无头环境用 `save_path` 存图。

## 限制 / 注意

- **窗口 ≤ ~300 天**：gateway 1d 单 symbol ≤300 根。回测窗口更长时，本地归因只覆盖其近期子集。
- **票池要够宽**：每期不足 `min_cs_size` 的截面会被跳过；票池太窄 → 结果稀疏甚至全空。
  `min_cs_size` 随票池调。
- universe 会漂移（如 MATIC→POL）：示例逐 symbol 取数，跳过未分配/取不到的。
- `style_volume_momentum`：当 `amount` 某期归零，vendored `log1p(pct_change)` 会出现
  `-inf`（外部口径原样保留，仅 RuntimeWarning）；个别期该风格 z-score 可能失真。
```
