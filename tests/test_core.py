"""核心逻辑离线测试（无需网络 / grpcurl）。

直接跑：  python tests/test_core.py
或 pytest：pytest tests/test_core.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantkit.backtest import BacktestClient, Factor  # noqa: E402
from quantkit.compose import WeightedFactor, cross_section_zscore, target_weights  # noqa: E402
from quantkit.data.panels import build_panels, run_build_signal  # noqa: E402
from quantkit.plugins import all_required_fields, load_plugin  # noqa: E402

EXPECTED_FIELDS = {
    "flow_confirmed_smooth_trend_momentum":
        ["volume", "taker_buy_volume", "taker_sell_volume"],
    "trade_size_toxicity_flow_persistence":
        ["taker_buy_quote_volume", "taker_sell_quote_volume", "taker_buy_trades", "taker_sell_trades"],
    "carry_dislocation_positioning_mean_reversion":
        ["funding_rate_close", "binance_premium_index_close", "open_interest_close",
         "top_account_long_percent", "top_account_short_percent"],
}


def _bars(symbols, n=120):
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    out = {}
    for i, s in enumerate(symbols):
        rng = np.random.default_rng(i)
        close = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)), idx)
        vol = pd.Series(rng.uniform(1e3, 1e4, n), idx)
        tbv = vol * rng.uniform(0.4, 0.6, n)
        out[s] = pd.DataFrame({
            "close": close, "volume": vol,
            "taker_buy_volume": tbv, "taker_sell_volume": vol - tbv,
            "taker_buy_quote_volume": tbv * close, "taker_sell_quote_volume": (vol - tbv) * close,
            "taker_buy_trades": pd.Series(rng.integers(50, 500, n), idx).astype(float),
            "taker_sell_trades": pd.Series(rng.integers(50, 500, n), idx).astype(float),
        })
    return out


def test_required_fields():
    for name, expected in EXPECTED_FIELDS.items():
        p = load_plugin(ROOT / "example_plugin" / f"{name}.py")
        assert p.required_fields == expected, (name, p.required_fields)
    print("test_required_fields OK")


def test_build_signal_runs():
    p = load_plugin(ROOT / "example_plugin/flow_confirmed_smooth_trend_momentum.py")
    bars = _bars(["A", "B", "C", "D"])
    panels = build_panels(p, bars)
    assert set(panels) == {"close", "volume", "taker_buy_volume", "taker_sell_volume"}
    sig = run_build_signal(p, bars)
    assert sig.shape == (120, 4)
    print("test_build_signal_runs OK")


def test_cross_section_zscore():
    df = pd.DataFrame({"A": [1.0, 2], "B": [3.0, 4], "C": [5.0, 6]})
    z = cross_section_zscore(df)
    assert abs(z.iloc[0].mean()) < 1e-9
    print("test_cross_section_zscore OK")


def test_target_weights_neutral():
    f1 = WeightedFactor(load_plugin(ROOT / "example_plugin/flow_confirmed_smooth_trend_momentum.py"), 0.6)
    f2 = WeightedFactor(load_plugin(ROOT / "example_plugin/trade_size_toxicity_flow_persistence.py"), 0.4)
    bars = _bars(["A", "B", "C", "D", "E", "F"])
    w, dbg = target_weights([f1, f2], bars, ranking={"mode": "N", "value": 2}, strategy_type="neutral")
    assert abs(w.sum()) < 1e-9, "neutral 应 dollar-neutral"
    assert abs(w.abs().sum() - 1.0) < 1e-9, "gross 应 = 1.0"
    print("test_target_weights_neutral OK")


def test_backtest_validation():
    bt = BacktestClient()
    assert bt.base == "http://13.215.186.241:8001"
    for bad in (
        lambda: bt._validate([Factor("j", "p"), Factor("j", "p")], None),
        lambda: bt._validate([Factor("a", "x")], {"mode": "custom", "weights": [0.6, 0.4]}),
        lambda: bt._validate([Factor("a", "x"), Factor("b", "y")], {"mode": "custom", "weights": [0.6, 0.5]}),
    ):
        try:
            bad()
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass
    bt._validate([Factor("a", "x"), Factor("b", "y")], {"mode": "custom", "weights": [0.6, 0.4]})
    print("test_backtest_validation OK")


def test_union_fields():
    ps = [load_plugin(ROOT / "example_plugin" / f"{n}.py") for n in EXPECTED_FIELDS]
    union = all_required_fields(ps)
    assert "close" in union and "open_interest_close" in union
    print("test_union_fields OK")


if __name__ == "__main__":
    test_required_fields()
    test_build_signal_runs()
    test_cross_section_zscore()
    test_target_weights_neutral()
    test_backtest_validation()
    test_union_fields()
    print("\nALL TESTS PASSED")
