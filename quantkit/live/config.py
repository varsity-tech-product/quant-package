"""实盘配置。敏感值走环境变量 / .env；策略组合走 strategy.json。

环境变量（.env，见 .env.example）：
  BINANCE_API_KEY / BINANCE_API_SECRET   币安 Futures key
  BINANCE_TESTNET=true                    默认 testnet 下单（强烈建议先 testnet）
  EXCHANGE_GATEWAY_DIR                     exchange-gateway 仓库路径
  GATEWAY_TARGET                           数据服务 gRPC 地址（默认 prod）
  CMC_API_KEY / CMC_TOP_N                  universe = CMC TopN（可选）

strategy.json（策略定义）：
  {
    "universe": {"mode": "cmc_top_n", "n": 10},        // 或 {"mode":"manual","symbols":[...]}
    "factors": [
      {"plugin": "/abs/path/to/factor_a.py", "weight": 0.6, "params": {}},
      {"plugin": "example_plugin/trade_size_toxicity_flow_persistence.py", "weight": 0.4}
    ],
    "ranking": {"mode": "N", "value": 5},
    "strategy_type": "neutral",
    "gross": 1.0
  }
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # dotenv 可选
    pass

# ── 数据服务 ───────────────────────────────────────────────────────────────────
GATEWAY_TARGET = os.environ.get("GATEWAY_TARGET", "13.231.65.185:8777")
EXCHANGE_GATEWAY_DIR = os.environ.get("EXCHANGE_GATEWAY_DIR", "/home/ec2-user/exchange-gateway")
KLINE_LOOKBACK = int(os.environ.get("KLINE_LOOKBACK", "1000"))  # 1d bars 拉多少根

# ── 币安下单 ───────────────────────────────────────────────────────────────────
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
BINANCE_TESTNET = os.environ.get("BINANCE_TESTNET", "true").lower() == "true"
BINANCE_TRADE_REST = (
    "https://testnet.binancefuture.com" if BINANCE_TESTNET else "https://fapi.binance.com"
)

# ── universe (CMC) ─────────────────────────────────────────────────────────────
CMC_API_KEY = os.environ.get("CMC_API_KEY", "")
CMC_TOP_N = int(os.environ.get("CMC_TOP_N", "10"))
STABLECOINS = {"USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDE", "USDD", "USDP", "FRAX"}

# ── 风控 / 下单参数 ─────────────────────────────────────────────────────────────
LEVERAGE = int(os.environ.get("LEVERAGE", "1"))
MAX_SINGLE_WEIGHT = float(os.environ.get("MAX_SINGLE_WEIGHT", "0.40"))
MIN_ORDER_NOTIONAL = float(os.environ.get("MIN_ORDER_NOTIONAL", "20.0"))
MAX_DRAWDOWN_HALT = float(os.environ.get("MAX_DRAWDOWN_HALT", "-0.20"))
LIMIT_ORDER_TIMEOUT = int(os.environ.get("LIMIT_ORDER_TIMEOUT", "60"))

# ── 日度 rebalance 时间（UTC）──────────────────────────────────────────────────
REBALANCE_HOUR_UTC = int(os.environ.get("REBALANCE_HOUR_UTC", "0"))
REBALANCE_MINUTE_UTC = int(os.environ.get("REBALANCE_MINUTE_UTC", "5"))

# ── 路径 ───────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get("LIVE_WORK_DIR", BASE_DIR))
DATA_DIR = WORK_DIR / "data"
LOG_DIR = WORK_DIR / "logs"
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class FactorSpec:
    plugin: str
    weight: float = 1.0
    params: dict = field(default_factory=dict)


@dataclass
class StrategyConfig:
    factors: list[FactorSpec]
    ranking: dict
    strategy_type: str = "neutral"
    gross: float = 1.0
    universe: dict = field(default_factory=lambda: {"mode": "cmc_top_n", "n": CMC_TOP_N})

    @classmethod
    def load(cls, path: str | Path) -> "StrategyConfig":
        data = json.loads(Path(path).expanduser().read_text())
        factors = [FactorSpec(**f) for f in data["factors"]]
        return cls(
            factors=factors,
            ranking=data["ranking"],
            strategy_type=data.get("strategy_type", "neutral"),
            gross=float(data.get("gross", 1.0)),
            universe=data.get("universe", {"mode": "cmc_top_n", "n": CMC_TOP_N}),
        )
