#!/usr/bin/env python3
from __future__ import annotations

import csv
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


MARKETDATA_SERVICE = "exchange_gateway.marketdata.v1.MarketDataService"
AGGTRADE_KLINE_SERVICE = "exchange_gateway.aggtrade_kline.v1.AggTradeKlineGatewayService"
SUBSCRIBE_BARS_METHOD = f"{MARKETDATA_SERVICE}/SubscribeBars"
SUBSCRIBE_MARKET_DATA_SLICES_METHOD = f"{MARKETDATA_SERVICE}/SubscribeMarketDataSlices"
SUBSCRIBE_AGGTRADE_KLINE_SLICES_METHOD = f"{AGGTRADE_KLINE_SERVICE}/SubscribeKlineSlices"
GET_LATEST_MARKET_DATA_METHOD = f"{MARKETDATA_SERVICE}/GetLatestMarketData"
GET_HISTORICAL_BARS_METHOD = f"{MARKETDATA_SERVICE}/GetHistoricalBars"
GET_HISTORICAL_BARS_READINESS_METHOD = f"{MARKETDATA_SERVICE}/GetHistoricalBarsReadiness"
GET_HISTORICAL_AGGTRADE_BARS_METHOD = f"{MARKETDATA_SERVICE}/GetHistoricalAggTradeBars"
GET_HISTORICAL_AGGTRADE_BARS_READINESS_METHOD = f"{MARKETDATA_SERVICE}/GetHistoricalAggTradeBarsReadiness"
GET_HISTORICAL_AGGTRADE_KLINES_METHOD = f"{AGGTRADE_KLINE_SERVICE}/GetHistoricalKlines"
GET_HISTORICAL_AGGTRADE_KLINE_READINESS_METHOD = f"{AGGTRADE_KLINE_SERVICE}/GetHistoricalKlineReadiness"
GET_HISTORICAL_AGGTRADE_FEATURE_BARS_METHOD = f"{AGGTRADE_KLINE_SERVICE}/GetHistoricalFeatureBars"
GET_HISTORICAL_AGGTRADE_FEATURE_READINESS_METHOD = f"{AGGTRADE_KLINE_SERVICE}/GetHistoricalFeatureReadiness"
GET_HISTORICAL_AGGTRADE_KLINE_SLICES_METHOD = f"{AGGTRADE_KLINE_SERVICE}/GetHistoricalKlineSlices"
GET_HISTORICAL_FUNDING_METHOD = f"{MARKETDATA_SERVICE}/GetHistoricalFundingRates"
GET_EXCHANGE_INFO_METHOD = f"{MARKETDATA_SERVICE}/GetExchangeInfo"
GET_CURRENT_FUNDING_METHOD = f"{MARKETDATA_SERVICE}/GetCurrentFundingRates"
GET_SETTLEMENT_FUNDING_METHOD = f"{MARKETDATA_SERVICE}/GetSettlementFundingRatesAt"
EXACT_ZERO_FILL = "FUNDING_RATE_FILL_POLICY_EXACT_ZERO_FILL"

DEFAULT_PROTO = "proto/marketdata/v1/marketdata.proto"
AGGTRADE_KLINE_PROTO = "proto/aggtrade_kline/v1/aggtrade_kline.proto"
UINT64 = 1 << 64


def find_proto_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / DEFAULT_PROTO).is_file():
            return candidate
    return start.parents[1]


REPO_ROOT = find_proto_root()

OHLCV_FIELDS = [
    "timestamp",
    "open_time_ms",
    "exchange",
    "symbol",
    "interval_seconds",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "trade_count",
    "taker_buy_volume",
    "taker_buy_amount",
    "taker_buy_trades",
    "taker_sell_volume",
    "taker_sell_amount",
    "taker_sell_trades",
    "data_quality",
    "subject",
    "stream_sequence",
    "worker_id",
    "assignment_generation",
    "config_version",
    "published_at_ms",
]

CURRENT_FUNDING_FIELDS = [
    "event_time",
    "event_time_ms",
    "exchange",
    "symbol",
    "contract_type",
    "funding_rate",
    "mark_price",
    "index_price",
    "estimated_settle_price",
    "next_funding_time",
    "next_funding_time_ms",
    "source",
    "quality",
    "producer_id",
    "producer_epoch",
    "published_at_ms",
    "sequence_in_epoch",
]

SETTLEMENT_FUNDING_FIELDS = [
    "timestamp",
    "timestamp_ms",
    "exchange",
    "symbol",
    "contract_type",
    "funding_rate",
    "matched_settlement_event",
    "settlement_source",
    "settlement_quality",
    "settlement_mark_price",
    "observed_event_time_ms",
    "confirmed_at_ms",
    "published_at_ms",
    "producer_id",
    "producer_epoch",
    "sequence_in_epoch",
]

