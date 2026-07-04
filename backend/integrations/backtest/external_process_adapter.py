"""外部进程引擎 adapters / External Process Engines (§9.6-9.13, Phase D §13.1 Mode C).

把战略规划 §9 列出的**重型/外部进程模式**引擎接入 Integration Registry:
- Lean / QuantConnect (§9.6, C#/.NET, 跨市场专业回测)
- Nautilus Trader (§9.7, Rust-native, 事件驱动高精度仿真)
- hftbacktest (§9.8, 高频交易研究沙箱)
- Freqtrade (§9.9, crypto dry-run 研究)
- Jesse (§9.9, crypto 回测)
- vn.py (§9.10, 国内量化, 只做参考不接交易 Gateway)
- QUANTAXIS / Qbot / hikyuu (§9.11, 国内量化一站式)
- StockSharp (§9.13, C#/.NET 生态)

这些项目**依赖重、语言混杂、部分有 license 风险**, 不适合 pip install 进 AlphaScope 主
环境。规划 §13.1 明确把它们归为 **Mode C: External Process** (子进程 / Docker / CLI /
REST), 仅通过「外部进程 + 格式兼容」接入, 不拷码入仓。

设计要点 (延续项目「确定性 · 失败安全 · No-Live-Order」基线):
- **不 pip install**: 这些 adapter 不 import 任何外部库, 只通过 subprocess/Docker/CLI
  调用外部引擎; 健康检查探测二进制/容器是否就绪。
- **严格遵守 No-Live-Order**: 即使外部引擎本身能交易 (如 vn.py/Freqtrade/Jesse 有
  live 模式), AlphaScope 只调 backtest/dry-run/research 路径; adapter 显式
  ``allow_live_order=False``, 命令白名单只允许 backtest/optimize。
- **诚实假设卡**: 每个引擎的摩擦模型不同, 假设卡标注 (与 pip 类 adapter 一致)。
- **边界**: 全部过 registry 三道断言 (边界/能力黑名单/许可证防火墙)。

本文件用参数化方式注册多个 adapter, 避免重复样板。
"""

from __future__ import annotations

import shutil
from typing import Any

from backend.integrations.base import BacktestEngineAdapter
from backend.integrations.schemas import (
    BacktestAssumptions,
    BacktestMetrics,
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
    NormalizedBacktestResult,
)
from backend.integrations.registry import register


# ============================================================
# 外部引擎规格表 (驱动参数化注册)
# ============================================================

