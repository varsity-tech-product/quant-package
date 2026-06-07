"""日度 rebalance 主流程（每日 00:05 UTC 触发一次）。

流程：
  1. 解析 universe（CMC TopN 或手工列表）
  2. 从 exchange-gateway 取每个 symbol 最近 1000 根 1d bars（失败关闭语义）
  3. 跑因子组合 -> 最新截面目标权重
  4. 查账户余额 -> 执行调仓
  5. 写 rebalance 日志

数据说明：K 线类因子（close/volume/taker_*）直接用 GetHistoricalBars。
若某因子需要 OI/premium/大户多空比历史（如 carry 因子），build_panels 会抛
MissingFieldError——这类 feature 历史需另接 market_features 1d（见 reference/data_service.md）。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..data.gateway_client import GatewayClient
from . import config
from .config import StrategyConfig
from .executor import BinanceFuturesExecutor
from .factor import compute_target_weights
from .universe import resolve_universe

logger = logging.getLogger("rebalancer")

REBALANCE_LOG = config.DATA_DIR / "rebalance_log.jsonl"
MIN_SYMBOLS = 4


async def run_daily_rebalance(
    strategy: StrategyConfig,
    executor: BinanceFuturesExecutor,
    gateway: GatewayClient,
) -> None:
    """完整日度调仓。所有异常应由调用方捕获，不让进程崩溃。"""
    run_time = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info("开始日度 rebalance @ %s", run_time.isoformat())

    # ── 1. universe ──────────────────────────────────────────────────────────
    symbols = await resolve_universe(strategy.universe)
    if len(symbols) < MIN_SYMBOLS:
        logger.error("universe 不足 %d 个，跳过", MIN_SYMBOLS)
        return

    # ── 2. 取 1d 行情（readiness 健康检查 + 拉 bars）────────────────────────
    try:
        ready = gateway.is_ready(symbols, limit=config.KLINE_LOOKBACK)
        not_ready = [s for s in symbols if not ready.get(s, False)]
        if not_ready:
            logger.warning("以下 symbol readiness 未就绪，可能被跳过: %s", not_ready)
    except Exception as e:
        logger.warning("readiness 检查失败（继续尝试取数）: %s", e)

    bars_panel = gateway.fetch_bars_panel(symbols, limit=config.KLINE_LOOKBACK)
    got = list(bars_panel.keys())
    missing = [s for s in symbols if s not in bars_panel]
    if missing:
        logger.warning("以下 symbol 取数失败，从 universe 移除: %s", missing)
    if len(got) < MIN_SYMBOLS:
        logger.error("有效行情不足 %d 个，跳过本次 rebalance", MIN_SYMBOLS)
        return

    # ── 3. 因子组合 -> 目标权重 ───────────────────────────────────────────────
    try:
        target_weights, debug = compute_target_weights(strategy, bars_panel)
    except Exception as e:
        logger.error("信号计算失败: %s", e)
        return

    # ── 4. 余额 + 调仓 ────────────────────────────────────────────────────────
    try:
        balance = await executor.get_balance()
    except Exception as e:
        logger.error("查询余额失败: %s，跳过", e)
        return

    logger.info("余额 %.2f USDT，目标权重 %s", balance, debug["weights"])
    try:
        await executor.rebalance(target_weights, balance)
    except Exception as e:
        logger.error("执行调仓失败: %s", e)
        return

    # ── 5. 日志 ──────────────────────────────────────────────────────────────
    entry = {
        "run_at": run_time.isoformat(),
        "signal_date": debug["date"],
        "symbols": got,
        "balance_usdt": balance,
        "target_weights": debug["weights"],
        "composite": debug["composite"],
    }
    with open(REBALANCE_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    logger.info("rebalance 完成 ✓")
