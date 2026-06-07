#!/usr/bin/env python3
"""样例 2：自省一个因子 plugin 需要哪些数据字段。

实盘路径要在本地跑 build_signal，必须知道每个 plugin 要哪些字段——这一步靠
inspect 函数签名自动得出，不写死。运行：

    python examples/02_inspect_plugin.py
    python examples/02_inspect_plugin.py /path/to/your_factor.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.plugins import load_plugin  # noqa: E402

DEFAULTS = [
    "example_plugin/flow_confirmed_smooth_trend_momentum.py",
    "example_plugin/trade_size_toxicity_flow_persistence.py",
    "example_plugin/carry_dislocation_positioning_mean_reversion.py",
]


def main() -> None:
    # main
    root = Path(__file__).resolve().parents[1]
    paths = sys.argv[1:] or [str(root / p) for p in DEFAULTS]
    for path in paths:
        p = load_plugin(path)
        print(f"\n{p.factor_type}")
        print(f"  file:    {p.source_path}")
        print(f"  params:  {p.default_params}")
        print(f"  fields:  {p.required_fields}")
        print("           （这些名字 = market_features 1d 列名，数据层据此切面板）")


if __name__ == "__main__":
    main()
