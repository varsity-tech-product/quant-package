# 实盘部署（币安 Futures 日度调仓）

基于 quanton 改造：保留 main→scheduler→rebalancer→factor→executor 骨架，
数据层换成 exchange-gateway（1d），因子层换成多 plugin 组合。

## 流程
```
每日 00:05 UTC
  → 解析 universe（CMC TopN 或手工列表）
  → exchange-gateway 取每 symbol 最近 1000 根 1d bars（readiness 检查 + 失败关闭）
  → 多 plugin 组合：build_signal → 截面 z-score → 加权 composite → 排名取多空
  → 查币安余额 → 计算 delta → 限价挂盘口(超时市价兜底) 调仓
  → 写 data/rebalance_log.jsonl
```
组合口径与回测服务 CS 语义一致，回测/实盘可比。

## 部署步骤
```bash
cd quant-package
cp .env.example .env            # 填 BINANCE_API_KEY/SECRET（先 testnet）、EXCHANGE_GATEWAY_DIR、CMC_API_KEY
cp examples/strategy.example.json strategy.json   # 改成你的因子组合
pip install -r requirements.txt

# 先跑一次验证（不起调度器，默认 testnet）
python -m quantkit.live.main --strategy strategy.json --once

# 常驻（每日自动调仓）
python -m quantkit.live.main --strategy strategy.json
```

## strategy.json
```json
{
  "universe": {"mode": "cmc_top_n", "n": 10},
  "factors": [
    {"plugin": "/mnt/efs-b/quant-factor-loop/.quant/<job>/step4/factor_a.py", "weight": 0.6},
    {"plugin": "example_plugin/trade_size_toxicity_flow_persistence.py", "weight": 0.4}
  ],
  "ranking": {"mode": "N", "value": 5},
  "strategy_type": "neutral",
  "gross": 1.0
}
```
- `universe`: `{"mode":"manual","symbols":[...]}` 或 `{"mode":"cmc_top_n","n":N}`
- `factors[].plugin`: 你的因子文件路径（实盘跑它的 build_signal）
- `ranking` / `strategy_type` / `gross` 同回测

## 风控（.env 可调）
- `BINANCE_TESTNET=true` 默认 testnet，**确认无误再切主网**
- `LEVERAGE`（默认 1=不加杠杆）、`MAX_SINGLE_WEIGHT`（单币上限）
- `MIN_ORDER_NOTIONAL`（小额 delta 不下单）、`MAX_DRAWDOWN_HALT`（回撤超阈值停止）
- 下单：限价挂盘口做 Maker，`LIMIT_ORDER_TIMEOUT` 秒未成交撤单市价兜底；单向持仓模式

## 注意
- carry 类因子需要 OI/premium/大户多空比**历史**，见 data_service.md「feature 历史」。
  K 线类因子开箱即用。
- 下单走币安（testnet/mainnet 按 .env 切）；行情只走数据服务。
