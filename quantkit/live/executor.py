"""
Binance Futures 下单执行器

功能：
  - 查询账户余额 / 当前持仓
  - 限价单下单（Maker 费率），超时未成交则市价兜底
  - 设置杠杆
  - 风控检查（最大回撤停止）
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import time
from typing import Optional
from urllib.parse import urlencode

import aiohttp
import pandas as pd

from .config import (
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    BINANCE_TRADE_REST,
    BINANCE_TESTNET,
    LEVERAGE,
    LIMIT_ORDER_TIMEOUT,
    MAX_DRAWDOWN_HALT,
    MIN_ORDER_NOTIONAL,
)

logger = logging.getLogger("executor")


def _sign(params: dict) -> str:
    # sign
    query = urlencode(params)
    return hmac.new(
        BINANCE_API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()


def _ts() -> int:
    # ts
    return int(time.time() * 1000)


class BinanceFuturesExecutor:

    def __init__(self) -> None:
        # init
        self._headers = {
            "X-MBX-APIKEY": BINANCE_API_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        self._peak_balance: Optional[float] = None
        self._step_size_cache: dict[str, float] = {}
        self._tick_size_cache: dict[str, float] = {}
        self._position_mode_set = False
        logger.info(
            "executor 初始化完成（%s）",
            "TESTNET" if BINANCE_TESTNET else "MAINNET ⚠️",
        )

    async def ensure_one_way_mode(self) -> None:
        # 确保账户为单向持仓模式（非 Hedge Mode），避免 -4061 错误
        """确保账户为单向持仓模式（非 Hedge Mode），避免 -4061 错误"""
        if self._position_mode_set:
            return
        params = {"dualSidePosition": "false", "timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.post(
                f"{BINANCE_TRADE_REST}/fapi/v1/positionSide/dual",
                data=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                if resp.status == 200:
                    logger.info("已切换为单向持仓模式")
                elif result.get("code") == -4059:
                    # "No need to change position side." — 已经是单向模式
                    logger.debug("账户已是单向持仓模式")
                else:
                    logger.warning("切换持仓模式失败: %s", result)
        self._position_mode_set = True

    # ── 查询接口 ──────────────────────────────────────────────────────────────

    async def get_balance(self) -> float:
        # 返回 USDT 可用余额
        """返回 USDT 可用余额"""
        params = {"timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v2/balance",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        for item in data:
            if item["asset"] == "USDT":
                bal = float(item["balance"])
                logger.info("USDT 可用余额: %.2f", bal)
                return bal
        raise ValueError("账户中未找到 USDT 余额")

    async def get_positions(self) -> dict[str, float]:
        # 返回当前所有有持仓的合约：{BTCUSDT: position_amt}
        """
        返回当前所有有持仓的合约：{BTCUSDT: position_amt}
        正数 = long，负数 = short，0 = 无仓
        """
        params = {"timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v2/positionRisk",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        positions = {}
        for p in data:
            amt = float(p["positionAmt"])
            if amt != 0.0:
                positions[p["symbol"]] = amt
        logger.info("当前持仓: %s", positions)
        return positions

    async def get_price(self, symbol: str) -> float:
        # 获取最新标记价格（用于计算下单数量）
        """获取最新标记价格（用于计算下单数量）"""
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v1/premiumIndex",
                params={"symbol": symbol},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return float(data["markPrice"])

    async def get_book_ticker(self, symbol: str) -> tuple[float, float]:
        # 获取当前最优买卖价: (bestBid, bestAsk)
        """获取当前最优买卖价: (bestBid, bestAsk)"""
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v1/ticker/bookTicker",
                params={"symbol": symbol},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        return float(data["bidPrice"]), float(data["askPrice"])

    async def get_symbol_info(self, symbol: str) -> dict:
        # 获取合约最小下单精度
        """获取合约最小下单精度"""
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v1/exchangeInfo",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                info = await resp.json()

        for s in info["symbols"]:
            if s["symbol"] == symbol:
                return s
        raise ValueError(f"{symbol} 不在 exchangeInfo 中")

    async def _get_step_size(self, symbol: str) -> float:
        # 从 exchangeInfo LOT_SIZE filter 获取最小下单精度，结果缓存
        """从 exchangeInfo LOT_SIZE filter 获取最小下单精度，结果缓存"""
        if symbol in self._step_size_cache:
            return self._step_size_cache[symbol]
        info = await self.get_symbol_info(symbol)
        for f in info["filters"]:
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                self._step_size_cache[symbol] = step
            if f["filterType"] == "PRICE_FILTER":
                tick = float(f["tickSize"])
                self._tick_size_cache[symbol] = tick
        return self._step_size_cache[symbol]

    def _get_tick_size(self, symbol: str) -> float:
        # 返回价格精度（需先调用过 _get_step_size 缓存）
        """返回价格精度（需先调用过 _get_step_size 缓存）"""
        return self._tick_size_cache.get(symbol, 0.01)

    # ── 下单 ──────────────────────────────────────────────────────────────────

    async def set_leverage(self, symbol: str, leverage: int = LEVERAGE) -> None:
        # set leverage
        params = {"symbol": symbol, "leverage": leverage, "timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.post(
                f"{BINANCE_TRADE_REST}/fapi/v1/leverage",
                data=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
        logger.debug("设置 %s 杠杆 %dx", symbol, leverage)

    def _round_price(self, price: float, tick_size: float) -> float:
        # 按 tickSize 取整价格
        """按 tickSize 取整价格"""
        decimals = max(0, round(-math.log10(tick_size))) if tick_size < 1 else 0
        return round(math.floor(price / tick_size) * tick_size, decimals)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        step_size: float = 1.0,
        tick_size: float = 0.01,
    ) -> dict:
        """挂限价单（GTC），返回订单信息"""
        qty_decimals = max(0, round(-math.log10(step_size))) if step_size < 1 else 0
        price_decimals = max(0, round(-math.log10(tick_size))) if tick_size < 1 else 0
        params = {
            "symbol":      symbol,
            "side":        side,
            "type":        "LIMIT",
            "timeInForce": "GTC",
            "quantity":    f"{quantity:.{qty_decimals}f}",
            "price":       f"{price:.{price_decimals}f}",
            "timestamp":   _ts(),
        }
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.post(
                f"{BINANCE_TRADE_REST}/fapi/v1/order",
                data=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"限价单失败 {symbol}: {result}")

        logger.info(
            "限价单已挂 %s %s qty=%.6f price=%.4f  orderId=%s",
            symbol, side, quantity, price, result.get("orderId"),
        )
        return result

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        step_size: float = 1.0,
    ) -> dict:
        """市价单（仅作为限价单超时后的兜底）"""
        decimals = max(0, round(-math.log10(step_size))) if step_size < 1 else 0
        qty_str = f"{quantity:.{decimals}f}"
        params = {
            "symbol":    symbol,
            "side":      side,
            "type":      "MARKET",
            "quantity":  qty_str,
            "timestamp": _ts(),
        }
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.post(
                f"{BINANCE_TRADE_REST}/fapi/v1/order",
                data=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"市价兜底失败 {symbol}: {result}")

        logger.info(
            "市价兜底成功 %s %s %.6f  orderId=%s",
            symbol, side, quantity, result.get("orderId"),
        )
        return result

    async def get_order_status(self, symbol: str, order_id: int) -> dict:
        """查询订单状态"""
        params = {"symbol": symbol, "orderId": order_id, "timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.get(
                f"{BINANCE_TRADE_REST}/fapi/v1/order",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def cancel_order(self, symbol: str, order_id: int) -> dict:
        """撤单"""
        params = {"symbol": symbol, "orderId": order_id, "timestamp": _ts()}
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.delete(
                f"{BINANCE_TRADE_REST}/fapi/v1/order",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"撤单失败 {symbol}: {result}")
        logger.info("撤单成功 %s orderId=%s", symbol, order_id)
        return result

    async def place_limit_then_market(
        self,
        symbol: str,
        side: str,
        quantity: float,
        step_size: float,
    ) -> None:
        """
        核心下单逻辑：限价单挂盘口 → 等待成交 → 超时撤单 → 剩余市价兜底
        BUY 挂 bestBid，SELL 挂 bestAsk，做 Maker 省手续费
        """
        tick_size = self._get_tick_size(symbol)

        # 1. 获取盘口价
        bid, ask = await self.get_book_ticker(symbol)
        limit_price = bid if side == "BUY" else ask
        limit_price = self._round_price(limit_price, tick_size)

        # 2. 挂限价单
        try:
            result = await self.place_limit_order(
                symbol, side, quantity, limit_price, step_size, tick_size,
            )
        except Exception as e:
            logger.warning("限价单失败 %s，直接市价兜底: %s", symbol, e)
            await self.place_market_order(symbol, side, quantity, step_size)
            return

        order_id = result["orderId"]

        # 3. 轮询等待成交
        filled_qty = 0.0
        deadline = time.time() + LIMIT_ORDER_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(5)
            try:
                status = await self.get_order_status(symbol, order_id)
            except Exception:
                continue
            filled_qty = float(status.get("executedQty", 0))
            order_status = status.get("status", "")

            if order_status == "FILLED":
                logger.info("限价单全部成交 %s %s %.6f", symbol, side, quantity)
                return
            if order_status in ("CANCELED", "EXPIRED", "REJECTED"):
                break

        # 4. 超时 → 撤单
        try:
            await self.cancel_order(symbol, order_id)
        except Exception as e:
            # 可能刚好全部成交了，再查一次
            logger.warning("撤单异常 %s: %s，再查一次状态", symbol, e)
            try:
                final = await self.get_order_status(symbol, order_id)
                if final.get("status") == "FILLED":
                    logger.info("限价单实际已全部成交 %s", symbol)
                    return
                filled_qty = float(final.get("executedQty", 0))
            except Exception:
                pass

        # 5. 剩余部分用市价兜底
        remaining = self._round_qty(quantity - filled_qty, step_size)
        if remaining > 0:
            logger.info(
                "限价单部分成交 %s：已成交 %.6f，剩余 %.6f 市价兜底",
                symbol, filled_qty, remaining,
            )
            try:
                await self.place_market_order(symbol, side, remaining, step_size)
            except Exception as e:
                logger.error("市价兜底失败 %s: %s", symbol, e)
        else:
            logger.info("限价单已全部成交 %s（撤单前成交完毕）", symbol)

    async def close_position(self, symbol: str, current_amt: float) -> dict:
        """平掉某个仓位（reduceOnly）"""
        side = "SELL" if current_amt > 0 else "BUY"
        qty  = abs(current_amt)
        step_size = self._step_size_cache.get(symbol, 1.0)
        decimals = max(0, round(-math.log10(step_size))) if step_size < 1 else 0
        params = {
            "symbol":     symbol,
            "side":       side,
            "type":       "MARKET",
            "quantity":   f"{qty:.{decimals}f}",
            "reduceOnly": "true",
            "timestamp":  _ts(),
        }
        params["signature"] = _sign(params)

        async with aiohttp.ClientSession(headers=self._headers) as s:
            async with s.post(
                f"{BINANCE_TRADE_REST}/fapi/v1/order",
                data=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                result = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(f"平仓失败 {symbol}: {result}")

        logger.info("平仓成功 %s  %.6f", symbol, qty)
        return result

    # ── 调仓主逻辑 ─────────────────────────────────────────────────────────────

    async def rebalance(
        self,
        target_weights: pd.Series,   # {symbol: weight}，正 = long，负 = short
        balance_usdt: float,
    ) -> None:
        """
        根据目标权重 rebalance 全部合约仓位。
        1. 查询当前价格和仓位
        2. 计算目标持仓金额 = weight × balance
        3. 计算 delta（目标 - 当前），过滤小 delta
        4. 先平/减仓，再开/增仓（避免保证金不足）
        5. 使用限价单挂盘口，超时后市价兜底
        """
        # ── 确保单向持仓模式 ───────────────────────────────────────────────
        await self.ensure_one_way_mode()

        # ── 风控：最大回撤检查 ────────────────────────────────────────────────
        if self._peak_balance is None:
            self._peak_balance = balance_usdt
        else:
            self._peak_balance = max(self._peak_balance, balance_usdt)

        drawdown = (balance_usdt - self._peak_balance) / self._peak_balance
        if drawdown < MAX_DRAWDOWN_HALT:
            logger.error(
                "账户回撤 %.1f%% 超过阈值 %.1f%%，停止交易！",
                drawdown * 100, MAX_DRAWDOWN_HALT * 100,
            )
            return

        # 只用 90% 余额下单，预留 10% 作为手续费和保证金缓冲
        balance_usdt = balance_usdt * 0.9

        # ── 查询当前仓位 ──────────────────────────────────────────────────────
        current_positions = await self.get_positions()

        all_symbols = set(target_weights.index.tolist()) | set(current_positions.keys())

        # ── 计算每个币的 delta（以 USDT 计价）────────────────────────────────
        deltas: list[tuple[str, float, float, float]] = []

        for symbol in all_symbols:
            price = await self.get_price(symbol)
            step_size = await self._get_step_size(symbol)
            target_w = float(target_weights.get(symbol, 0.0))
            target_usdt = target_w * balance_usdt

            current_amt  = current_positions.get(symbol, 0.0)
            current_usdt = current_amt * price

            delta_usdt = target_usdt - current_usdt
            deltas.append((symbol, delta_usdt, price, step_size))

        # ── 设置杠杆（初始化一次） ─────────────────────────────────────────────
        for symbol in all_symbols:
            try:
                await self.set_leverage(symbol, LEVERAGE)
            except Exception as e:
                logger.warning("设置 %s 杠杆失败（可能已设置）: %s", symbol, e)

        # ── 按仓位绝对值变化分批：减仓/平仓 先执行（释放保证金），再开仓/加仓 ──
        reduce_orders = []
        add_orders    = []
        for s, d, p, ss in deltas:
            current_amt = current_positions.get(s, 0.0)
            target_amt  = current_amt + d / p   # 目标持仓量
            if abs(target_amt) < abs(current_amt):
                reduce_orders.append((s, d, p, ss))
            else:
                add_orders.append((s, d, p, ss))

        # ── 第 1 批：减仓/平仓 — 市价单，快速释放保证金 ──────────────────────
        reduce_tasks = []
        for symbol, delta_usdt, price, step_size in reduce_orders:
            if abs(delta_usdt) < MIN_ORDER_NOTIONAL:
                logger.debug("跳过 %s delta=%.2f USDT（低于最小下单额）", symbol, delta_usdt)
                continue
            qty = self._round_qty(abs(delta_usdt) / price, step_size)
            if qty == 0:
                continue
            side = "BUY" if delta_usdt > 0 else "SELL"
            reduce_tasks.append(self.place_market_order(symbol, side, qty, step_size))

        if reduce_tasks:
            results = await asyncio.gather(*reduce_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("减仓异常: %s", r)

        # ── 第 2 批：开仓/加仓 — 限价单挂盘口，超时市价兜底 ──────────────────
        add_tasks = []
        for symbol, delta_usdt, price, step_size in add_orders:
            if abs(delta_usdt) < MIN_ORDER_NOTIONAL:
                logger.debug("跳过 %s delta=%.2f USDT（低于最小下单额）", symbol, delta_usdt)
                continue
            qty = self._round_qty(abs(delta_usdt) / price, step_size)
            if qty == 0:
                continue
            side = "BUY" if delta_usdt > 0 else "SELL"
            add_tasks.append(self.place_limit_then_market(symbol, side, qty, step_size))

        if add_tasks:
            results = await asyncio.gather(*add_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.error("调仓异常: %s", r)

    def _round_qty(self, qty: float, step_size: float) -> float:
        """按 stepSize 向下取整，确保不超过 Binance 精度要求"""
        return math.floor(qty / step_size) * step_size