HISTORICAL_FUNDING_FIELDS = [
    "timestamp",
    "funding_time_ms",
    "exchange",
    "symbol",
    "contract_type",
    "funding_rate",
    "source",
    "quality",
    "mark_price",
    "observed_event_time_ms",
    "confirmed_at_ms",
    "published_at_ms",
    "producer_id",
    "producer_epoch",
    "sequence_in_epoch",
    "window_source",
    "cache_fully_warmed",
    "requested_limit",
    "returned_count",
    "oldest_funding_time_ms",
    "newest_funding_time_ms",
]

EXCHANGE_INFO_FIELDS = [
    "exchange",
    "symbol",
    "pair",
    "contract_type",
    "status",
    "quote_asset",
    "margin_asset",
    "onboard_time_ms",
    "listing_time",
    "cached_at_ms",
    "next_refresh_after_ms",
    "source",
]


class GrpcurlError(RuntimeError):
    pass


class NativeGrpcUnavailable(RuntimeError):
    pass


def parse_symbols(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        out.extend(part.strip().upper() for part in value.split(",") if part.strip())
    return sorted(set(out))


def chunked(values: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(values), size):
        yield values[i : i + size]


def utc_iso(ms: int | str | None) -> str:
    value = int(ms or 0)
    if value <= 0:
        return ""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def decimal_value(value: dict[str, Any] | None) -> Decimal:
    if not value:
        return Decimal(0)
    hi = int(value.get("hi", 0))
    lo = int(value.get("lo", 0))
    scale = int(value.get("scale", 0))
    signed = hi * UINT64 + lo
    return Decimal(signed).scaleb(-scale)


def decimal_str(value: dict[str, Any] | None) -> str:
    out = decimal_value(value)
    if out == 0:
        return "0"
    return format(out.normalize(), "f")


def decimal_sum_str(*values: dict[str, Any] | None) -> str:
    out = sum((decimal_value(value) for value in values), Decimal(0))
    if out == 0:
        return "0"
    return format(out.normalize(), "f")


def iter_json_objects(text: Iterable[str]) -> Iterator[dict[str, Any]]:
    buffer: list[str] = []
    depth = 0
    in_string = False
    escaped = False
    started = False

    for chunk in text:
        for char in chunk:
            if not started:
                if char.isspace():
                    continue
                if char != "{":
                    continue
                started = True

            buffer.append(char)

            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield json.loads("".join(buffer))
                    buffer.clear()
                    started = False


_NATIVE_GRPC_LOCK = threading.Lock()
_NATIVE_GRPC_MODULES: dict[str, Any] | None = None


def _native_grpc_cache_dir() -> Path:
    configured = os.environ.get("EXCHANGE_GATEWAY_FETCH_CLIENT_GRPC_CACHE")
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "exchange_gateway_fetch_client_grpc_py"


def _load_native_grpc_modules() -> dict[str, Any]:
    global _NATIVE_GRPC_MODULES
    with _NATIVE_GRPC_LOCK:
        if _NATIVE_GRPC_MODULES is not None:
            return _NATIVE_GRPC_MODULES

        try:
            import grpc  # type: ignore[import-not-found]
            from google.protobuf.json_format import MessageToDict, ParseDict  # type: ignore[import-not-found]
            from grpc_tools import protoc  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise NativeGrpcUnavailable(
                "native gRPC backend requires Python packages grpcio, grpcio-tools and protobuf; "
                "install them or use --backend grpcurl"
            ) from exc

        cache_dir = _native_grpc_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        proto_files = [
            REPO_ROOT / "proto/common/v1/decimal.proto",
            REPO_ROOT / "proto/marketdata/v1/marketdata.proto",
        ]
        generated = cache_dir / "proto/marketdata/v1/marketdata_pb2_grpc.py"
        newest_proto_mtime = max(path.stat().st_mtime for path in proto_files)
        if not generated.is_file() or generated.stat().st_mtime < newest_proto_mtime:
            args = [
                "grpc_tools.protoc",
                f"-I{REPO_ROOT}",
                f"--python_out={cache_dir}",
                f"--grpc_python_out={cache_dir}",
                *(str(path) for path in proto_files),
            ]
            rc = protoc.main(args)
            if rc != 0:
                raise NativeGrpcUnavailable(f"failed to generate Python gRPC stubs, protoc exit code={rc}")
        for package_dir in [
            cache_dir / "proto",
            cache_dir / "proto/common",
            cache_dir / "proto/common/v1",
            cache_dir / "proto/marketdata",
            cache_dir / "proto/marketdata/v1",
        ]:
            (package_dir / "__init__.py").touch()

        if str(cache_dir) not in sys.path:
            sys.path.insert(0, str(cache_dir))
        marketdata_pb2 = importlib.import_module("proto.marketdata.v1.marketdata_pb2")
        marketdata_pb2_grpc = importlib.import_module("proto.marketdata.v1.marketdata_pb2_grpc")
        _NATIVE_GRPC_MODULES = {
            "grpc": grpc,
            "MessageToDict": MessageToDict,
            "ParseDict": ParseDict,
            "marketdata_pb2": marketdata_pb2,
            "marketdata_pb2_grpc": marketdata_pb2_grpc,
        }
        return _NATIVE_GRPC_MODULES


class NativeGrpcUnaryClient:
    def __init__(self, target: str) -> None:
        modules = _load_native_grpc_modules()
        grpc = modules["grpc"]
        marketdata_pb2_grpc = modules["marketdata_pb2_grpc"]
        self._modules = modules
        self._channel = grpc.insecure_channel(
            target,
            options=[
                ("grpc.max_receive_message_length", 128 * 1024 * 1024),
                ("grpc.max_send_message_length", 128 * 1024 * 1024),
            ],
        )
        self._stub = marketdata_pb2_grpc.MarketDataServiceStub(self._channel)

    def close(self) -> None:
        self._channel.close()

    def unary(self, method: str, payload: dict[str, Any], *, max_time: float = 30) -> dict[str, Any]:
        marketdata_pb2 = self._modules["marketdata_pb2"]
        parse_dict = self._modules["ParseDict"]
        message_to_dict = self._modules["MessageToDict"]
        request_types: dict[str, Any] = {
            GET_LATEST_MARKET_DATA_METHOD: marketdata_pb2.GetLatestMarketDataRequest,
            GET_HISTORICAL_BARS_METHOD: marketdata_pb2.GetHistoricalBarsRequest,
            GET_HISTORICAL_BARS_READINESS_METHOD: marketdata_pb2.GetHistoricalBarsReadinessRequest,
            GET_HISTORICAL_AGGTRADE_BARS_METHOD: marketdata_pb2.GetHistoricalBarsRequest,
            GET_HISTORICAL_AGGTRADE_BARS_READINESS_METHOD: marketdata_pb2.GetHistoricalBarsReadinessRequest,
            GET_HISTORICAL_FUNDING_METHOD: marketdata_pb2.GetHistoricalFundingRatesRequest,
            GET_EXCHANGE_INFO_METHOD: marketdata_pb2.GetExchangeInfoRequest,
            GET_CURRENT_FUNDING_METHOD: marketdata_pb2.GetCurrentFundingRatesRequest,
            GET_SETTLEMENT_FUNDING_METHOD: marketdata_pb2.GetSettlementFundingRatesAtRequest,
        }
        rpc_names: dict[str, str] = {
            GET_LATEST_MARKET_DATA_METHOD: "GetLatestMarketData",
            GET_HISTORICAL_BARS_METHOD: "GetHistoricalBars",
            GET_HISTORICAL_BARS_READINESS_METHOD: "GetHistoricalBarsReadiness",
            GET_HISTORICAL_AGGTRADE_BARS_METHOD: "GetHistoricalAggTradeBars",
            GET_HISTORICAL_AGGTRADE_BARS_READINESS_METHOD: "GetHistoricalAggTradeBarsReadiness",
            GET_HISTORICAL_FUNDING_METHOD: "GetHistoricalFundingRates",
            GET_EXCHANGE_INFO_METHOD: "GetExchangeInfo",
            GET_CURRENT_FUNDING_METHOD: "GetCurrentFundingRates",
            GET_SETTLEMENT_FUNDING_METHOD: "GetSettlementFundingRatesAt",
        }
        request_type = request_types.get(method)
        rpc_name = rpc_names.get(method)
        if request_type is None or rpc_name is None:
            raise NativeGrpcUnavailable(f"native backend does not support method: {method}")
        request = parse_dict(payload, request_type())
        response = getattr(self._stub, rpc_name)(request, timeout=max_time)
        return message_to_dict(response, preserving_proto_field_name=False)


class ExchangeGatewayRefClient:
    def __init__(
        self,
        target: str,
        *,
        grpcurl: str = "grpcurl",
        import_path: str | Path = REPO_ROOT,
        proto: str | Path = DEFAULT_PROTO,
        backend: str = "auto",
    ) -> None:
        if backend not in {"auto", "native", "grpcurl"}:
            raise ValueError("backend must be one of: auto, native, grpcurl")
        self.target = target
        self.grpcurl = grpcurl
        self.import_path = Path(import_path)
        self.proto = proto
        self.backend = backend
        self._native: NativeGrpcUnaryClient | None = None
        if backend in {"auto", "native"}:
            try:
                self._native = NativeGrpcUnaryClient(target)
            except NativeGrpcUnavailable:
                if backend == "native":
                    raise

    def _base_args(self, *, max_time: float | None = None, proto: str | Path | None = None) -> list[str]:
        args = [self.grpcurl, "-plaintext"]
        if max_time is not None:
            args.extend(["-max-time", str(max_time)])
        args.extend(["-import-path", str(self.import_path), "-proto", str(proto or self.proto)])
        return args

    def close(self) -> None:
        if self._native is not None:
            self._native.close()

    def unary(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        max_time: float = 30,
        proto: str | Path | None = None,
    ) -> dict[str, Any]:
        if proto is None and self._native is not None:
            return self._native.unary(method, payload, max_time=max_time)
        args = [
            *self._base_args(max_time=max_time, proto=proto),
            "-d",
            json.dumps(payload, separators=(",", ":")),
            self.target,
            method,
        ]
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise GrpcurlError((completed.stderr or completed.stdout or "").strip())
        return json.loads(completed.stdout or "{}")

    def stream(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        max_time: float | None = None,
        proto: str | Path | None = None,
    ) -> Iterator[dict[str, Any]]:
        args = [
            *self._base_args(max_time=max_time, proto=proto),
            "-d",
            json.dumps(payload, separators=(",", ":")),
            self.target,
            method,
        ]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if proc.stdout is None:
                return
            yield from iter_json_objects(proc.stdout)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)

    def get_current_funding(self, exchange: str, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        response = self.unary(GET_CURRENT_FUNDING_METHOD, {"exchange": exchange, "symbols": symbols or []})
        return list(response.get("snapshots", []))

    def get_latest_market_data(
        self,
        exchange: str,
        symbols: list[str] | None,
        interval_seconds: int,
    ) -> dict[str, Any]:
        return self.unary(
            GET_LATEST_MARKET_DATA_METHOD,
            {"exchange": exchange, "symbols": symbols or [], "intervalSeconds": interval_seconds},
        )

    def get_historical_bars(
        self,
        exchange: str,
        symbol: str,
        interval_seconds: int,
        limit: int,
        *,
        end_time_ms: int = 0,
        include_bar_envelope: bool = False,
        max_time: float = 30,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeBarEnvelope": include_bar_envelope,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(GET_HISTORICAL_BARS_METHOD, payload, max_time=max_time)

    def get_historical_bars_readiness(
        self,
        exchange: str,
        symbols: list[str] | None,
        interval_seconds: list[int],
        limit: int,
        *,
        end_time_ms: int = 0,
        include_gaps: bool = True,
        max_gaps: int = 5,
        max_time: float = 180,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbols": symbols or [],
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeGaps": include_gaps,
            "maxGaps": max_gaps,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(GET_HISTORICAL_BARS_READINESS_METHOD, payload, max_time=max_time)

    def get_historical_aggtrade_bars(
        self,
        exchange: str,
        symbol: str,
        interval_seconds: int,
        limit: int,
        *,
        end_time_ms: int = 0,
        include_bar_envelope: bool = False,
        max_time: float = 30,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeBarEnvelope": include_bar_envelope,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(GET_HISTORICAL_AGGTRADE_BARS_METHOD, payload, max_time=max_time)

    def get_historical_aggtrade_bars_readiness(
        self,
        exchange: str,
        symbols: list[str] | None,
        interval_seconds: list[int],
        limit: int,
        *,
        end_time_ms: int = 0,
        include_gaps: bool = True,
        max_gaps: int = 5,
        max_time: float = 180,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbols": symbols or [],
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeGaps": include_gaps,
            "maxGaps": max_gaps,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(GET_HISTORICAL_AGGTRADE_BARS_READINESS_METHOD, payload, max_time=max_time)

    def get_historical_aggtrade_klines(
        self,
        exchange: str,
        symbol: str,
        interval_seconds: int,
        limit: int,
        *,
        end_time_ms: int = 0,
        include_bar_envelope: bool = False,
        max_time: float = 30,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeBarEnvelope": include_bar_envelope,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(
            GET_HISTORICAL_AGGTRADE_KLINES_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )

    def get_historical_aggtrade_kline_readiness(
        self,
        exchange: str,
        symbols: list[str] | None,
        interval_seconds: list[int],
        limit: int,
        *,
        end_time_ms: int = 0,
        include_gaps: bool = True,
        max_gaps: int = 5,
        max_time: float = 180,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbols": symbols or [],
            "intervalSeconds": interval_seconds,
            "limit": limit,
            "includeGaps": include_gaps,
            "maxGaps": max_gaps,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(
            GET_HISTORICAL_AGGTRADE_KLINE_READINESS_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )

    def get_historical_aggtrade_feature_bars(
        self,
        exchange: str,
        symbol: str,
        dataset: str,
        interval: str,
        limit: int,
        *,
        end_time_ms: int = 0,
        max_time: float = 30,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "dataset": dataset,
            "interval": interval,
            "limit": limit,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(
            GET_HISTORICAL_AGGTRADE_FEATURE_BARS_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )

    def get_historical_aggtrade_feature_readiness(
        self,
        subscriptions: list[dict[str, str]],
        limit: int,
        *,
        end_time_ms: int = 0,
        max_time: float = 180,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"subscriptions": subscriptions, "limit": limit}
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(
            GET_HISTORICAL_AGGTRADE_FEATURE_READINESS_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )

    def get_historical_aggtrade_kline_slices(
        self,
        exchange: str,
        symbols: list[str],
        interval_seconds: int,
        *,
        feature_dataset: str = "market_features",
        feature_interval: str = "1h",
        limit: int = 300,
        end_time_ms: int = 0,
        feature_readiness_policy: str = "FEATURE_READINESS_POLICY_CURRENT",
        max_time: float = 180,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbols": symbols,
            "intervalSeconds": interval_seconds,
            "featureDataset": feature_dataset,
            "featureInterval": feature_interval,
            "limit": limit,
            "featureReadinessPolicy": feature_readiness_policy,
        }
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(
            GET_HISTORICAL_AGGTRADE_KLINE_SLICES_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )

    def get_historical_funding_rates(
        self,
        exchange: str,
        symbol: str,
        limit: int,
        *,
        contract_type: str = "usdt",
        start_time_ms: int = 0,
        end_time_ms: int = 0,
        include_provisional: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "exchange": exchange,
            "symbol": symbol,
            "contractType": contract_type,
            "limit": limit,
            "includeProvisional": include_provisional,
        }
        if start_time_ms > 0:
            payload["startTimeMs"] = str(start_time_ms)
        if end_time_ms > 0:
            payload["endTimeMs"] = str(end_time_ms)
        return self.unary(GET_HISTORICAL_FUNDING_METHOD, payload)

    def get_exchange_info(
        self,
        exchange: str,
        symbols: list[str] | None = None,
        *,
        include_ineligible: bool = False,
    ) -> dict[str, Any]:
        return self.unary(
            GET_EXCHANGE_INFO_METHOD,
            {
                "exchange": exchange,
                "symbols": symbols or [],
                "includeIneligible": include_ineligible,
            },
        )

    def get_settlement_funding_at(
        self,
        exchange: str,
        symbols: list[str],
        timestamps_ms: list[int],
        *,
        fill_policy: str = EXACT_ZERO_FILL,
    ) -> list[dict[str, Any]]:
        response = self.unary(
            GET_SETTLEMENT_FUNDING_METHOD,
            {
                "exchange": exchange,
                "symbols": symbols,
                "timestampsMs": [str(value) for value in timestamps_ms],
                "fillPolicy": fill_policy,
            },
        )
        return list(response.get("rates", []))

    def subscribe_bars(
        self,
        exchange: str,
        symbols: list[str],
        interval_seconds: int,
        *,
        max_time: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        payload = {
            "subscriptions": [
                {"exchange": exchange, "symbol": symbol, "intervalSeconds": interval_seconds}
                for symbol in symbols
            ],
            "includeBarEnvelope": True,
        }
        yield from self.stream(SUBSCRIBE_BARS_METHOD, payload, max_time=max_time)

    def subscribe_market_data_slices(
        self,
        exchange: str,
        symbols: list[str],
        bar_interval_seconds: int,
        *,
        feature_datasets: list[str] | None = None,
        feature_interval: str = "1h",
        feature_readiness_policy: str = "FEATURE_READINESS_POLICY_CURRENT",
        release_timeout_ms: int = 0,
        require_current_daily_feature: bool = False,
        max_time: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        payload = {
            "subscriptions": [
                {
                    "exchange": exchange,
                    "symbols": symbols,
                    "barIntervalSeconds": bar_interval_seconds,
                    "featureDatasets": feature_datasets or ["market_features"],
                    "featureInterval": feature_interval,
                    "featureReadinessPolicy": feature_readiness_policy,
                    "releaseTimeoutMs": release_timeout_ms,
                    "requireCurrentDailyFeature": require_current_daily_feature,
                }
            ]
        }
        yield from self.stream(SUBSCRIBE_MARKET_DATA_SLICES_METHOD, payload, max_time=max_time)

    def subscribe_aggtrade_kline_slices(
        self,
        exchange: str,
        symbols: list[str],
        bar_interval_seconds: int,
        *,
        feature_datasets: list[str] | None = None,
        feature_interval: str = "1h",
        feature_readiness_policy: str = "FEATURE_READINESS_POLICY_CURRENT",
        release_timeout_ms: int = 0,
        require_current_daily_feature: bool = False,
        max_time: float | None = None,
    ) -> Iterator[dict[str, Any]]:
        payload = {
            "subscriptions": [
                {
                    "exchange": exchange,
                    "symbols": symbols,
                    "barIntervalSeconds": bar_interval_seconds,
                    "featureDatasets": feature_datasets or ["market_features"],
                    "featureInterval": feature_interval,
                    "featureReadinessPolicy": feature_readiness_policy,
                    "releaseTimeoutMs": release_timeout_ms,
                    "requireCurrentDailyFeature": require_current_daily_feature,
                }
            ]
        }
        yield from self.stream(
            SUBSCRIBE_AGGTRADE_KLINE_SLICES_METHOD,
            payload,
            max_time=max_time,
            proto=AGGTRADE_KLINE_PROTO,
        )


def bar_record(message: dict[str, Any]) -> dict[str, Any] | None:
    envelope = message.get("barEnvelope") or {}
    bar = envelope.get("bar") or message.get("bar") or {}
    if not bar:
        return None
    metadata = envelope.get("metadata") or {}
    open_time_ms = int(bar.get("openTimeMs", 0))
    return {
        "timestamp": utc_iso(open_time_ms),
        "open_time_ms": open_time_ms,
        "exchange": bar.get("exchange", ""),
        "symbol": bar.get("symbol", ""),
        "interval_seconds": int(bar.get("intervalSeconds", 0)),
        "open": decimal_str(bar.get("open")),
        "high": decimal_str(bar.get("high")),
        "low": decimal_str(bar.get("low")),
        "close": decimal_str(bar.get("close")),
        "volume": decimal_str(bar.get("volume")),
        "amount": decimal_sum_str(bar.get("takerBuyQuoteVolume"), bar.get("takerSellQuoteVolume")),
        "trade_count": int(
            bar.get(
                "tradeCount",
                int(bar.get("takerBuyTrades", 0)) + int(bar.get("takerSellTrades", 0)),
            )
        ),
        "taker_buy_volume": decimal_str(bar.get("takerBuyVolume")),
        "taker_buy_amount": decimal_str(bar.get("takerBuyQuoteVolume")),
        "taker_buy_trades": int(bar.get("takerBuyTrades", 0)),
        "taker_sell_volume": decimal_str(bar.get("takerSellVolume")),
        "taker_sell_amount": decimal_str(bar.get("takerSellQuoteVolume")),
        "taker_sell_trades": int(bar.get("takerSellTrades", 0)),
        "data_quality": bar.get("dataQuality", ""),
        "subject": envelope.get("subject", ""),
        "stream_sequence": int(envelope.get("streamSequence", 0)),
        "worker_id": metadata.get("workerId", ""),
        "assignment_generation": int(metadata.get("assignmentGeneration", 0)),
        "config_version": metadata.get("configVersion", ""),
        "published_at_ms": int(metadata.get("publishedAtUnixMs", 0)),
    }


def current_funding_record(item: dict[str, Any]) -> dict[str, Any]:
    event_time_ms = int(item.get("eventTimeMs", 0))
    next_funding_time_ms = int(item.get("nextFundingTimeMs", 0))
    return {
        "event_time": utc_iso(event_time_ms),
        "event_time_ms": event_time_ms,
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "contract_type": item.get("contractType", ""),
        "funding_rate": decimal_str(item.get("fundingRate")),
        "mark_price": decimal_str(item.get("markPrice")),
        "index_price": decimal_str(item.get("indexPrice")),
        "estimated_settle_price": decimal_str(item.get("estimatedSettlePrice")),
        "next_funding_time": utc_iso(next_funding_time_ms),
        "next_funding_time_ms": next_funding_time_ms,
        "source": item.get("source", ""),
        "quality": item.get("quality", ""),
        "producer_id": item.get("producerId", ""),
        "producer_epoch": int(item.get("producerEpoch", 0)),
        "published_at_ms": int(item.get("publishedAtMs", 0)),
        "sequence_in_epoch": int(item.get("sequenceInEpoch", 0)),
    }


def latest_market_data_record(item: dict[str, Any]) -> dict[str, Any] | None:
    row = bar_record({"barEnvelope": item.get("barEnvelope")})
    if row is None:
        return None

    funding = item.get("currentFunding") or {}
    if funding:
        funding_row = current_funding_record(funding)
        row.update(
            {
                "funding_rate_last": funding_row["funding_rate"],
                "funding_event_time": funding_row["event_time"],
                "funding_event_time_ms": funding_row["event_time_ms"],
                "funding_next_time": funding_row["next_funding_time"],
                "funding_next_time_ms": funding_row["next_funding_time_ms"],
                "funding_mark_price": funding_row["mark_price"],
                "funding_index_price": funding_row["index_price"],
                "funding_source": funding_row["source"],
                "funding_quality": funding_row["quality"],
                "funding_published_at_ms": funding_row["published_at_ms"],
            }
        )
    else:
        row.update(
            {
                "funding_rate_last": "",
                "funding_event_time": "",
                "funding_event_time_ms": 0,
                "funding_next_time": "",
                "funding_next_time_ms": 0,
                "funding_mark_price": "",
                "funding_index_price": "",
                "funding_source": "",
                "funding_quality": "",
                "funding_published_at_ms": 0,
            }
        )
    return row


def exchange_info_record(item: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    onboard_time_ms = int(item.get("onboardTimeMs", 0))
    return {
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "pair": item.get("pair", ""),
        "contract_type": item.get("contractType", ""),
        "status": item.get("status", ""),
        "quote_asset": item.get("quoteAsset", ""),
        "margin_asset": item.get("marginAsset", ""),
        "onboard_time_ms": onboard_time_ms,
        "listing_time": utc_iso(onboard_time_ms),
        "cached_at_ms": int(response.get("cachedAtMs", 0)),
        "next_refresh_after_ms": int(response.get("nextRefreshAfterMs", 0)),
        "source": response.get("source", ""),
    }


def historical_bars_readiness_record(item: dict[str, Any]) -> dict[str, Any]:
    gaps = []
    backfill_eligible_missing_bars = 0
    for gap in item.get("gaps", []):
        start_time_ms = int(gap.get("startTimeMs", 0))
        end_time_ms_exclusive = int(gap.get("endTimeMsExclusive", 0))
        missing_bars = int(gap.get("missingBars", 0))
        backfill_eligible = bool(gap.get("backfillEligible", False))
        if backfill_eligible:
            backfill_eligible_missing_bars += missing_bars
        gaps.append(
            {
                "start_time": utc_iso(start_time_ms),
                "start_time_ms": start_time_ms,
                "end_time_exclusive": utc_iso(end_time_ms_exclusive),
                "end_time_ms_exclusive": end_time_ms_exclusive,
                "missing_bars": missing_bars,
                "backfill_eligible": backfill_eligible,
                "skip_reason": gap.get("skipReason", ""),
            }
        )

    window_start_ms = int(item.get("windowStartMs", 0))
    window_end_ms = int(item.get("windowEndMs", 0))
    available_from_ms = int(item.get("availableFromMs", 0))
    available_to_ms = int(item.get("availableToMs", 0))
    ready_from_ms = int(item.get("readyFromMs", 0))
    ready_to_ms = int(item.get("readyToMs", 0))
    last_backfill_started_at_ms = int(item.get("lastBackfillStartedAtMs", 0))
    last_backfill_completed_at_ms = int(item.get("lastBackfillCompletedAtMs", 0))
    updated_at_ms = int(item.get("updatedAtMs", 0))
    return {
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "interval_seconds": int(item.get("intervalSeconds", 0)),
        "ready": bool(item.get("ready", False)),
        "status": item.get("status", ""),
        "reason": item.get("reason", ""),
        "requested_limit": int(item.get("requestedLimit", 0)),
        "window_start": utc_iso(window_start_ms),
        "window_start_ms": window_start_ms,
        "window_end": utc_iso(window_end_ms),
        "window_end_ms": window_end_ms,
        "available_from": utc_iso(available_from_ms),
        "available_from_ms": available_from_ms,
        "available_to": utc_iso(available_to_ms),
        "available_to_ms": available_to_ms,
        "ready_from": utc_iso(ready_from_ms),
        "ready_from_ms": ready_from_ms,
        "ready_to": utc_iso(ready_to_ms),
        "ready_to_ms": ready_to_ms,
        "missing_gap_count": int(item.get("missingGapCount", 0)),
        "backfill_eligible_missing_bars": backfill_eligible_missing_bars,
        "insufficient_listing_age": bool(item.get("insufficientListingAge", False)),
        "last_backfill_started_at": utc_iso(last_backfill_started_at_ms),
        "last_backfill_started_at_ms": last_backfill_started_at_ms,
        "last_backfill_completed_at": utc_iso(last_backfill_completed_at_ms),
        "last_backfill_completed_at_ms": last_backfill_completed_at_ms,
        "last_error": item.get("lastError", ""),
        "updated_at": utc_iso(updated_at_ms),
        "updated_at_ms": updated_at_ms,
        "gaps": gaps,
    }


def feature_bar_record(item: dict[str, Any]) -> dict[str, Any]:
    open_time_ms = int(item.get("openTimeMs", 0))
    end_time_ms = int(item.get("endTimeMs", 0))
    columns = list(item.get("columns", []))
    values = list(item.get("values", []))
    missing_mask = list(item.get("missingMask", []))
    feature_values: dict[str, str | None] = {}
    missing_columns: list[str] = []
    for index, column in enumerate(columns):
        missing = bool(missing_mask[index]) if index < len(missing_mask) else False
        value = values[index] if index < len(values) else ""
        if missing:
            missing_columns.append(column)
        feature_values[column] = None if missing else value
    return {
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "dataset": item.get("dataset", ""),
        "interval": item.get("interval", ""),
        "open_time": utc_iso(open_time_ms),
        "open_time_ms": open_time_ms,
        "end_time": utc_iso(end_time_ms),
        "end_time_ms": end_time_ms,
        "completeness": item.get("completeness", ""),
        "source_version": item.get("sourceVersion", ""),
        "published_at_ms": int(item.get("publishedAtMs", 0)),
        "missing_count": len(missing_columns),
        "missing_columns": missing_columns,
        "values": feature_values,
    }


def market_data_slice_record(item: dict[str, Any]) -> dict[str, Any]:
    slice_time_ms = int(item.get("sliceTimeMs", 0))
    released_at_ms = int(item.get("releasedAtMs", 0))
    return {
        "payload_type": "slice",
        "exchange": item.get("exchange", ""),
        "bar_interval_seconds": int(item.get("barIntervalSeconds", 0)),
        "slice_time": utc_iso(slice_time_ms),
        "slice_time_ms": slice_time_ms,
        "completeness": item.get("completeness", ""),
        "released_at": utc_iso(released_at_ms),
        "released_at_ms": released_at_ms,
        "bars": [
            row
            for bar in item.get("bars", [])
            if (row := bar_record({"bar": bar})) is not None
        ],
        "feature_bars": [feature_bar_record(feature_bar) for feature_bar in item.get("featureBars", [])],
    }


def slice_missing_input_record(item: dict[str, Any]) -> dict[str, Any]:
    expected_time_ms = int(item.get("expectedTimeMs", 0))
    return {
        "payload_type": "missing_input",
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "input_type": item.get("inputType", ""),
        "dataset": item.get("dataset", ""),
        "interval": item.get("interval", ""),
        "feature_readiness_policy": item.get("featureReadinessPolicy", ""),
        "expected_time": utc_iso(expected_time_ms),
        "expected_time_ms": expected_time_ms,
        "reason": item.get("reason", ""),
    }


def market_data_slice_stream_record(message: dict[str, Any]) -> dict[str, Any] | None:
    if "slice" in message:
        return market_data_slice_record(message["slice"])
    if "missingInput" in message:
        return slice_missing_input_record(message["missingInput"])
    if "status" in message:
        return {"payload_type": "status", "status": message["status"]}
    return None


def settlement_funding_record(item: dict[str, Any]) -> dict[str, Any]:
    timestamp_ms = int(item.get("timestampMs", 0))
    settlement = item.get("settlementEvent") or {}
    return {
        "timestamp": utc_iso(timestamp_ms),
        "timestamp_ms": timestamp_ms,
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "contract_type": item.get("contractType", ""),
        "funding_rate": decimal_str(item.get("fundingRate")),
        "matched_settlement_event": bool(item.get("matchedSettlementEvent", False)),
        "settlement_source": settlement.get("source", ""),
        "settlement_quality": settlement.get("quality", ""),
        "settlement_mark_price": decimal_str(settlement.get("markPrice")),
        "observed_event_time_ms": int(settlement.get("observedEventTimeMs", 0)),
        "confirmed_at_ms": int(settlement.get("confirmedAtMs", 0)),
        "published_at_ms": int(settlement.get("publishedAtMs", 0)),
        "producer_id": settlement.get("producerId", ""),
        "producer_epoch": int(settlement.get("producerEpoch", 0)),
        "sequence_in_epoch": int(settlement.get("sequenceInEpoch", 0)),
    }


def historical_funding_record(item: dict[str, Any]) -> dict[str, Any]:
    funding_time_ms = int(item.get("fundingTimeMs", 0))
    return {
        "timestamp": utc_iso(funding_time_ms),
        "funding_time_ms": funding_time_ms,
        "exchange": item.get("exchange", ""),
        "symbol": item.get("symbol", ""),
        "contract_type": item.get("contractType", ""),
        "funding_rate": decimal_str(item.get("fundingRate")),
        "source": item.get("source", ""),
        "quality": item.get("quality", ""),
        "mark_price": decimal_str(item.get("markPrice")),
        "observed_event_time_ms": int(item.get("observedEventTimeMs", 0)),
        "confirmed_at_ms": int(item.get("confirmedAtMs", 0)),
        "published_at_ms": int(item.get("publishedAtMs", 0)),
        "producer_id": item.get("producerId", ""),
        "producer_epoch": int(item.get("producerEpoch", 0)),
        "sequence_in_epoch": int(item.get("sequenceInEpoch", 0)),
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)