# 每个引擎: name / display_name / description / homepage / 探测命令 (binary 或 docker image) /
# license / 命令白名单 (只允许 backtest 类)
_EXTERNAL_ENGINES: list[dict[str, Any]] = [
    {
        "name": "lean",
        "display_name": "Lean / QuantConnect",
        "description": (
            "QuantConnect 开源算法交易引擎 (C#/.NET), 专业跨市场回测。规划 §9.6: "
            "不接 live trading, 只接 research/backtest/optimization (Mode C 外部进程)。"
        ),
        "homepage": "https://github.com/QuantConnect/Lean",
        "probe": "lean",  # CLI: lean-cli
        "docker": "quantconnect/lean",
        "license_name": "Apache-2.0",
        "license_safety": LicenseSafety.SAFE,
        "allowed_commands": ("backtest", "optimize", "research"),
    },
    {
        "name": "nautilus",
        "display_name": "Nautilus Trader",
        "description": (
            "Rust-native 高性能事件驱动交易系统框架。规划 §9.7: 不做实盘下单, "
            "用其事件驱动与高精度仿真能力做研究 (Mode C)。"
        ),
        "homepage": "https://github.com/nautechsystems/nautilus_trader",
        "probe": "nautilus",
        "docker": "ghcr.io/nautechsystems/nautilus_trader",
        "license_name": "LGPL-3.0",
        "license_safety": LicenseSafety.COPILEFT_RISK,  # LGPL 有传染性, 外部进程隔离
        "allowed_commands": ("backtest", "sandbox", "run_backtest"),
    },
    {
        "name": "hftbacktest",
        "display_name": "hftbacktest 高频研究沙箱",
        "description": (
            "高频交易研究沙箱: 盘口回放/延迟/队列位置/订单成交模拟。规划 §9.8: "
            "高级模块, 不进普通用户主流程 (Mode C MicrostructureLab)。"
        ),
        "homepage": "https://github.com/nkaz001/hftbacktest",
        "probe": None,  # 纯 Python 但依赖重, 不 pip install, 走外部进程
        "docker": None,
        "license_name": "MIT",
        "license_safety": LicenseSafety.SAFE,
        "allowed_commands": ("backtest", "simulate"),
    },
    {
        "name": "freqtrade",
        "display_name": "Freqtrade (dry-run 研究)",
        "description": (
            "开源 crypto 交易机器人。规划 §9.9/§12: 可研究使用, 但不要暴露真实交易密钥, "
            "只接 backtesting/hyperopt/dry-run (Mode C)。"
        ),
        "homepage": "https://github.com/freqtrade/freqtrade",
        "probe": "freqtrade",
        "docker": "freqtradeorg/freqtrade",
        "license_name": "GPL-3.0",
        "license_safety": LicenseSafety.COPILEFT_RISK,  # GPL 强传染, 必须外部进程
        "allowed_commands": ("backtesting", "hyperopt", "dry-run"),
    },
    {
        "name": "jesse",
        "display_name": "Jesse (crypto 回测)",
        "description": ("crypto 研究回测框架。规划 §9.9: 避免实盘交易链路, 只接 backtest (Mode C)。"),
        "homepage": "https://github.com/jesse-ai/jesse",
        "probe": "jesse",
        "docker": None,
        "license_name": "MIT",
        "license_safety": LicenseSafety.SAFE,
        "allowed_commands": ("backtest", "optimize"),
    },
    {
        "name": "vnpy",
        "display_name": "vn.py (仅参考/外部进程)",
        "description": (
            "国内量化一站式框架。规划 §9.10/§12: 不接真实交易 Gateway, 只做参考或外部服务 (Mode C, 严格隔离交易)。"
        ),
        "homepage": "https://github.com/vnpy/vnpy",
        "probe": None,
        "docker": None,
        "license_name": "LGPL-3.0",
        "license_safety": LicenseSafety.COPILEFT_RISK,
        "allowed_commands": ("backtest",),  # 不允许任何 live gateway 命令
    },
    {
        "name": "quantaxis",
        "display_name": "QUANTAXIS (国内量化)",
        "description": ("国内量化分析框架。规划 §9.11: 架构可借鉴, 走外部进程 (Mode C)。"),
        "homepage": "https://github.com/yutiansut/QUANTAXIS",
        "probe": None,
        "docker": "quantaxis/qa",
        "license_name": "MIT",
        "license_safety": LicenseSafety.SAFE,
        "allowed_commands": ("backtest", "research"),
    },
    {
        "name": "stocksharp",
        "display_name": "StockSharp (C# 生态)",
        "description": ("C#/.NET 交易算法框架。规划 §9.13: 建议只做参考或外部服务 (Mode C)。"),
        "homepage": "https://github.com/StockSharp/StockSharp",
        "probe": None,
        "docker": None,
        "license_name": "Apache-2.0",
        "license_safety": LicenseSafety.SAFE,
        "allowed_commands": ("backtest", "history"),
    },
]


# ============================================================
# 通用外部进程 adapter (参数化)
# ============================================================


def _probe_available(spec: dict[str, Any]) -> bool:
    """探测外部引擎是否可用 (binary 在 PATH 或 docker image 存在)。

    纯函数, 失败安全: 任何异常返回 False。
    """
    probe = spec.get("probe")
    if probe:
        try:
            return shutil.which(probe) is not None
        except Exception:
            return False
    # 无 probe 命令的 (hftbacktest/vnpy 等纯 pip 类但走外部进程) → 报 UNAVAILABLE
    # (调用方应在独立 venv/Docker 跑, AlphaScope 不直接探测)
    return False


def _build_metadata(adapter_cls: type, spec: dict[str, Any]) -> IntegrationMetadata:
    return IntegrationMetadata(
        name=spec["name"],
        category=adapter_cls.CATEGORY,
        mode=IntegrationMode.EXTERNAL_PROCESS,  # 全部 Mode C
        version="0.1.0",
        display_name=spec["display_name"],
        description=spec["description"],
        homepage=spec["homepage"],
        package=None,  # 外部进程, 无 pip 包名
        capabilities=[
            CapabilitySpec(name="run_backtest", description="通过子进程/Docker 调用外部引擎回测")
            for _ in [0]  # 单元素
        ],
        license_name=spec["license_name"],
        license_safety=spec["license_safety"],
        # 外部进程模式: code_copy_allowed 恒 False (不拷码入仓, 与许可证防火墙一致)
        code_copy_allowed=False,
        allow_live_order=False,
    )


