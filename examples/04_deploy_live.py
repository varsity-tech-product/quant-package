#!/usr/bin/env python3
"""样例 4：部署实盘（默认 testnet，先跑一次验证）。

前置：
  1. cp .env.example .env 并填好 BINANCE_API_KEY/SECRET（先 testnet）、EXCHANGE_GATEWAY_DIR
  2. cp examples/strategy.example.json strategy.json 并改成你的因子组合

跑一次（不起调度器）：
    python examples/04_deploy_live.py            # 等价 python -m quantkit.live.main --strategy strategy.json --once

常驻（每日 00:05 UTC 自动调仓）：
    python -m quantkit.live.main --strategy strategy.json
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.live.main import main as live_main  # noqa: E402


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    strategy = sys.argv[1] if len(sys.argv) > 1 else str(root / "strategy.json")
    raise SystemExit(live_main(["--strategy", strategy, "--once"]))
