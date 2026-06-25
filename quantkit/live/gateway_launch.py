"""实盘 ``binance_direct`` 启动胶水：渲染 live C# 策略 → 拼 Lean env → 起 paper-runner。

与现有 :mod:`quantkit.live.main`（Python 直连币安）不同，这条路把执行交给
exchange-gateway 的 Lean ``binance_direct`` 通道：

1. :func:`quantkit.compose_csharp.render_live_strategy` 把因子组合渲染成一个
   Lean C# 策略类（与回测同口径的 composite + 调仓）。
2. 写成 ``<workdir>/<ClassName>.cs``。
3. 按 runbook（``docs/runbooks/paper-live-execution.md``）拼好
   ``LEAN_EXECUTION_PROFILE=binance_direct`` 等环境变量。
4. 调 ``uv run --project <gateway>/services/paper-runner python -m paper_runner``。

本模块**只编排**，不持有任何密钥：币安凭证仍由 ``BINANCE_API_KEY`` /
``BINANCE_API_SECRET`` 环境变量提供，传给 Lean 的只是**变量名**。要真正下单需本机已
装好 Lean + paper-runner + gateway lean 插件（含 ``QuantConnect.BinanceBrokerage.dll``），
路径通过下列环境变量指向：

* ``EXCHANGE_GATEWAY_REPO``     —— exchange-gateway 仓库根（含 services/paper-runner）
* ``LEAN_ROOT`` / ``LEAN_PLUGIN_DIR`` —— Lean 运行时与插件目录
* ``EXCHANGE_GATEWAY_AGGTRADE_KLINE_URL`` —— 8778 行情（默认 127.0.0.1:8778）

默认 ``dry-run=true``（策略侧 GetParameter）→ 只计算并打印目标权重，不下单。
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

from ..compose_csharp import StrategySpec, render_live_strategy
from ..plugins import FactorPlugin


@dataclass
class GatewayLaunchConfig:
    """binance_direct 启动所需的环境（路径 + profile）。凭证只传变量名。"""

    instance_id: str
    gateway_repo: Path
    lean_root: Path
    lean_plugin_dir: Path
    aggtrade_kline_url: str = "127.0.0.1:8778"
    exchange: str = "binance-usdm"
    security_model: str = "binance_crypto_future"
    binance_api_key_env: str = "BINANCE_API_KEY"
    binance_api_secret_env: str = "BINANCE_API_SECRET"
    # 主网默认；testnet 必须显式覆盖这两个 URL（见 runbook）。
    binance_fapi_url: str = "https://fapi.binance.com"
    binance_fws_url: str = "wss://fstream.binance.com/ws"
    extra_env: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, instance_id: str, env: Optional[Mapping[str, str]] = None) -> "GatewayLaunchConfig":
        env = env or os.environ
        repo = env.get("EXCHANGE_GATEWAY_REPO")
        if not repo:
            raise ValueError("EXCHANGE_GATEWAY_REPO 未设置（指向 exchange-gateway 仓库根）")
        lean_root = Path(env.get("LEAN_ROOT", str(Path(repo) / "lean")))
        return cls(
            instance_id=instance_id,
            gateway_repo=Path(repo),
            lean_root=lean_root,
            lean_plugin_dir=Path(env.get("LEAN_PLUGIN_DIR", str(lean_root / "plugins"))),
            aggtrade_kline_url=env.get("EXCHANGE_GATEWAY_AGGTRADE_KLINE_URL", "127.0.0.1:8778"),
            binance_fapi_url=env.get("BINANCE_FAPI_URL", "https://fapi.binance.com"),
            binance_fws_url=env.get("BINANCE_FWEBSOCKET_URL", "wss://fstream.binance.com/ws"),
        )

    @property
    def paper_runner_project(self) -> Path:
        return self.gateway_repo / "services" / "paper-runner"


def write_live_strategy(
    plugins: Sequence[FactorPlugin],
    spec: StrategySpec,
    symbols: Sequence[str],
    out_dir: Path,
    *,
    subscribe_features: bool = True,
    bar_size: str = "1d",
) -> tuple[Path, str]:
    """渲染 live C# 策略并写到 ``out_dir/<ClassName>.cs``，返回 (路径, 类名)。"""
    source, class_name = render_live_strategy(
        plugins, spec, symbols, subscribe_features=subscribe_features, bar_size=bar_size
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{class_name}.cs"
    path.write_text(source, encoding="utf-8")
    return path, class_name


def build_env(
    cfg: GatewayLaunchConfig,
    class_name: str,
    strategy_source_path: Path,
    *,
    dry_run: bool = True,
    strategy_parameters: Optional[Mapping[str, str]] = None,
    base_env: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """拼 binance_direct 的 Lean 启动环境变量（不含密钥值，只含变量名）。"""
    env = dict(base_env if base_env is not None else os.environ)
    params = {"dry-run": "true" if dry_run else "false"}
    if strategy_parameters:
        params.update({k: str(v) for k, v in strategy_parameters.items()})
    env.update(
        {
            "INSTANCE_ID": cfg.instance_id,
            "LEAN_EXECUTION_PROFILE": "binance_direct",
            "LEAN_STRATEGY_CLASS_NAME": class_name,
            "LEAN_STRATEGY_SOURCE_PATH": str(strategy_source_path),
            "LEAN_ROOT": str(cfg.lean_root),
            "LEAN_PLUGIN_DIR": str(cfg.lean_plugin_dir),
            "EXCHANGE_GATEWAY_EXCHANGE": cfg.exchange,
            "EXCHANGE_GATEWAY_SECURITY_MODEL": cfg.security_model,
            "EXCHANGE_GATEWAY_BINANCE_API_KEY_ENV": cfg.binance_api_key_env,
            "EXCHANGE_GATEWAY_BINANCE_API_SECRET_ENV": cfg.binance_api_secret_env,
            "EXCHANGE_GATEWAY_AGGTRADE_KLINE_URL": cfg.aggtrade_kline_url,
            "BINANCE_FAPI_URL": cfg.binance_fapi_url,
            "BINANCE_FWEBSOCKET_URL": cfg.binance_fws_url,
            "LEAN_STRATEGY_PARAMETERS_JSON": json.dumps(params),
        }
    )
    env.update({k: str(v) for k, v in cfg.extra_env.items()})
    return env


def paper_runner_command(cfg: GatewayLaunchConfig) -> list[str]:
    """启动 paper-runner 的命令（uv 入口，见 runbook）。"""
    return ["uv", "run", "--project", str(cfg.paper_runner_project), "python", "-m", "paper_runner"]


def launch(
    plugins: Sequence[FactorPlugin],
    spec: StrategySpec,
    symbols: Sequence[str],
    cfg: GatewayLaunchConfig,
    *,
    workdir: Path,
    subscribe_features: bool = True,
    bar_size: str = "1d",
    dry_run: bool = True,
    strategy_parameters: Optional[Mapping[str, str]] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """端到端：渲染策略 → 拼 env → 起 paper-runner（前台阻塞运行）。

    凭证预检：``dry_run=False`` 时要求 ``cfg.binance_api_key_env`` /
    ``binance_api_secret_env`` 指向的环境变量已设置，否则直接报错（不触网）。
    """
    src_path, class_name = write_live_strategy(
        plugins, spec, symbols, workdir, subscribe_features=subscribe_features, bar_size=bar_size
    )
    if not dry_run:
        for name in (cfg.binance_api_key_env, cfg.binance_api_secret_env):
            if not os.environ.get(name):
                raise RuntimeError(f"dry_run=False 但环境变量 {name} 未设置（拒绝在无凭证下尝试真实下单）")
    env = build_env(cfg, class_name, src_path, dry_run=dry_run, strategy_parameters=strategy_parameters)
    cmd = paper_runner_command(cfg)
    return subprocess.run(cmd, cwd=str(cfg.gateway_repo), env=env, check=check)
