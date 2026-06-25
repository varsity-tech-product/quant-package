"""
Rewrite single-symbol factor C# fragments into per-symbol form.

Vendored verbatim from ``quantai-service/strategy_composer/rewriter.py`` (logic
unchanged) so the live strategy composes factors **identically** to the backtest
server. No external dependencies — standard library only.

The plugins in step4 produce C# fragments designed for a single-symbol strategy
(one instance of fields like _highBuf, _window). For cross-sectional we need to
embed each factor's logic into a FactorState inner class so we can keep one
instance per symbol.

The rewriter does the minimum textual transformation needed:

  1. Inline parameter defaults: replace GetIntParameter("name", N) and
     GetDoubleParameter("name", X) with the literal default value. This avoids
     having to forward Lean's parameter dictionary through nested classes.
  2. Strip leading whitespace from multi-line FACTOR_COMPUTE_BODY so the
     fragment indents cleanly inside the template's method body.

No identifier renaming is needed because each factor's state lives inside its
own FactorState_F<i> class with its own scope.
"""
from __future__ import annotations

import re
import textwrap


_GET_INT_RE = re.compile(
    r"""GetIntParameter\(\s*"[^"]*"\s*,\s*(?P<def>-?\d+)\s*\)"""
)
_GET_DOUBLE_RE = re.compile(
    r"""GetDoubleParameter\(\s*"[^"]*"\s*,\s*(?P<def>-?\d+(?:\.\d+)?)\s*\)"""
)

# Matches: var <name> = <queueIdent>.ToArray();
# Captures the local array name so we can emit a NaN-guard loop.
_TOARRAY_NAME_RE = re.compile(
    r"""\bvar\s+(?P<name>\w+)\s*=\s*\w+\.ToArray\(\)\s*;"""
)


def build_extra_buf_nan_guard(extra_buf_toarray: str) -> str:
    """Generate a NaN guard block that scans every array produced by extra_buf_toarray.

    The futures/on-chain columns (open_interest_*, funding_rate_*, *_long_short_ratio,
    liquidation_*, binance_premium_index_*) are NaN for older coins or early dates
    where the upstream source has no data. If we let NaN propagate into rolling/sum
    the factor returns rawSignal=NaN, which silently breaks:
      - CS ranking: OrderByDescending puts NaN at the bottom → it enters shortSet
        and gets a real short position based on a garbage signal.
      - TS position updates: every comparison with NaN is false → existing position
        freezes and can never be updated.

    Returning false from Compute() makes the cross-sectional template's
    `allOk = false; continue;` skip the symbol cleanly, and the time-series
    TryComputeRawSignal short-circuits OnData. Either way no bad order goes out.

    Returns "" if no extra arrays are declared (close-only factors are unaffected).
    """
    if not extra_buf_toarray or not extra_buf_toarray.strip():
        return ""
    names = _TOARRAY_NAME_RE.findall(extra_buf_toarray)
    if not names:
        return ""
    lines = [
        "// Auto-injected NaN guard for futures/on-chain extra columns.",
        "// Skip this symbol today if any value in the rolling buffer is NaN.",
    ]
    for n in names:
        lines.append(
            f"for (int __nanI = 0; __nanI < {n}.Length; __nanI++) "
            f"if (double.IsNaN({n}[__nanI])) return false;"
        )
    return "\n".join(lines) + "\n"


def inline_default_params(code: str) -> str:
    """Replace GetIntParameter("k", N) / GetDoubleParameter("k", X) with the literal default.

    The plugin authors put the same default value in FACTOR_DEFAULT_PARAMS, so the
    literal we extract here matches the Python research path. This removes the
    need to wire algo.GetIntParameter through the FactorState class.
    """
    code = _GET_INT_RE.sub(lambda m: m.group("def"), code)
    code = _GET_DOUBLE_RE.sub(lambda m: m.group("def"), code)
    return code


def dedent_block(text: str) -> str:
    """textwrap.dedent for blocks that may have leading newlines."""
    return textwrap.dedent(text).lstrip("\n").rstrip() + "\n"


def reindent(block: str, spaces: int) -> str:
    """Reindent every non-blank line by `spaces` spaces."""
    pad = " " * spaces
    out_lines: list[str] = []
    for line in block.splitlines():
        if line.strip() == "":
            out_lines.append("")
        else:
            out_lines.append(pad + line.lstrip())
    return "\n".join(out_lines)


def prepare_factor_fragments(sections: dict[str, object], factor_index: int) -> dict[str, str]:
    """Pull the relevant string fragments out of a plugin's FACTOR_SECTIONS dict.

    Returns a dict keyed by template variable name (without leading underscores),
    with each value cleaned up and re-indented to the template's expected level.
    Numbers / non-strings are coerced to str() for safety.
    """
    def _get(name: str) -> str:
        v = sections.get(name, "")
        return v if isinstance(v, str) else str(v)

    param_fields = _get("__FACTOR_PARAM_FIELDS__")
    factor_init = inline_default_params(_get("__FACTOR_INIT__"))
    factor_log = _get("__FACTOR_LOG__")
    price_window_expr = _get("__PRICE_WINDOW_EXPR__").strip() or "1"
    extra_buf_fields = _get("__EXTRA_BUF_FIELDS__")
    extra_buf_enqueue = _get("__EXTRA_BUF_ENQUEUE__")
    extra_buf_dequeue = _get("__EXTRA_BUF_DEQUEUE__")
    extra_buf_toarray = _get("__EXTRA_BUF_TOARRAY__")

    # Prepend an auto-injected NaN guard for every extra array declared above.
    # This eliminates the silent failure mode where a NaN funding_rate / open_interest
    # cell propagates through rolling/sum and ends up either freezing a position (TS)
    # or seeding a random short basket pick (CS). With the guard, Compute() returns
    # false the moment any extra buffer contains NaN, and the symbol is skipped that
    # day. Factor authors do not need to write their own IsNaN checks.
    # Dedent the user's body first so it shares the same 0-indent baseline as the
    # guard; the template's `{{ compute_body|indent(16, True) }}` re-indents both.
    user_body = dedent_block(_get("__FACTOR_COMPUTE_BODY__"))
    nan_guard = build_extra_buf_nan_guard(extra_buf_toarray)
    compute_body = (nan_guard + user_body).rstrip() + "\n"

    return {
        "factor_index": str(factor_index),
        "factor_type": _get("__FACTOR_TYPE__"),
        "factor_description": _get("__FACTOR_DESCRIPTION__"),
        "factor_formula": _get("__FACTOR_FORMULA__"),
        "param_fields": param_fields.rstrip("\n"),
        "factor_init": factor_init.rstrip("\n"),
        "factor_log": factor_log.rstrip("\n"),
        "price_window_expr": price_window_expr,
        "extra_buf_fields": extra_buf_fields.rstrip("\n"),
        "extra_buf_enqueue": extra_buf_enqueue.rstrip("\n"),
        "extra_buf_dequeue": extra_buf_dequeue.rstrip("\n"),
        "extra_buf_toarray": extra_buf_toarray.rstrip("\n"),
        "compute_body": compute_body.rstrip("\n"),
    }
