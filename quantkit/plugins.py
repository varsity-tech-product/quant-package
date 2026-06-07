"""因子 plugin 加载与字段自省。

每个因子 plugin 是一个 ``.py`` 文件，统一导出：

* ``FACTOR_TYPE``           — 因子名 (str)
* ``FACTOR_DEFAULT_PARAMS`` — 默认参数 (dict)
* ``FACTOR_SECTIONS``       — 给回测引擎渲染 C# 的占位符片段 (dict)
* ``build_signal(close, params, <若干具名 DataFrame>, **_kwargs) -> DataFrame``
      —— Python 版信号计算，输入/输出都是 ``[date x symbol]`` 面板

实盘路径需要在本地跑 ``build_signal``，所以必须知道每个 plugin 要哪些数据字段。
不同 plugin 字段不同（如 carry 因子要 funding/open_interest/大户多空比），
因此用 :func:`required_fields` 从函数签名自动推断，而不是写死。
"""
from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# build_signal 的前两个参数是固定的，不算数据字段。
_FIXED_PARAMS = {"close", "params"}


@dataclass
class FactorPlugin:
    """已加载的因子 plugin 句柄。"""

    factor_type: str
    default_params: dict[str, Any]
    sections: dict[str, str]
    build_signal: Callable[..., Any]
    source_path: Path

    @property
    def required_fields(self) -> list[str]:
        # build_signal 需要的数据字段（除 close/params 外的具名参数）。
        """build_signal 需要的数据字段（除 close/params 外的具名参数）。

        例：flow_confirmed_smooth_trend_momentum ->
            ['volume', 'taker_buy_volume', 'taker_sell_volume']
        这些名字与数据服务 market_features 35 列 schema 的列名一一对应。
        """
        return required_fields(self.build_signal)


def required_fields(build_signal: Callable[..., Any]) -> list[str]:
    # 从 ``build_signal`` 签名推断需要的数据字段名。
    """从 ``build_signal`` 签名推断需要的数据字段名。

    跳过 ``close`` / ``params`` 这两个固定参数，以及 ``**kwargs`` 之类的可变参数。
    始终隐含需要 ``close``（价格），调用方自行保证。
    """
    sig = inspect.signature(build_signal)
    fields: list[str] = []
    for name, param in sig.parameters.items():
        if name in _FIXED_PARAMS:
            continue
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        fields.append(name)
    return fields


def load_plugin(path: str | Path) -> FactorPlugin:
    """从文件路径加载一个因子 plugin。

    Args:
        path: plugin ``.py`` 文件路径。可以是用户自己路径下的因子
              （如 ``/mnt/efs-b/quant-factor-loop/.quant/<job>/step4/x.py``），
              也可以是 ``example_plugin/`` 里的样例。
    """
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"plugin not found: {path}")

    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import plugin: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    missing = [a for a in ("FACTOR_TYPE", "build_signal") if not hasattr(module, a)]
    if missing:
        raise AttributeError(f"plugin {path.name} missing attrs: {missing}")

    return FactorPlugin(
        factor_type=getattr(module, "FACTOR_TYPE"),
        default_params=dict(getattr(module, "FACTOR_DEFAULT_PARAMS", {})),
        sections=dict(getattr(module, "FACTOR_SECTIONS", {})),
        build_signal=getattr(module, "build_signal"),
        source_path=path,
    )


def all_required_fields(plugins: list[FactorPlugin]) -> set[str]:
    """一组 plugin 合并后需要的全部数据字段（含隐含的 close）。"""
    fields: set[str] = {"close"}
    for p in plugins:
        fields.update(p.required_fields)
    return fields
