# 策略回测提交（速查）

服务地址：`http://quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com`（无需 API key）。
完整文档：`/home/ec2-user/quantai-service/docs/strategy_submit.md`。

把因子 plugin 的源码内容直接提交（content 模式），服务端组装策略跑 MatchX 回测，轮询取结果。

## 因子 plugin 从哪来
任意一份 quant-factor-loop step4 plugin .py 都行，**直接传文件内容、不需要 job_id**：
- 本仓 `sample_factors/` 里的归档样例（文件名 `<job_id>__<plugin>.py`，仅作来源溯源）
- 你自己的因子，如 `/mnt/efs-b/quant-factor-loop/.quant/<job>/step4/x.py`

> 样例 `example_plugin/` 也能直接回测；它演示的就是 plugin 标准格式。

## 用本包提交
```python
from quantkit.backtest import BacktestClient, Factor
bt = BacktestClient()                                  # http://quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com

# 截面策略 —— Factor.from_file 读出整段 .py 源码发过去
resp = bt.submit_cs(
    factors=[
        Factor.from_file("sample_factors/job_20260418_185701_5a9c12__trend_pullback_resumption.py"),
        Factor.from_file("/mnt/efs-b/quant-factor-loop/.quant/job_xxx/step4/factor_b.py", name="factor_b"),
    ],
    weighting={"mode": "custom", "weights": [0.6, 0.4]},   # 省略=equal
    ranking={"mode": "N", "value": 5},                     # 或 {"mode":"percent","value":10}
    strategy_type="neutral",                               # long_only / short_only / neutral
)
sid = resp["strategy_id"]
bt.wait(sid)                                               # 轮询到 completed/failed
print(bt.summary(sid)["metrics"])                          # sharpe / net_profit_pct / ...
bt.equity_curve(sid); bt.orders(sid)

# 时序策略（自己指定 symbols）
bt.submit_ts(symbols=["btcusdt","ethusdt"],
             factors=[Factor.from_file("sample_factors/...py")])
```

`Factor.from_content(src, name=...)` 可直接传内存里的源码字符串。`name` 缺省时
`from_file` 取文件名 stem，服务端再缺省则回退 plugin 里的 `FACTOR_TYPE`。

## 关键约束（本地已先校验，减少 422）
- `factors` 1..20；**content 模式不去重**（传重复 = 权重翻倍，自负责）
- `name` 可省略（缺省取文件 stem → 服务端回退 `FACTOR_TYPE`）
- `custom` 权重长度=factors、全>0、和=1.0（±1e-6）
- CS `ranking`：`N` 正整数 / `percent` ∈ (0,50]
- TS `symbols` 1..20

## 端点速查
```
POST /strategies/submit       截面
POST /strategies/submit_ts    时序
GET  /strategies/{sid}        状态+meta（轮询 state.status）
GET  /strategies/{sid}/summary        指标卡
GET  /strategies/{sid}/equity_curve   净值曲线
GET  /strategies/{sid}/orders         成交明细
GET  /strategies/{sid}/result         完整原始结果
```
