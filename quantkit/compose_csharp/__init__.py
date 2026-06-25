"""把因子 plugin 的 ``FACTOR_SECTIONS`` C# 片段拼成一个完整 Lean 策略类。

口径来源：``quantai-service/strategy_composer``（回测服务端的拼接器）。本包**逐字
vendored** 其拼接逻辑（``rewriter`` + 渲染 + 模板的因子逻辑半边），以保证实盘策略
与回测**同口径**；同时去掉了 service 侧的 S3/EFS/job_id 依赖（quant-package 走
content 模式，plugin 直接来自 :mod:`quantkit.plugins`）。

两个渲染目标：

* :func:`render_backtest_strategy` —— 复刻回测服务端那份 ``FactorCsvBar`` 自定义
  数据 + ``AddData`` 的策略，用于**和回测对账**（同输入应产出同款 C#）。
* :func:`render_live_strategy` —— 实盘 ``binance_direct`` 专用：``AddCryptoFuture``
  下真实合约 + 实时 ``TradeBar`` OHLCV + ``market_features`` 特征流合并，复用同一套
  ``FactorState`` 因子逻辑与 ``Rebalance`` 调仓数学。

细节见 ``reference/lean_live_composer.md``。
"""
from __future__ import annotations

from .renderer import render_backtest_strategy, render_live_strategy
from .spec import Ranking, StrategySpec, Weighting

__all__ = [
    "render_backtest_strategy",
    "render_live_strategy",
    "StrategySpec",
    "Weighting",
    "Ranking",
]
