"""exchange-gateway 数据服务封装（取数依赖已内置，不再依赖外部仓库）。

参考客户端与 proto 已 vendor 进 ``quantkit/data/_gateway``（见该子包 docstring），
因此本包**不再需要** ``EXCHANGE_GATEWAY_DIR`` 指向 exchange-gateway 仓库。
唯一的本机前置是装了 ``grpcurl``（vendored client 走 grpcurl backend）。

数据路径（与 exchange-gateway 8778 / 8777 对齐）：
* 1d K 线 + readiness —— 新 aggtrade-kline-gateway（**8778**，``AggTradeKlineGatewayService``）
  的 ``GetHistoricalKlines`` / ``GetHistoricalKlineReadiness``。aggTrade 合成 K 线，
  只支持 1h/1d，**最多 300 根**。
* OI / premium / 大户多空比 历史 —— market_features（**8778** ``GetHistoricalFeatureBars``，
  unary 历史，dataset=``market_features``、interval=``1d``）。
* funding 历史 —— 旧 market gateway（**8777**，``MarketDataService`` 的
  ``GetHistoricalFundingRates``；8778 不提供 funding）。

我们只用 **1d**（``interval_seconds=86400`` / ``interval="1d"``），``limit`` 最多 300。
失败关闭语义：返回里带 ``statuses[]``（有缺口/不足）就视为该 symbol 不可用。

字段覆盖（见 quant-package.md §2.4）：
* K 线类字段 —— ``GetHistoricalKlines`` 返回 ``marketdata.v1.Bar``，字段与 8777 一致：
  close/volume/taker_buy_volume/taker_sell_volume/taker_buy_quote_volume(=taker_buy_amount)/
  taker_sell_quote_volume/taker_buy_trades/taker_sell_trades 等。
* funding 历史 —— ``GetHistoricalFundingRates``。
* OI/premium/大户多空比 历史 —— ``GetHistoricalFeatureBars``（market_features 1d）。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from ._gateway import ref_client as ref

DAY_SECONDS = 86400          # 1d K 线 readiness / klines 用秒
DAY_INTERVAL = "1d"          # feature 历史的 interval 是字符串
FEATURE_DATASET = "market_features"
MAX_KLINE_LIMIT = 300        # 8778 aggtrade-kline-gateway 上限，只支持 1h/1d × ≤300 根

DEFAULT_KLINE_TARGET = "13.231.65.185:8778"     # aggtrade-kline-gateway：klines + features
DEFAULT_FUNDING_TARGET = "13.231.65.185:8777"   # legacy market gateway：funding

# GetHistoricalKlines 返回的 Bar 字段 -> plugin 入参名（market_features 列名）。
# ref client 的 bar_record 把 quote volume 叫 *_amount，这里映射回 *_quote_volume。
_BAR_FIELD_ALIASES = {
    "taker_buy_amount": "taker_buy_quote_volume",
    "taker_sell_amount": "taker_sell_quote_volume",
    # 整根 bar 的成交额：ref client 叫 amount，plugin 入参名是 quote_volume。
    "amount": "quote_volume",
    "trade_count": "trades",
}


class GatewayClient:
    """1d 行情取数客户端（klines/features 走 8778，funding 走 8777）。"""

    def __init__(
        self,
        kline_target: str = DEFAULT_KLINE_TARGET,
        funding_target: str = DEFAULT_FUNDING_TARGET,
        *,
        exchange: str = "binance",
    ) -> None:
        # init：两个底层 ref client，因为 funding 仍只在 8777，klines/features 在 8778。
        self.exchange = exchange
        self._ref = ref  # 模块级 helper：bar_record / feature_bar_record
        # 强制 grpcurl backend：外部用户只需装 grpcurl，无需 grpcio/grpcio-tools。
        self._kline = ref.ExchangeGatewayRefClient(kline_target, backend="grpcurl")
        self._funding = ref.ExchangeGatewayRefClient(funding_target, backend="grpcurl")

    # ── readiness 健康检查（8778 GetHistoricalKlineReadiness）────────────────────
    def is_ready(self, symbols: list[str], limit: int = MAX_KLINE_LIMIT) -> dict[str, bool]:
        # 逐 symbol 查 1d aggTrade K 线 readiness，返回 {symbol: ready}。
        """逐 symbol 查 1d readiness，返回 {symbol: ready}。"""
        limit = min(limit, MAX_KLINE_LIMIT)
        resp = self._kline.get_historical_aggtrade_kline_readiness(
            self.exchange, symbols, [DAY_SECONDS], limit
        )
        out: dict[str, bool] = {}
        # 兼容 JSONL / dict 两种返回风格（GetHistoricalKlineReadinessResponse.rows）
        rows = resp if isinstance(resp, list) else resp.get("rows", resp.get("readiness", []))
        for row in rows or []:
            sym = row.get("symbol", "")
            if sym:
                out[sym] = bool(row.get("ready", False))
        return out

    # ── 历史 1d K 线（8778 GetHistoricalKlines）──────────────────────────────────
    def fetch_bars(self, symbol: str, limit: int = MAX_KLINE_LIMIT) -> pd.DataFrame | None:
        # 取单个 symbol 最近 ``limit`` 根已闭合 1d aggTrade K 线（≤300）。
        """取单个 symbol 最近 ``limit`` 根已闭合 1d bars。

        失败关闭：有 ``statuses[]`` 或无 bars 时返回 None。
        Returns: DataFrame，index 为 UTC datetime，列为标准化后的字段名。
        """
        limit = min(limit, MAX_KLINE_LIMIT)
        resp = self._kline.get_historical_aggtrade_klines(
            self.exchange, symbol, DAY_SECONDS, limit, include_bar_envelope=False
        )
        if resp.get("statuses"):
            return None
        bars = resp.get("bars") or []
        if not bars:
            return None

        records: list[dict[str, Any]] = []
        for bar in bars:
            row = self._ref.bar_record({"bar": bar})
            if row is None:
                continue
            rec = {"open_time": pd.to_datetime(int(row["open_time_ms"]), unit="ms", utc=True)}
            for k, v in row.items():
                if k in ("open_time_ms", "timestamp", "symbol", "exchange",
                         "interval_seconds", "subject", "data_quality"):
                    continue
                name = _BAR_FIELD_ALIASES.get(k, k)
                rec[name] = _to_float(v)
            records.append(rec)

        df = pd.DataFrame(records).set_index("open_time").sort_index()
        return df

    def fetch_bars_panel(self, symbols: list[str], limit: int = MAX_KLINE_LIMIT) -> dict[str, pd.DataFrame]:
        # 批量取多个 symbol 的 1d bars，返回 {symbol: DataFrame}。取不到的跳过。
        """批量取多个 symbol 的 1d bars，返回 {symbol: DataFrame}。取不到的跳过。"""
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.fetch_bars(sym, limit)
            if df is not None and not df.empty:
                out[sym] = df
        return out

    # ── 历史 feature（8778 GetHistoricalFeatureBars：OI/premium/大户多空比）───────
    def fetch_features(self, symbol: str, limit: int = MAX_KLINE_LIMIT) -> pd.DataFrame | None:
        # 取单个 symbol 的 1d market_features 历史，返回 [date x feature列] DataFrame。
        """取单个 symbol 的 1d ``market_features`` 历史。

        失败关闭：有 ``statuses[]`` 或无 feature bar 时返回 None。缺失列（``missing_mask``）
        按 NaN 处理，**不会**把缺失当真值。
        Returns: DataFrame，index 为 UTC datetime，列为 feature 名（与 build_signal 入参对齐）。
        """
        limit = min(limit, MAX_KLINE_LIMIT)
        resp = self._kline.get_historical_aggtrade_feature_bars(
            self.exchange, symbol, FEATURE_DATASET, DAY_INTERVAL, limit
        )
        if resp.get("statuses"):
            return None
        fbars = resp.get("featureBars") or resp.get("feature_bars") or []
        if not fbars:
            return None

        records: list[dict[str, Any]] = []
        for fb in fbars:
            row = self._ref.feature_bar_record(fb)
            rec: dict[str, Any] = {
                "open_time": pd.to_datetime(int(row["open_time_ms"]), unit="ms", utc=True)
            }
            # feature_bar_record 已把缺失列置 None；_to_float(None) -> NaN。
            for col, val in (row.get("values") or {}).items():
                rec[col] = _to_float(val)
            records.append(rec)

        if not records:
            return None
        df = pd.DataFrame(records).set_index("open_time").sort_index()
        return df

    def fetch_features_panel(self, symbols: list[str], limit: int = MAX_KLINE_LIMIT) -> dict[str, pd.DataFrame]:
        # 批量取多个 symbol 的 1d market_features，返回 {symbol: DataFrame}。取不到的跳过。
        """批量取多个 symbol 的 1d market_features，返回 {symbol: DataFrame}。取不到的跳过。"""
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.fetch_features(sym, limit)
            if df is not None and not df.empty:
                out[sym] = df
        return out

    # ── 历史 funding（8777 GetHistoricalFundingRates）────────────────────────────
    def fetch_funding(self, symbol: str, limit: int = 1000) -> pd.Series | None:
        # 取单个 symbol 的历史 funding rate，返回 Series（index=UTC datetime）。
        """取单个 symbol 的历史 funding rate，返回 Series（index=UTC datetime）。

        funding 仍走 8777 market gateway（8778 无 funding 接口），不受 300 根上限约束。
        """
        resp = self._funding.get_historical_funding_rates(self.exchange, symbol, limit)
        rates = resp.get("rates") or resp.get("fundingRates") or []
        if not rates:
            return None
        idx, vals = [], []
        for r in rates:
            ts = int(r.get("fundingTimeMs", 0))
            idx.append(pd.to_datetime(ts, unit="ms", utc=True))
            vals.append(_to_float(r.get("fundingRate")))
        return pd.Series(vals, index=pd.DatetimeIndex(idx)).sort_index()


def _to_float(v: Any) -> float:
    # to float
    if v is None or v == "":
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")
