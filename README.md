# quant-package

把截面因子 plugin 组合成策略 → 提交回测 → 取结果 → 部署币安实盘的 Skill + 工具包。

## 安装为 Claude Code skill
```bash
npx skills add varsity-tech-product/quant-package -a claude-code -y
```
装完后 AI 读 `SKILL.md` 即可端到端操作。

## 直接用工具包
```bash
pip install -r requirements.txt
```

三大能力：
1. **组合 + 回测**：`quantkit.backtest` 提交到 `http://13.215.186.241:8001`，轮询取结果。
2. **本地信号**：`quantkit.plugins` + `quantkit.data` + `quantkit.compose`，从数据服务取 1d 行情跑 `build_signal`。
3. **实盘部署**：`quantkit.live` 币安 Futures 日度调仓（默认 testnet）。

## 快速开始
```bash
python examples/02_inspect_plugin.py          # 看因子需要哪些字段
python examples/01_compose_and_backtest.py    # 组合+回测（改成你的 job_id）
python examples/03_fetch_data.py BTCUSDT ETHUSDT   # 取 1d 数据（需 grpcurl + 数据服务）
python examples/04_deploy_live.py             # 实盘跑一次（需 .env + strategy.json）
```

## 文档
- `SKILL.md` — AI 入口
- `reference/plugin_contract.md` — 插件契约 + 字段自省
- `reference/backtest_submit.md` — 回测提交速查
- `reference/data_service.md` — exchange-gateway 数据服务（1d）
- `reference/live_deploy.md` — 实盘部署
- `reference/troubleshooting.md` — 已知卡点 / 排错

## 目录
```
quantkit/         核心库（plugins / backtest / compose / data / live）
examples/         端到端样例脚本 + strategy.example.json
example_plugin/   3 个样例因子 plugin（演示插件格式）
sample_factors/   12 个带 job_id 的归档因子（无自有因子时直接回测，catalog.json 索引）
reference/        细节文档
scripts/commit.sh 频繁提交小工具
```
