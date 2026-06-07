"""实盘入口：加载策略 -> 起调度器 -> 每日 00:05 UTC 触发 rebalance。

运行：
    python -m quantkit.live.main --strategy strategy.json
    python -m quantkit.live.main --strategy strategy.json --once   # 立即跑一次后退出

强烈建议先在 BINANCE_TESTNET=true 下验证。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal as os_signal
import sys
from logging.handlers import TimedRotatingFileHandler

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..data.gateway_client import GatewayClient
from . import config
from .config import StrategyConfig
from .executor import BinanceFuturesExecutor
from .rebalancer import run_daily_rebalance


def setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    fh = TimedRotatingFileHandler(config.LOG_DIR / "live.log", when="midnight", utc=True, backupCount=30)
    fh.setFormatter(fmt)
    root.addHandler(fh)


logger = logging.getLogger("main")


def preflight(strategy: StrategyConfig) -> None:
    errors = []
    if not config.BINANCE_API_KEY or not config.BINANCE_API_SECRET:
        errors.append("BINANCE_API_KEY / BINANCE_API_SECRET 未配置")
    if not strategy.factors:
        errors.append("strategy.json 没有 factors")
    if errors:
        for e in errors:
            logger.error("预检失败: %s", e)
        sys.exit(1)
    logger.info("预检通过 ✓（%s 模式）", "TESTNET" if config.BINANCE_TESTNET else "MAINNET ⚠️")


async def _run_once(strategy, executor, gateway) -> None:
    try:
        await run_daily_rebalance(strategy, executor, gateway)
    except Exception as e:
        logger.error("rebalance 未捕获异常: %s", e, exc_info=True)


async def main_async(strategy_path: str, once: bool) -> None:
    setup_logging()
    logger.info("quantkit live 启动")
    strategy = StrategyConfig.load(strategy_path)
    preflight(strategy)

    executor = BinanceFuturesExecutor()
    gateway = GatewayClient(config.GATEWAY_TARGET, gateway_dir=config.EXCHANGE_GATEWAY_DIR)

    if once:
        await _run_once(strategy, executor, gateway)
        return

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _run_once,
        trigger=CronTrigger(hour=config.REBALANCE_HOUR_UTC, minute=config.REBALANCE_MINUTE_UTC, timezone="UTC"),
        args=[strategy, executor, gateway],
        id="daily_rebalance", max_instances=1, misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("调度器已启动，每日 %02d:%02d UTC 调仓",
                config.REBALANCE_HOUR_UTC, config.REBALANCE_MINUTE_UTC)

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.shutdown(wait=False)
    logger.info("已退出")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="quantkit 币安实盘日度调仓")
    ap.add_argument("--strategy", required=True, help="strategy.json 路径")
    ap.add_argument("--once", action="store_true", help="立即跑一次后退出")
    args = ap.parse_args(argv)
    asyncio.run(main_async(args.strategy, args.once))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
