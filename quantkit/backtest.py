"""策略回测服务客户端。

封装 ``/home/ec2-user/quantai-service/docs/strategy_submit.md`` 描述的接口：
在已归档（有 job_id）的因子之上组装策略，提交到 MatchX 回测引擎，轮询拿结果。

注意：回测路径**不在本地算信号**——服务端用 plugin 的 C# 片段编译跑 Lean。
本地只需提供 ``{job_id, plugin}`` 即可。本地任意 plugin 想回测，需先经
quant-factor-loop 归档拿到 job_id。

基本用法::

    from quantkit.backtest import BacktestClient, Factor
    bt = BacktestClient()  # 默认 http://13.215.186.241:8001
    resp = bt.submit_cs(
        factors=[Factor("job_xxx", "chaikin_money_flow.py")],
        ranking={"mode": "N", "value": 5},
    )
    state = bt.wait(resp["strategy_id"])
    print(bt.summary(resp["strategy_id"]))
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
import json
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE = "http://13.215.186.241:8001"

# 服务端字段约束（见文档 §8），本地先校验以减少 422。
MAX_FACTORS = 5
MAX_TS_SYMBOLS = 20
WEIGHT_SUM_TOL = 1e-6


@dataclass
class Factor:
    """一个已归档因子的引用。"""

    job_id: str
    plugin: str

    def to_dict(self) -> dict[str, str]:
        # to dict
        return {"job_id": self.job_id, "plugin": self.plugin}


class BacktestError(RuntimeError):
    pass


class BacktestClient:
    def __init__(self, base: str = DEFAULT_BASE, *, timeout: float = 30.0) -> None:
        # init
        self.base = base.rstrip("/")
        self.timeout = timeout

    # ── HTTP 底层 ────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        # request
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            raise BacktestError(f"{method} {path} -> HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise BacktestError(f"{method} {path} -> {e.reason}") from e
        return json.loads(raw) if raw else None

    # ── 本地校验 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _validate(factors: list[Factor], weighting: dict | None) -> None:
        # validate
        if not 1 <= len(factors) <= MAX_FACTORS:
            raise ValueError(f"factors 数量必须 1..{MAX_FACTORS}，当前 {len(factors)}")
        seen = set()
        for f in factors:
            key = (f.job_id, f.plugin)
            if key in seen:
                raise ValueError(f"重复的 (job_id, plugin): {key}")
            seen.add(key)
        if weighting and weighting.get("mode") == "custom":
            w = weighting.get("weights") or []
            if len(w) != len(factors):
                raise ValueError("custom weights 长度必须等于 factors 数量")
            if any(x <= 0 for x in w):
                raise ValueError("custom weights 必须都 > 0")
            if abs(sum(w) - 1.0) > WEIGHT_SUM_TOL:
                raise ValueError(f"custom weights 之和必须为 1.0，当前 {sum(w)}")

    # ── 提交 ─────────────────────────────────────────────────────────────────
    def submit_cs(
        self,
        factors: list[Factor],
        ranking: dict[str, Any],
        *,
        weighting: dict | None = None,
        strategy_type: str = "neutral",
        start_date: str | None = None,
        end_date: str | None = None,
        initial_cash: float | None = None,
        rebalance_bars: int | None = None,
        taker_fee_rate: float | None = None,
        maker_fee_rate: float | None = None,
    ) -> dict:
        # 提交截面策略 ``POST /strategies/submit``。
        """提交截面策略 ``POST /strategies/submit``。"""
        self._validate(factors, weighting)
        body: dict[str, Any] = {
            "factors": [f.to_dict() for f in factors],
            "ranking": ranking,
            "strategy_type": strategy_type,
        }
        if weighting:
            body["weighting"] = weighting
        _put_optional(body, start_date=start_date, end_date=end_date,
                       initial_cash=initial_cash, rebalance_bars=rebalance_bars,
                       taker_fee_rate=taker_fee_rate, maker_fee_rate=maker_fee_rate)
        return self._request("POST", "/strategies/submit", body)

    def submit_ts(
        self,
        symbols: list[str],
        factors: list[Factor],
        *,
        weighting: dict | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        initial_cash: float | None = None,
        rebalance_bars: int | None = None,
    ) -> dict:
        # 提交时序策略 ``POST /strategies/submit_ts``。
        """提交时序策略 ``POST /strategies/submit_ts``。"""
        self._validate(factors, weighting)
        if not 1 <= len(symbols) <= MAX_TS_SYMBOLS:
            raise ValueError(f"symbols 数量必须 1..{MAX_TS_SYMBOLS}")
        body: dict[str, Any] = {
            "symbols": [s.lower() for s in symbols],
            "factors": [f.to_dict() for f in factors],
        }
        if weighting:
            body["weighting"] = weighting
        _put_optional(body, start_date=start_date, end_date=end_date,
                       initial_cash=initial_cash, rebalance_bars=rebalance_bars)
        return self._request("POST", "/strategies/submit_ts", body)

    # ── 读结果 ───────────────────────────────────────────────────────────────
    def status(self, strategy_id: str) -> dict:
        # status
        return self._request("GET", f"/strategies/{strategy_id}")

    def summary(self, strategy_id: str) -> dict:
        return self._request("GET", f"/strategies/{strategy_id}/summary")

    def equity_curve(self, strategy_id: str) -> dict:
        return self._request("GET", f"/strategies/{strategy_id}/equity_curve")

    def orders(self, strategy_id: str) -> dict:
        return self._request("GET", f"/strategies/{strategy_id}/orders")

    def result(self, strategy_id: str) -> dict:
        return self._request("GET", f"/strategies/{strategy_id}/result")

    def list_strategies(self, limit: int = 20, offset: int = 0) -> dict:
        return self._request("GET", f"/strategies?limit={limit}&offset={offset}")

    # ── 轮询直到完成 ─────────────────────────────────────────────────────────
    def wait(
        self,
        strategy_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float = 1800.0,
        on_progress=None,
    ) -> dict:
        """轮询 ``GET /strategies/{sid}`` 直到 completed/failed/timeout。

        Returns: 最终的 status dict。
        """
        deadline = time.monotonic() + timeout
        while True:
            st = self.status(strategy_id)
            state = (st.get("state") or {}).get("status", "")
            if on_progress:
                on_progress(st)
            if state in ("completed", "failed", "timeout"):
                return st
            if time.monotonic() > deadline:
                raise BacktestError(f"等待 {strategy_id} 超时（最后状态 {state}）")
            time.sleep(poll_interval)


def _put_optional(body: dict, **kwargs: Any) -> None:
    for k, v in kwargs.items():
        if v is not None:
            body[k] = v
