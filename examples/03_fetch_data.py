#!/usr/bin/env python3
"""样例 3：从 exchange-gateway 数据服务取 1d 行情，拼成因子需要的面板。

依赖：本机装了 grpcurl（取数依赖已内置，无需 exchange-gateway 仓库）。
bars/readiness 走 8778 aggtrade-kline-gateway（≤300 根），funding 走 8777。

    python examples/03_fetch_data.py BTCUSDT ETHUSDT SOLUSDT BNBUSDT
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.data.gateway_client import GatewayClient  # noqa: E402
from quantkit.data.panels import build_panels  # noqa: E402
from quantkit.plugins import load_plugin  # noqa: E402


def main() -> None:
    # main
    symbols = sys.argv[1:] or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    gw = GatewayClient()  # 默认 klines/features=8778, funding=8777

    print("readiness:", gw.is_ready(symbols))
    bars = gw.fetch_bars_panel(symbols, limit=300)
    for sym, df in bars.items():
        print(f"{sym}: {df.shape[0]} bars, cols={list(df.columns)[:6]}..., last={df.index[-1].date()}")

    # 切成某个 K 线类因子需要的面板
    root = Path(__file__).resolve().parents[1]
    p = load_plugin(root / "example_plugin/flow_confirmed_smooth_trend_momentum.py")
    panels = build_panels(p, bars)
    print(f"\n{p.factor_type} 面板: {list(panels)}  shape={panels['close'].shape}")


if __name__ == "__main__":
    main()
