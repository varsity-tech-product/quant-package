#!/usr/bin/env python3
"""样例 5：对一个因子组合做"预测值风格归因"。

归因对象是**策略的预测值（composite 信号）**，不是回测盈亏：每个截面按预测值排序
取多空桶，看两边对基础风格因子（流动性/波动/动量/反转/量动量/资金费/beta）的暴露差。
预测面板用 compose 在本地按**与回测同口径**复算（回测在服务端，不吐预测面板）。

依赖：本机装了 grpcurl（取数）；pip install matplotlib scipy（画图 + Spearman）。
注意：gateway 1d ≤300 根 ≈ 300 天，所以归因窗口最多覆盖最近 ~300 天。

    python examples/05_style_attribution.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.attribution import attribute_strategy  # noqa: E402
from quantkit.compose import WeightedFactor  # noqa: E402
from quantkit.data.gateway_client import GatewayClient  # noqa: E402
from quantkit.plugins import load_plugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# ── 可改：票池要够宽（分桶 + min_cs_size），窗口 ≤300 天 ───────────────────────
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "AVAXUSDT", "LINKUSDT", "LTCUSDT", "DOTUSDT", "TRXUSDT", "MATICUSDT", "BCHUSDT",
    "ATOMUSDT", "UNIUSDT", "ETCUSDT", "FILUSDT", "APTUSDT", "ARBUSDT", "OPUSDT",
    "NEARUSDT", "INJUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "AAVEUSDT", "RUNEUSDT",
    "LDOUSDT", "STXUSDT",
]
LOOKBACK = 300

# ── 可改：你的因子组合（plugin 路径 + 权重）。这里用包内 example_plugin 演示 ──
FACTOR_SPECS = [
    (ROOT / "example_plugin" / "flow_confirmed_smooth_trend_momentum.py", 0.6),
    (ROOT / "example_plugin" / "trade_size_toxicity_flow_persistence.py", 0.4),
]


def main() -> None:
    gw = GatewayClient()
    print(f"取 {len(UNIVERSE)} 个 symbol 的 1d bars (limit={LOOKBACK}) ...")
    # 逐 symbol 取，跳过网关未分配/取不到的（universe 会随时间漂移）
    bars = {}
    skipped = []
    for sym in UNIVERSE:
        try:
            df = gw.fetch_bars(sym, limit=LOOKBACK)
        except Exception as exc:  # noqa: BLE001 — 单 symbol 失败不应中断整批
            skipped.append((sym, str(exc).splitlines()[-1].strip()))
            continue
        if df is not None and not df.empty:
            bars[sym] = df
        else:
            skipped.append((sym, "no bars"))
    print(f"  实际取到 {len(bars)} 个 symbol；跳过 {len(skipped)}: {[s for s, _ in skipped]}")

    funding = {sym: gw.fetch_funding(sym, limit=1000) for sym in bars}
    have_funding = sum(1 for v in funding.values() if v is not None and len(v))
    print(f"  funding 可用 {have_funding}/{len(bars)} 个（缺则 style_funding=NaN）")

    factors = [WeightedFactor(load_plugin(p), w) for p, w in FACTOR_SPECS]
    print("因子:", [(f.plugin.factor_type, f.weight) for f in factors])

    out_png = ROOT / "style_attribution.png"
    res = attribute_strategy(
        factors,
        bars,
        funding=funding if have_funding else None,
        top_pct=0.2,
        min_cs_size=min(20, max(5, len(bars) // 2)),
        roll_window=60,
        market_symbol="BTCUSDT",
        save_path=str(out_png),
        title_prefix="Strategy Composite",
    )

    print(f"\n归因期数: {len(res['long_ts'])}（窗口 ~{LOOKBACK} 天上限）")
    print("\nlong-short 风格暴露（按 |暴露| 排序，CS z 单位）:")
    print(res["long_short_exposure"].sort_values(key=abs, ascending=False).round(4))

    exposure = {
        "long_short_exposure": res["long_short_exposure"].round(6).to_dict(),
        "long_exposure": res["long_exposure"].round(6).to_dict(),
        "short_exposure": res["short_exposure"].round(6).to_dict(),
        "periods": int(len(res["long_ts"])),
        "lookback_days": LOOKBACK,
        "note": "prediction(信号)风格归因；非回测盈亏归因；窗口≤300天",
    }
    (ROOT / "style_exposure.json").write_text(json.dumps(exposure, indent=2, ensure_ascii=False))
    res["roll_corr"].to_csv(ROOT / "style_roll_corr.csv", index=False)
    print(f"\n已存: {out_png.name} / style_exposure.json / style_roll_corr.csv")


if __name__ == "__main__":
    main()
