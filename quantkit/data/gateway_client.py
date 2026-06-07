"""exchange-gateway 数据服务封装。

设计原则：**不重造 gRPC 管道**。exchange-gateway 仓库里已经有官方参考客户端
``examples/marketdata-fetch-client/exchange_gateway_ref_client.py``（内部 shell 调
``grpcurl`` + proto）。这里把它 import 进来，包一层 pandas 友好的接口。

依赖：
* 本机装了 ``grpcurl``
* 能访问到 exchange-gateway 仓库（含 proto）。路径用环境变量
  ``EXCHANGE_GATEWAY_DIR`` 覆盖，默认 ``/home/ec2-user/exchange-gateway``。

我们只用 **1d**（``interval_seconds=86400``）日线，``limit`` 最多 1000。
失败关闭语义：返回里带 ``statuses[]``（有缺口/不足）就视为该 symbol 不可用。

字段覆盖（见 quant-package.md §2.4）：
* K 线类字段 —— ``GetHistoricalBars`` 直接给：close/volume/taker_buy_volume/
  taker_sell_volume/taker_buy_quote_volume(=taker_buy_amount)/taker_sell_quote_volume/
  taker_buy_trades/taker_sell_trades 等。
* funding 历史 —— ``GetHistoricalFundingRates``。
* OI/premium/大户多空比历史 —— market_features 1d（streaming），见 panels 文档。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

DAY_SECONDS = 86400
DEFAULT_TARGET = "13.231.65.185:8777"
DEFAULT_GATEWAY_DIR = os.environ.get("EXCHANGE_GATEWAY_DIR", "/home/ec2-user/exchange-gateway")

# GetHistoricalBars 返回的字段 -> plugin 入参名（market_features 列名）。
# ref client 的 bar_record 把 quote volume 叫 *_amount，这里映射回 *_quote_volume。
_BAR_FIELD_ALIASES = {
    "taker_buy_amount": "taker_buy_quote_volume",
    "taker_sell_amount": "taker_sell_quote_volume",
}


def _load_ref_client(gateway_dir: str | Path):
    # 把 exchange-gateway 的 ref client import 进来。
    """把 exchange-gateway 的 ref client import 进来。"""
    gateway_dir = Path(gateway_dir).expanduser().resolve()
    client_dir = gateway_dir / "examples" / "marketdata-fetch-client"
    if not client_dir.is_dir():
        raise FileNotFoundError(
            f"找不到 exchange-gateway ref client: {client_dir}\n"
            f"设置环境变量 EXCHANGE_GATEWAY_DIR 指向 exchange-gateway 仓库根目录。"
        )
    if str(client_dir) not in sys.path:
        sys.path.insert(0, str(client_dir))
    import exchange_gateway_ref_client as ref  # type: ignore

    return ref


class GatewayClient:
    """1d 行情取数客户端。"""

    def __init__(
        self,
        target: str = DEFAULT_TARGET,
        *,
        exchange: str = "binance",
        gateway_dir: str | Path = DEFAULT_GATEWAY_DIR,
    ) -> None:
        self.target = target
        self.exchange = exchange
        self._ref = _load_ref_client(gateway_dir)
        self._client = self._ref.ExchangeGatewayRefClient(target)

    # ── readiness 健康检查 ───────────────────────────────────────────────────
    def is_ready(self, symbols: list[str], limit: int = 1000) -> dict[str, bool]:
        """逐 symbol 查 1d readiness，返回 {symbol: ready}。"""
        resp = self._client.get_historical_bars_readiness(
            self.exchange, symbols, [DAY_SECONDS], limit
        )
        out: dict[str, bool] = {}
        # 兼容 JSONL / dict 两种返回风格
        rows = resp if isinstance(resp, list) else resp.get("readiness", resp.get("rows", []))
        for row in rows or []:
            sym = row.get("symbol", "")
            if sym:
                out[sym] = bool(row.get("ready", False))
        return out

    # ── 历史 1d K 线 ─────────────────────────────────────────────────────────
    def fetch_bars(self, symbol: str, limit: int = 1000) -> pd.DataFrame | None:
        """取单个 symbol 最近 ``limit`` 根已闭合 1d bars。

        失败关闭：有 ``statuses[]`` 或无 bars 时返回 None。
        Returns: DataFrame，index 为 UTC datetime，列为标准化后的字段名。
        """
        resp = self._client.get_historical_bars(
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

    def fetch_bars_panel(self, symbols: list[str], limit: int = 1000) -> dict[str, pd.DataFrame]:
        """批量取多个 symbol 的 1d bars，返回 {symbol: DataFrame}。取不到的跳过。"""
        out: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self.fetch_bars(sym, limit)
            if df is not None and not df.empty:
                out[sym] = df
        return out

    # ── 历史 funding ─────────────────────────────────────────────────────────
    def fetch_funding(self, symbol: str, limit: int = 1000) -> pd.Series | None:
        """取单个 symbol 的历史 funding rate，返回 Series（index=UTC datetime）。"""
        resp = self._client.get_historical_funding_rates(self.exchange, symbol, limit)
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
    if v is None or v == "":
        return float("nan")
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")
