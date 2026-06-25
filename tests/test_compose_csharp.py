"""compose_csharp 离线测试（无需网络 / grpcurl / Lean）。

直接跑：  python tests/test_compose_csharp.py
或 pytest：pytest tests/test_compose_csharp.py

只验证 Python 渲染层：因子片段拼接、权重/ranking 校验、回测/实盘两套模板渲染出
结构良好（括号配平、关键脚手架齐全）的 C#。不编译 C#（无 Lean 运行时）。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantkit.compose_csharp.rewriter import (  # noqa: E402
    build_extra_buf_nan_guard,
    inline_default_params,
    prepare_factor_fragments,
)
from quantkit.compose_csharp.renderer import (  # noqa: E402
    render_backtest_strategy,
    render_live_strategy,
)
from quantkit.compose_csharp.spec import Ranking, StrategySpec, Weighting  # noqa: E402
from quantkit.plugins import load_plugin  # noqa: E402

SAMPLE_DIR = ROOT / "sample_factors"


def _balanced(src: str) -> None:
    assert src.count("{") == src.count("}"), ("brace imbalance", src.count("{"), src.count("}"))
    assert src.count("(") == src.count(")"), ("paren imbalance", src.count("("), src.count(")"))


def _a_feature_factor():
    """A sample plugin that declares extra (futures/on-chain) buffers."""
    for p in sorted(SAMPLE_DIR.glob("*.py")):
        if load_plugin(p).sections.get("__EXTRA_BUF_TOARRAY__", "").strip():
            return load_plugin(p)
    return load_plugin(sorted(SAMPLE_DIR.glob("*.py"))[0])


def _a_price_factor():
    """A sample plugin that does NOT declare extra buffers (close-only)."""
    for p in sorted(SAMPLE_DIR.glob("*.py")):
        if not load_plugin(p).sections.get("__EXTRA_BUF_TOARRAY__", "").strip():
            return load_plugin(p)
    return load_plugin(sorted(SAMPLE_DIR.glob("*.py"))[0])


def test_rewriter_inline_and_guard():
    assert inline_default_params('GetIntParameter("w", 18)') == "18"
    assert inline_default_params('GetDoubleParameter("s", 1.4)') == "1.4"
    g = build_extra_buf_nan_guard("var hi = _highBuf.ToArray();")
    assert "double.IsNaN(hi[__nanI])" in g
    assert build_extra_buf_nan_guard("") == ""  # close-only factor: no guard
    frags = prepare_factor_fragments(
        {"__FACTOR_TYPE__": "x", "__FACTOR_INIT__": '_w = GetIntParameter("w", 5);',
         "__PRICE_WINDOW_EXPR__": "_w"}, 0)
    assert frags["factor_init"] == "_w = 5;"
    assert frags["price_window_expr"] == "_w"
    print("test_rewriter_inline_and_guard OK")


def test_spec_validation():
    StrategySpec().validate(2)  # equal default
    StrategySpec(weighting=Weighting("custom", [0.6, 0.4])).validate(2)
    for bad in (
        lambda: StrategySpec(weighting=Weighting("custom", [0.6, 0.5])).validate(2),  # sum != 1
        lambda: StrategySpec(weighting=Weighting("custom", [1.0])).validate(2),        # len mismatch
        lambda: StrategySpec(ranking=Ranking("percent", 60)).validate(1),             # percent > 50
        lambda: StrategySpec(ranking=Ranking("N", 2.5)).validate(1),                  # N not int
        lambda: StrategySpec().validate(0),                                            # 0 factors
    ):
        try:
            bad()
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    assert StrategySpec(weighting=Weighting("custom", [0.6, 0.4])).resolved_weights(2) == [0.6, 0.4]
    assert StrategySpec().resolved_weights(4) == [0.25, 0.25, 0.25, 0.25]
    print("test_spec_validation OK")


def test_backtest_render():
    p = _a_feature_factor()
    spec = StrategySpec(weighting=Weighting("custom", [1.0]), ranking=Ranking("N", 5))
    src, cls = render_backtest_strategy([p], spec, ["btcusdt", "ethusdt", "solusdt"],
                                        generated_at="2026-06-25T00:00:00+00:00")
    _balanced(src)
    assert f"class {cls}" in src
    assert "AddData<FactorCsvBar>" in src           # backtest custom-data shell
    assert "FactorState_F0" in src and "private void Rebalance()" in src
    assert "GetIntParameter(" not in src            # all param calls inlined by rewriter
    print("test_backtest_render OK")


def test_live_render_with_features():
    p = _a_feature_factor()
    spec = StrategySpec(ranking=Ranking("percent", 20), strategy_type="neutral")
    src, cls = render_live_strategy([p], spec, ["btcusdt", "ethusdt", "solusdt", "bnbusdt"],
                                    generated_at="2026-06-25T00:00:00+00:00")
    _balanced(src)
    for must in ("AddCryptoFuture", "MatchXKlineWithCoinglassBar", "MergeFeature",
                 "SetHoldings(_tradable", "class LiveFactorBar", "_dryRun"):
        assert must in src, must
    assert "AddData<FactorCsvBar>" not in src       # not the backtest shell
    print("test_live_render_with_features OK")


def test_live_render_price_only():
    p = _a_price_factor()
    spec = StrategySpec(ranking=Ranking("N", 2))
    src, cls = render_live_strategy([p], spec, ["btcusdt", "ethusdt", "solusdt"],
                                    subscribe_features=False,
                                    generated_at="2026-06-25T00:00:00+00:00")
    _balanced(src)
    # features off → the feature carrier type must be entirely absent (else undefined-type)
    assert "MatchXKlineWithCoinglassBar" not in src
    assert "MergeFeature" not in src
    assert "AddCryptoFuture" in src and "FactorState_F0" in src
    print("test_live_render_price_only OK")


def test_live_render_multi_factor():
    plugins = [_a_price_factor(), _a_feature_factor()]
    spec = StrategySpec(weighting=Weighting("custom", [0.4, 0.6]), ranking=Ranking("N", 3))
    src, cls = render_live_strategy(plugins, spec, ["btcusdt", "ethusdt", "solusdt", "bnbusdt"],
                                    generated_at="2026-06-25T00:00:00+00:00")
    _balanced(src)
    assert "FactorState_F0" in src and "FactorState_F1" in src
    assert "_weights = new double[] { 0.4, 0.6 }" in src
    print("test_live_render_multi_factor OK")


def test_class_name_deterministic():
    p = _a_feature_factor()
    spec = StrategySpec(ranking=Ranking("N", 5))
    _, c1 = render_live_strategy([p], spec, ["btcusdt", "ethusdt"], generated_at="A")
    _, c2 = render_live_strategy([p], spec, ["btcusdt", "ethusdt"], generated_at="B")
    assert c1 == c2, "class name must be stable across generated_at"
    print("test_class_name_deterministic OK")


if __name__ == "__main__":
    test_rewriter_inline_and_guard()
    test_spec_validation()
    test_backtest_render()
    test_live_render_with_features()
    test_live_render_price_only()
    test_live_render_multi_factor()
    test_class_name_deterministic()
    print("\nALL TESTS PASSED")
