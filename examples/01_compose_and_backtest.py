#!/usr/bin/env python3
"""样例 1：把多个已归档因子组合成截面策略，提交回测，取结果。

回测路径不在本地算信号——服务端用 plugin 的 C# 片段编译跑 Lean。所以这里只需
给 (job_id, plugin)。job_id 来自 quant-factor-loop 归档，找法见
reference/backtest_submit.md（S3: s3://quant-factor-loop-archive-apse1/quant/<job_id>/step4/）。

把下面的 JOB_A / PLUGIN_A 换成你自己的归档因子后运行：

    python examples/01_compose_and_backtest.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quantkit.backtest import BacktestClient, Factor  # noqa: E402

# ↓↓↓ 换成你自己的归档因子（job_id + step4 下的 plugin 文件名）
JOB_A, PLUGIN_A = "job_20260511_091436_a73c28", "chaikin_money_flow.py"
JOB_B, PLUGIN_B = "job_20260511_091436_a73c28", "chaikin_money_flow.py"  # demo 占位


def main() -> None:
    bt = BacktestClient()  # 默认 http://13.215.186.241:8001
    print("提交截面策略到", bt.base)

    resp = bt.submit_cs(
        factors=[Factor(JOB_A, PLUGIN_A)],            # 单因子；多因子见下方注释
        ranking={"mode": "N", "value": 5},
        strategy_type="neutral",
        # start_date="2024-06-01", end_date="2025-12-31",
    )
    # 多因子 + 自定义权重示例：
    # resp = bt.submit_cs(
    #     factors=[Factor(JOB_A, PLUGIN_A), Factor(JOB_B, PLUGIN_B)],
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
