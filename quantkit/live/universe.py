"""实盘 universe 解析。

两种模式（strategy.json 的 ``universe`` 字段）：
* ``{"mode": "manual", "symbols": ["BTCUSDT", ...]}``  —— 直接用给定列表
* ``{"mode": "cmc_top_n", "n": 10}``                   —— CoinMarketCap 市值 Top N
                                                           （非稳定币，且币安 Futures 上有该合约）

CMC 模式需要 ``CMC_API_KEY``，且会用数据服务的 exchange_info 校验合约可交易。
"""
from __future__ import annotations

import logging

import aiohttp

from . import config

logger = logging.getLogger("universe")


async def resolve_universe(spec: dict) -> list[str]:
    # resolve universe
    mode = spec.get("mode", "cmc_top_n")
    if mode == "manual":
        symbols = [s.upper() for s in spec["symbols"]]
        logger.info("manual universe: %s", symbols)
        return symbols
    if mode == "cmc_top_n":
        return await _cmc_top_n(int(spec.get("n", config.CMC_TOP_N)))
    raise ValueError(f"未知 universe.mode: {mode}")


async def _cmc_top_n(top_n: int) -> list[str]:
    # cmc top n
    if not config.CMC_API_KEY:
        raise RuntimeError("universe.mode=cmc_top_n 需要 CMC_API_KEY")

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    params = {"start": 1, "limit": top_n * 4, "sort": "market_cap",
              "cryptocurrency_type": "coins", "convert": "USD"}
    headers = {"X-CMC_PRO_API_KEY": config.CMC_API_KEY}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()

    candidates: list[str] = []
    for coin in data["data"]:
        sym = coin["symbol"].upper()
        if sym not in config.STABLECOINS:
            candidates.append(sym + "USDT")
        if len(candidates) >= top_n * 2:
            break

    active = await _binance_active_symbols()
    result = [s for s in candidates if s in active][:top_n]
    if len(result) < top_n:
        logger.warning("只找到 %d 个有效合约（要求 %d）", len(result), top_n)
    logger.info("cmc_top_n universe: %s", result)
    return result


async def _binance_active_symbols() -> set[str]:
    # 从币安 Futures exchangeInfo 拿正在交易的 USDT 合约集合（行情用 mainnet）。
    """从币安 Futures exchangeInfo 拿正在交易的 USDT 合约集合（行情用 mainnet）。"""
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            info = await resp.json()
    return {
        s["symbol"] for s in info["symbols"]
        if s["status"] == "TRADING" and s["quoteAsset"] == "USDT"
    }
