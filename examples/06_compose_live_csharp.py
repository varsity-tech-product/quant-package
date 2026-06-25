#!/usr/bin/env python3
"""样例 6：把因子组合渲染成 Lean **实盘 C# 策略**（binance_direct）。

这条路把执行交给 exchange-gateway 的 Lean ``binance_direct`` 通道（直连币安 USD-M），
而不是 quantkit.live 的 Python 直连。渲染出的策略与回测**同口径**（同一套 composite
+ 调仓数学），只是数据/下单外壳换成了实时行情 + AddCryptoFuture 真实合约。

本样例**只渲染并打印** C# 源码 + 启动命令，不真正起 Lean（起 Lean 需本机装好
Lean 运行时 + paper-runner + gateway 插件，见 reference/lean_live_composer.md）。

    python examples/06_compose_live_csharp.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.compose_csharp import Ranking, StrategySpec, Weighting  # noqa: E402
from quantkit.compose_csharp import render_live_strategy  # noqa: E402
from quantkit.live.gateway_launch import (  # noqa: E402
    GatewayLaunchConfig,
    build_env,
    paper_runner_command,
    write_live_strategy,
)
from quantkit.plugins import load_plugin  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# ── 可改：因子组合（plugin 路径 + 权重）+ 可交易票池 ────────────────────────
FACTOR_SPECS = [
    (ROOT / "example_plugin" / "flow_confirmed_smooth_trend_momentum.py", 0.6),
    (ROOT / "example_plugin" / "trade_size_toxicity_flow_persistence.py", 0.4),
]
SYMBOLS = ["btcusdt", "ethusdt", "solusdt", "bnbusdt", "xrpusdt", "adausdt"]


def main() -> None:
    plugins = [load_plugin(p) for p, _ in FACTOR_SPECS]
    weights = [w for _, w in FACTOR_SPECS]

    spec = StrategySpec(
        weighting=Weighting("custom", weights),
        ranking=Ranking("percent", 20),   # 多空各取 20%
        strategy_type="neutral",
        rebalance_bars=1,                  # 每日调仓
    )

    print("因子:", [(p.factor_type, w) for p, w in zip(plugins, weights)])
    print(f"票池: {len(SYMBOLS)} 个；ranking={spec.ranking.mode}/{spec.ranking.value} "
          f"strategy_type={spec.strategy_type}")

    # 任一因子声明了 futures/on-chain 额外列 → 订上 market_features 流。
    need_features = any(p.sections.get("__EXTRA_BUF_TOARRAY__", "").strip() for p in plugins)
    print(f"需要 market_features 流: {need_features}")

    source, class_name = render_live_strategy(
        plugins, spec, SYMBOLS, subscribe_features=need_features, bar_size="1d"
    )
    print(f"\n渲染策略类: {class_name}  ({len(source)} chars)")

    # 写到带时间戳的工作目录（按 SKILL 约定，不散落在 package 里）。
    workdir = ROOT / "_live_strategy_out"
    src_path, _ = write_live_strategy(
        plugins, spec, SYMBOLS, workdir, subscribe_features=need_features
    )
    print(f"已写: {src_path}")

    # 演示启动 env / 命令（不真正起 Lean）。真实运行需 EXCHANGE_GATEWAY_REPO 等。
    cfg = GatewayLaunchConfig(
        instance_id="binance-direct-live-001",
        gateway_repo=Path("/path/to/exchange-gateway"),
        lean_root=Path("/path/to/lean"),
        lean_plugin_dir=Path("/path/to/lean/plugins"),
    )
    env = build_env(cfg, class_name, src_path, dry_run=True, base_env={})
    print("\n启动命令:")
    print("  " + " ".join(paper_runner_command(cfg)))
    print("关键环境变量（dry-run=true，安全）:")
    for k in ("LEAN_EXECUTION_PROFILE", "LEAN_STRATEGY_CLASS_NAME", "EXCHANGE_GATEWAY_SECURITY_MODEL",
              "EXCHANGE_GATEWAY_AGGTRADE_KLINE_URL", "LEAN_STRATEGY_PARAMETERS_JSON"):
        print(f"  {k}={env[k]}")
    print("\n真实下单：设 dry-run=false 并按 reference/lean_live_composer.md 配好 Lean 运行时。")


if __name__ == "__main__":
    main()
