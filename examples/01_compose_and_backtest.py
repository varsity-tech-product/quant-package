#!/usr/bin/env python3
"""样例 1：把多个因子 plugin 组合成截面策略，提交回测，取结果。

回测路径不在本地算信号——服务端用 plugin 的 C# 片段编译跑 Lean。所以这里只需
把整段 plugin .py 源码发过去（content 模式），无需 job_id、不查 S3/EFS。
plugin .py 可以是 sample_factors/ 里的样例，也可以是你自己的（如
/mnt/efs-b/quant-factor-loop/.quant/<job>/step4/x.py）。

把下面的 PLUGIN_A / PLUGIN_B 换成你的因子文件后运行：

    python examples/01_compose_and_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.backtest import BacktestClient, Factor  # noqa: E402

# ↓↓↓ 换成你自己的因子 .py 路径（sample_factors/ 或 /mnt/efs-b/.../step4/x.py）
ROOT = Path(__file__).resolve().parents[1]
PLUGIN_A = ROOT / "sample_factors" / "job_20260418_185701_5a9c12__trend_pullback_resumption.py"
PLUGIN_B = ROOT / "sample_factors" / "job_20260418_185743_02d1a2__range_quote_inefficiency_reversal.py"


def main() -> None:
    # main
    bt = BacktestClient()  # 默认 http://quantai-alb-b-1640784904.ap-southeast-1.elb.amazonaws.com
    print("提交截面策略到", bt.base)

    resp = bt.submit_cs(
        factors=[Factor.from_file(PLUGIN_A)],         # 单因子；多因子见下方注释
        ranking={"mode": "N", "value": 5},
        strategy_type="neutral",
        # start_date="2024-06-01", end_date="2025-12-31",
    )
    # 多因子 + 自定义权重示例：
    # resp = bt.submit_cs(
    #     factors=[Factor.from_file(PLUGIN_A), Factor.from_file(PLUGIN_B)],
    #     weighting={"mode": "custom", "weights": [0.6, 0.4]},
    #     ranking={"mode": "percent", "value": 10},
    # )

    sid = resp["strategy_id"]
    print("strategy_id:", sid, "| status:", resp.get("status"))

    print("轮询回测...")
    st = bt.wait(sid, on_progress=lambda s: print("  ->", (s.get("state") or {}).get("match_stage", "")))
    print("最终状态:", (st.get("state") or {}).get("status"))

    summ = bt.summary(sid)
    metrics = summ.get("metrics", {})
    for k in ("sharpe", "net_profit_pct", "annual_return_pct", "max_drawdown_pct", "turnover_pct"):
        print(f"  {k}: {metrics.get(k)}")


if __name__ == "__main__":
    main()