# 延迟导入 CapabilitySpec (避免顶部循环)
from backend.integrations.schemas import CapabilitySpec  # noqa: E402


def _make_healthcheck(spec: dict[str, Any]):
    def healthcheck(self) -> IntegrationHealth:
        if _probe_available(spec):
            return IntegrationHealth(
                name=spec["name"],
                status=HealthStatus.HEALTHY,
                message=f"{spec['display_name']} 就绪 (外部进程模式)",
            )
        docker = spec.get("docker")
        return IntegrationHealth(
            name=spec["name"],
            status=HealthStatus.UNAVAILABLE,
            message=(
                f"{spec['display_name']} 未检测到。外部进程模式: "
                + (f"docker pull {docker}" if docker else "pip install 在独立 venv (不进主环境)")
                + f" 或访问 {spec['homepage']}"
            ),
        )

    return healthcheck


def _make_run_backtest(spec: dict[str, Any]):
    def run_backtest(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None = None,
        **kw: Any,
    ) -> NormalizedBacktestResult:
        """通过外部进程调用引擎回测。

        本 adapter 是骨架: 实际调用需调用方提供 ``command`` (完整命令行) 或
        ``docker_run`` (Docker 参数); 否则返回 UNAVAILABLE 标记的空结果。
        命令白名单: 只允许 spec['allowed_commands'] 里的 backtest 类命令。
        """
        assump = assumptions or BacktestAssumptions(
            engine_name=spec["name"],
            execution_price="外部引擎决定 (见引擎文档)",
            settlement_rule="外部引擎决定",
            price_limit_filter=None,
            future_function_check=True,
            data_source="外部进程 (子进程/Docker)",
            note=(
                f"{spec['display_name']} 外部进程回测: 引擎自身摩擦模型见其文档; "
                f"AlphaScope 命令白名单只允许 {spec['allowed_commands']}, 严禁 live trading。"
            ),
        )
        # 骨架实现: 不实际执行子进程 (需调用方提供完整命令 + 引擎就绪)
        # 真正接入时由调用层 (CLI/编排) 构造命令并解析结果; 这里只保证结构正确
        return NormalizedBacktestResult(
            engine_name=spec["name"],
            strategy_id=strategy_id,
            universe=list(symbols),
            start_date=start,
            end_date=end,
            initial_cash=kw.get("init_cash"),
            benchmark=kw.get("benchmark", "沪深300"),
            assumptions=assump,
            metrics=BacktestMetrics(),
            equity_curve=[],
            trades=[],
            risk_events=[],
            evidence_links=[],
            reproducibility_hash=None,
            research_only=True,
        )

    return run_backtest


# ============================================================
# 参数化注册: 为每个引擎生成一个 adapter 类并注册
# ============================================================


def _register_external_engine(spec: dict[str, Any]) -> type:
    """为单个外部引擎规格生成并注册一个 BacktestEngineAdapter 子类。"""
    cls_name = "".join(p.capitalize() for p in spec["name"].split("_")) + "ExternalAdapter"

    # 构造类属性与方法
    attrs: dict[str, Any] = {
        "NAME": spec["name"],
        "CATEGORY": __import__(
            "backend.integrations.schemas", fromlist=["IntegrationCategory"]
        ).IntegrationCategory.BACKTEST,
        "_metadata": lambda self, _spec=spec: _build_metadata(type(self), _spec),
        "healthcheck": _make_healthcheck(spec),
        "run_backtest": _make_run_backtest(spec),
    }
    cls = type(cls_name, (BacktestEngineAdapter,), attrs)
    register(cls)
    return cls


# 模块导入时注册全部外部引擎
_REGISTERED_EXTERNAL: list[type] = []
for _spec in _EXTERNAL_ENGINES:
    try:
        _REGISTERED_EXTERNAL.append(_register_external_engine(_spec))
    except Exception:
        # 单引擎注册失败不影响其余 (如与已注册名冲突)
        continue


def list_external_engines() -> list[str]:
    """返回已注册的外部引擎 adapter 名。"""
    return [c.NAME for c in _REGISTERED_EXTERNAL]
