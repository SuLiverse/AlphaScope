"""Qlib Adapter — AI 量化因子与机器学习引擎 (Phase 2 第三个真实 adapter).

Qlib (MIT, 微软出品) 是面向 AI 的量化投研平台, 强项是**系统化的因子库 (Alpha158 /
Alpha360) + ML 模型实验流程**。本 adapter 把它接入 AlphaScope 的 Integration Registry,
补齐自研 factor_registry(确定性技术因子)所不擅长的「机器学习因子 + 模型训练」能力
(对应战略规划「QlibAdapter」「FactorLab + Qlib 深度融合」, v2.5 蓝图核心)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``qlib`` 用 import-guard 包裹, 没装不影响其余功能
  (healthcheck 报 UNAVAILABLE)。安装并初始化数据后即生效。
- **不触网**: 因子计算所需的 OHLCV 由调用方通过 ``bars=`` 注入, 不抓数据、不下单。
- **失败安全**: qlib 不可用 / 数据未初始化 / 字段不匹配 → 返回空 + DEGRADED, 不抛。
- **归一化纯函数可单测**: ``normalize_qlib_factor_df`` 把 Qlib 输出的 dataframe
  (列名 = 因子, 行 = 日期) 归一化成 AlphaScope 因子向量结构 (与 factor_registry
  compute_for_symbol 同构), 不依赖 qlib 即可单测。
- **诚实标注口径**: Qlib Alpha158 因子的口径与自研确定性因子不同 (含 ML 衍生),
  在输出里标 ``source=qlib`` + disclaimer, 防混淆。

合规: 因子是对历史量价/ML 结构的度量, direction 仅为口径标注, 不据此给买卖指令、
不预测、不构成选股建议。
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: qlib 缺失时优雅降级 -----
try:
    import qlib  # type: ignore[import-untyped]  # noqa: F401

    _QLIB_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    qlib = None  # type: ignore[assignment]
    _QLIB_AVAILABLE = False

from backend.integrations.base import FactorAdapter
from backend.integrations.schemas import (
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
)
from backend.integrations.registry import register

# Alpha158 是 Qlib 最经典的因子集 (158 个), 这里只登记元信息, 实际计算由 qlib 完成。
# 不在 import 时列举全部 158 个名字, 避免与 qlib 版本耦合。
_DEFAULT_FACTOR_SET = "alpha158"


def _to_qlib_instrument(code: str) -> str:
    """把 AlphaScope 口径标的代码转成 Qlib 口径 (如 600000 → SH600000, 000001 → SZ000001)。

    Qlib CN 数据用 交易所前缀 + 6 位代码: 沪市 (60/68/90/11 开头) → SH, 深市 → SZ。
    纯函数, 失败安全: 已带前缀/非 6 位/空 → 原样返回 (交给 Qlib 自行解析或报错)。
    """
    if not code:
        return code
    s = str(code).strip().upper()
    if s.startswith(("SH", "SZ", "BJ")) and len(s) >= 8:
        return s  # 已是 Qlib 口径
    digits = s.lstrip("#")
    if len(digits) != 6 or not digits.isdigit():
        return s  # 非标准 6 位代码, 原样返回
    if digits[:2] in ("60", "68", "90", "11", "13", "56"):
        return "SH" + digits
    return "SZ" + digits


# ============================================================
# 纯函数 (无需 qlib 即可单测)
# ============================================================


def normalize_qlib_factor_df(df: Any, symbol: str, factor_set: str = _DEFAULT_FACTOR_SET) -> dict[str, Any]:
    """把 Qlib 输出的因子 dataframe 归一化成 AlphaScope 因子向量结构。

    Qlib 的典型输出: index = 日期(datetime), columns = 各因子名 (如 KBAR/OPEN0/...),
    values = 因子值。本函数取**最新一行**作为该标的的因子向量 (与 factor_registry
    compute_for_symbol 的 asof 口径一致), 失败安全返回空向量。

    输出形如:
        {"symbol": ..., "asof": ..., "factor_set": "alpha158",
         "factors": {factor_id: value, ...}, "source": "qlib", "disclaimer": ...}

    兼容 pandas DataFrame; 空 / None → 空 factors。
    """
    empty: dict[str, Any] = {
        "symbol": str(symbol),
        "asof": "",
        "factor_set": factor_set,
        "factors": {},
        "source": "qlib",
        "disclaimer": (
            "Qlib 因子(ml 衍生, source=qlib)与确定性技术因子口径不同, 仅为研究辅助, 不预测、不构成选股建议。"
        ),
    }
    if df is None:
        return empty
    # 取最新行
    try:
        if hasattr(df, "iloc") and len(df) > 0:
            last_row = df.iloc[-1]
            asof = str(df.index[-1])[:10] if len(df.index) else ""
            factors: dict[str, Any] = {}
            for col in df.columns:
                try:
                    val = float(last_row[col])
                    # 过滤 NaN/inf (Qlib 计算缺失会产 NaN)
                    if val == val and val not in (float("inf"), float("-inf")):
                        factors[str(col)] = val
                except (TypeError, ValueError):
                    continue
            return {**empty, "asof": asof, "factors": factors}
    except Exception:
        pass
    return empty


def has_qlib_data_initialized() -> bool:
    """探测 qlib 是否已初始化数据目录。

    qlib.init() 成功后, qlib.config.C.registered 会变 True (QlibConfig 单例的
    @property)。这是最干净的「是否已初始化」判断点 (init() 本身在
    skip_if_reg and C.registered 时早返回)。provider_uri 在 init 后会被
    resolve_path 规范化成 dict, 不可直接做字符串比较。
    """
    if not _QLIB_AVAILABLE:
        return False
    try:
        from qlib.config import C  # type: ignore[import-untyped]

        return bool(getattr(C, "registered", False))
    except Exception:
        return False


# ============================================================
# Adapter
# ============================================================


@register
class QlibAdapter(FactorAdapter):
    """Qlib AI 量化因子 adapter (Phase 2)。

    把 Qlib 的 Alpha158/Alpha360 因子集 + ML 因子能力接入 AlphaScope。所需 OHLCV
    由调用方注入 (``bars=``); qlib 不可用 / 数据未初始化时返回空, 不抛。
    """

    NAME = "qlib"
    # CATEGORY 继承自 FactorAdapter.FACTOR

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="Qlib AI 量化因子",
            description=(
                "微软出品的 AI 量化平台, 强项是 Alpha158/Alpha360 系统化因子库 + ML "
                "模型实验流程。补齐自研确定性因子所不擅长的机器学习因子能力。"
                "可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/microsoft/qlib",
            package="pyqlib",
            capabilities=[
                {
                    "name": "compute_factors",
                    "description": "用 Alpha158/Alpha360 算因子向量",
                },
            ],
            license_name="MIT",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _QLIB_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message="qlib 未安装。安装后生效: pip install pyqlib",
            )
        if not has_qlib_data_initialized():
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.DEGRADED,
                message=(
                    "qlib 已安装但数据目录未初始化。需先 qlib.init(provider_uri=...) "
                    "并下载日线数据 (python -m qlib.run.get_data)。"
                ),
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message="qlib 就绪 (Alpha158/Alpha360 因子库 + ML 实验流程)",
        )

    def compute_factors(self, symbols: list[str], **kw: Any) -> dict[str, Any]:
        """为给定标的计算 Qlib 因子向量。

        关键入参 (kw):
        - instruments: list[str]  Qlib 口径标的 (如 ["SH600000"]); 缺省回退 symbols
        - start_time / end_time: str  因子计算区间 (如 "2020-01-01")
        - factor_set: str   "alpha158"(默认) / "alpha360"

        返回 normalize_qlib_factor_df 归一化后的结构。
        失败安全: qlib 不可用 / 数据未初始化 / API 抛错 → 返回空因子向量, 不抛。
        本方法是 Qlib 相对自研 factor_registry 的差异化能力 (ML 衍生因子), 故单独实现。

        注意: 正确的 Qlib API 是 ``from qlib.contrib.data.handler import Alpha158``,
        handler 需要 instruments/start_time/end_time/fit_*_time, 取因子用
        ``h.fetch(col_set="feature")``。详见 Qlib data framework 文档。
        """
        instruments = kw.get("instruments") or [_to_qlib_instrument(s) for s in symbols if s]
        symbol = instruments[0] if instruments else str(kw.get("symbol", ""))
        factor_set = str(kw.get("factor_set", _DEFAULT_FACTOR_SET))
        start_time = str(kw.get("start_time", "2018-01-01"))
        end_time = str(kw.get("end_time", "2024-12-31"))
        if not _QLIB_AVAILABLE or not has_qlib_data_initialized() or not instruments:
            # 失败安全: 返回空因子向量 (结构与正常输出一致)
            return normalize_qlib_factor_df(None, symbol=symbol, factor_set=factor_set)
        try:
            # 延迟导入 qlib 的具体 API (避免模块导入时的副作用)。
            # 注意: Alpha158 在 qlib.contrib.data.handler (非 qlib.data.dataset.loader)。
            if factor_set == "alpha360":
                from qlib.contrib.data.handler import (  # type: ignore[import-untyped]
                    Alpha360 as _Handler,
                )
            else:
                from qlib.contrib.data.handler import (  # type: ignore[import-untyped]
                    Alpha158 as _Handler,
                )

            h = _Handler(
                instruments=instruments,
                start_time=start_time,
                end_time=end_time,
                fit_start_time=start_time,
                fit_end_time=end_time,
                # 仅取原始因子值, 关闭 DropnaLabel/CSZScoreNorm 等 learn 处理
                learn_processors=[],
            )
            df = h.fetch(col_set="feature")  # MultiIndex(datetime, instrument) × 158 列
            return normalize_qlib_factor_df(df, symbol=symbol, factor_set=factor_set)
        except Exception:
            return normalize_qlib_factor_df(None, symbol=symbol, factor_set=factor_set)
