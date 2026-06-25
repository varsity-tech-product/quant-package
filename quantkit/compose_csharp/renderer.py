"""Render factor plugins + a :class:`StrategySpec` into Lean C# source.

Vendored/adapted from ``quantai-service/strategy_composer/renderer.py``. Two
differences from the server version:

* **content-mode only** — plugins come straight from :mod:`quantkit.plugins`
  (``FactorPlugin.sections``); no job_id, no S3/EFS ``plugin_loader``,
  no ``universe_resolver``. The caller passes a plain list of trading symbols.
* **two targets** — :func:`render_backtest_strategy` reproduces the server's
  ``FactorCsvBar`` custom-data strategy (for reconciliation), while
  :func:`render_live_strategy` emits the ``binance_direct`` live shell. Both
  share the identical ``FactorState`` / ``Rebalance`` factor-logic half.

The factor-logic half (per-symbol state classes + cross-sectional z-score →
weighted composite → rank → baskets) is byte-identical between the two
templates, so live trades on the **same composite signal** the backtest used.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..plugins import FactorPlugin
from .rewriter import prepare_factor_fragments
from .spec import StrategySpec

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)


def _bar_to_resolution(bar_size: str) -> tuple[str, str, float]:
    """Map bar_size → (Lean Resolution name, resolution folder, hours per bar)."""
    bs = bar_size.lower().strip()
    if bs in ("1d", "d", "1day", "daily"):
        return "Daily", "daily", 24.0
    if bs in ("1h", "h", "1hour", "hourly"):
        return "Hour", "hour", 1.0
    if bs in ("1m", "1min", "minute"):
        return "Minute", "minute", 1 / 60.0
    raise ValueError(f"Unsupported bar_size for cross-sectional: {bar_size}")


def _token_from_pair(pair: str) -> str:
    """'btcusdt' → 'BTC', '1000pepeusdt' → '1000PEPE' (matches template TokenFromPair)."""
    upper = pair.upper()
    return upper[:-4] if upper.endswith("USDT") else upper


def _class_name(prefix: str, spec: StrategySpec, plugins: Sequence[FactorPlugin],
                weights: Sequence[float]) -> str:
    """Deterministic, valid C# class name from spec + factor identities."""
    h = hashlib.sha1()
    h.update(f"{spec.strategy_type}/{spec.ranking.mode}/{spec.ranking.value}".encode())
    h.update(f"/{spec.rebalance_bars}/{spec.start_date}/{spec.end_date}".encode())
    for p, w in zip(plugins, weights):
        h.update(f"{p.factor_type}/{w}".encode())
    return f"{prefix}_{h.hexdigest()[:10]}"


def _factors_ctx(plugins: Sequence[FactorPlugin]) -> list[dict]:
    ctx = []
    for i, plugin in enumerate(plugins):
        frags = prepare_factor_fragments(plugin.sections, i)
        frags["job_id"] = "inline"
        ctx.append(frags)
    return ctx


def _common_ctx(
    spec: StrategySpec,
    plugins: Sequence[FactorPlugin],
    weights: Sequence[float],
    class_name: str,
    bar_size: str,
    generated_at: Optional[str],
) -> dict:
    lean_res, folder, bar_hours = _bar_to_resolution(bar_size)
    start_dt = datetime.strptime(spec.start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(spec.end_date, "%Y-%m-%d")
    return {
        "class_name": class_name,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "factors": _factors_ctx(plugins),
        "weights": list(weights),
        "weighting_mode": spec.weighting.mode,
        "rank_mode": spec.ranking.mode,
        "rank_value": spec.ranking.value,
        "strategy_type": spec.strategy_type,
        "rebalance_bars": spec.rebalance_bars,
        "bar_size": bar_size,
        "lean_resolution": lean_res,
        "resolution_folder": folder,
        "bar_hours": bar_hours,
        "start_date": spec.start_date,
        "end_date": spec.end_date,
        "start_year": start_dt.year,
        "start_month": start_dt.month,
        "start_day": start_dt.day,
        "end_year": end_dt.year,
        "end_month": end_dt.month,
        "end_day": end_dt.day,
        "initial_cash": int(spec.initial_cash),
    }


def render_backtest_strategy(
    plugins: Sequence[FactorPlugin],
    spec: StrategySpec,
    symbols: Sequence[str],
    *,
    bar_size: str = "1d",
    generated_at: Optional[str] = None,
) -> tuple[str, str]:
    """Reproduce the server's FactorCsvBar custom-data strategy (reconciliation).

    ``symbols`` are lowercase pairs like ``btcusdt``. The daily universe is
    collapsed to a single snapshot at ``start_date`` containing every token —
    enough to render a valid, compilable strategy for diffing the factor-logic
    half against the backtest server output. Returns ``(cs_source, class_name)``.
    """
    weights = spec.resolved_weights(len(plugins))
    spec.validate(len(plugins))
    if len(weights) != len(plugins):
        raise ValueError("internal: weights length must match plugins length")

    all_symbols = [s.lower() for s in symbols]
    tokens = sorted({_token_from_pair(s) for s in all_symbols})

    class_name = _class_name("CrossSectionalComposite", spec, plugins, weights)
    ctx = _common_ctx(spec, plugins, weights, class_name, bar_size, generated_at)
    ctx["all_symbols"] = all_symbols
    ctx["daily_plan_items"] = [(spec.start_date, tokens)]

    template = _env.get_template("cross_sectional_backtest.cs.j2")
    return template.render(**ctx), class_name


def render_live_strategy(
    plugins: Sequence[FactorPlugin],
    spec: StrategySpec,
    symbols: Sequence[str],
    *,
    bar_size: str = "1d",
    subscribe_features: bool = True,
    generated_at: Optional[str] = None,
) -> tuple[str, str]:
    """Emit the binance_direct live strategy (AddCryptoFuture + 8778 live feed).

    ``symbols`` are lowercase pairs like ``btcusdt`` and become the tradable
    universe (one ``AddCryptoFuture`` each). When ``subscribe_features`` is True,
    each symbol also subscribes the ``market_features`` stream so factors that
    need taker/OI/funding columns can compute; pure-price factors work either way.
    Returns ``(cs_source, class_name)``.
    """
    weights = spec.resolved_weights(len(plugins))
    spec.validate(len(plugins))
    if len(weights) != len(plugins):
        raise ValueError("internal: weights length must match plugins length")

    all_symbols = [s.lower() for s in symbols]

    class_name = _class_name("CrossSectionalLive", spec, plugins, weights)
    ctx = _common_ctx(spec, plugins, weights, class_name, bar_size, generated_at)
    ctx["all_symbols"] = all_symbols
    ctx["subscribe_features"] = subscribe_features

    template = _env.get_template("cross_sectional_live.cs.j2")
    return template.render(**ctx), class_name
