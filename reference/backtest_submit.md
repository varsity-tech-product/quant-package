# 策略回测提交（速查）

服务地址：`http://quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com`（无需 API key）。
完整文档：`/home/ec2-user/quantai-service/docs/strategy_submit.md`。

在已归档（有 job_id）的因子之上组装策略，提交到 MatchX 回测引擎，轮询取结果。

## job_id / plugin 从哪找
归档在 S3：
```
s3://quant-factor-loop-archive-apse1/quant/<job_id>/step4/<factor>.py
```
列 job：`aws s3 ls s3://quant-factor-loop-archive-apse1/quant/ --region ap-southeast-1`
列因子文件：`aws s3 ls s3://.../quant/<job_id>/step4/ --region ap-southeast-1`
提交时填 `{job_id, plugin: "<factor>.py"}`。

> 样例 `example_plugin/` 只演示插件格式；真实回测提交用**已归档有 job_id** 的因子。

## 用本包提交
```python
from quantkit.backtest import BacktestClient, Factor
bt = BacktestClient()                                  # http://quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com

# 截面策略
resp = bt.submit_cs(
    factors=[Factor("job_xxx", "factor_a.py"), Factor("job_yyy", "factor_b.py")],
    weighting={"mode": "custom", "weights": [0.6, 0.4]},   # 省略=equal
    ranking={"mode": "N", "value": 5},                     # 或 {"mode":"percent","value":10}
    strategy_type="neutral",                               # long_only / short_only / neutral
)
sid = resp["strategy_id"]
bt.wait(sid)                                               # 轮询到 completed/failed
print(bt.summary(sid)["metrics"])                          # sharpe / net_profit_pct / ...
bt.equity_curve(sid); bt.orders(sid)

# 时序策略（自己指定 symbols）
bt.submit_ts(symbols=["btcusdt","ethusdt"], factors=[Factor("job_xxx","factor_a.py")])
```

## 关键约束（本地已先校验，减少 422）
- `factors` 1..20；`(job_id, plugin)` 不能重复
- `plugin` 可省略（`Factor(job_id)`），服务端按 job_id 自动反查；旧的 `{job_id, plugin}` 仍兼容
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
