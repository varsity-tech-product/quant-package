# 排错 / 已知卡点

实测走完 组合→回测→实盘 后整理的踩坑点，AI 用本包前先扫一眼。

## 回测路径

### 服务连不上（Connection refused）
`BacktestClient` 所有请求报 `Connection refused` → 回测服务 `quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com`
没在跑。**先探活**：
```python
BacktestClient().list_strategies()   # 连不上就是服务没启动，不是用法错
```
连不上时联系服务维护者启动，不要反复重试。

### 提交前本地已校验
`factors` 1..20、custom 权重和=1.0、CS percent∈(0,50]——这些本地先报 `ValueError`，
不用等服务端 422。content 模式**不去重**（传重复=权重翻倍，自负责）。

## 实盘 / 本地取数路径

### grpcurl 没装
`reference/data_service.md` 要求本机有 `grpcurl`，但很多机器没有。用户级安装（不动系统）：
```bash
curl -sL https://github.com/fullstorydev/grpcurl/releases/download/v1.9.1/grpcurl_1.9.1_linux_x86_64.tar.gz \
  | tar xz -C ~/.local/bin grpcurl
grpcurl --version
```
跑 live 脚本时确保 `~/.local/bin` 在 PATH 里。

### MissingFieldError: quote_volume / amount
已修：`gateway_client._BAR_FIELD_ALIASES` 现含 `amount→quote_volume`、`trade_count→trades`。
若再遇到某字段缺失，先看 `fetch_bars_panel` 返回的真实列名，按需在别名表补映射——
本包**不静默填 0**，缺字段直接抛错。

### required_fields 自省为空但因子其实要数据
因子若从 `**kwargs`/`**data` 里 `data.get("xxx")` 取数（而非声明具名参数），
`required_fields` 会漏报，实盘会拿到 None。提交回测不受影响（服务端算信号）；
**实盘前**打开 .py 确认取数方式。写新因子请把字段声明成具名参数。

### .env / cwd 依赖
`quantkit` 未打包，`python -m quantkit.live.main` 必须在 package 根目录下跑，
且 `.env` 只从 cwd 读。`strategy.json` 可用绝对路径放别处，但 `.env` 要放在 package 根目录。

## 实盘下单

### 必须用户自备 Binance API key
本包不内置任何交易密钥。`--once` 预检会 fail-fast：`BINANCE_API_KEY / ... 未配置`。
- **testnet（默认，先用）**：https://testnet.binancefuture.com 注册后页面下方生成，
  与主网 key **不通用**，资金是模拟的。
- 主网（`BINANCE_TESTNET=false`）：binance.com API 管理，开「合约交易」权限。
AI 应主动向用户索要 key 并帮其写入 `.env`（见 SKILL.md「实盘前先要 key」）。
