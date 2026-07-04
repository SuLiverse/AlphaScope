"""外部进程引擎 adapters 测试 / §9.6-9.13.

覆盖:
1. 全部 8 个引擎注册成功 + 自动发现
2. 元数据: mode=external_process + code_copy_allowed=False (许可证防火墙)
3. 边界: 全部 allow_live_order=False
4. 健康检查: 三态 (HEALTHY/UNAVAILABLE), 不抛
5. run_backtest 骨架: 返回 research_only=True 的空结果, 不抛
6. 许可证分级正确: GPL/LGPL → copyleft_risk + 外部进程; MIT/Apache → safe

合规: 测试只校验 adapter 注册与边界, 不调用任何实盘下单。
"""

from __future__ import annotations

from backend.integrations.backtest.external_process_adapter import (
    _EXTERNAL_ENGINES,
    list_external_engines,
)
from backend.integrations.registry import get_registry
from backend.integrations.schemas import HealthStatus, IntegrationMode, LicenseSafety


EXPECTED_ENGINES = {
    "lean",
    "nautilus",
    "hftbacktest",
    "freqtrade",
    "jesse",
    "vnpy",
    "quantaxis",
    "stocksharp",
}


# ============================================================
# 1. 注册与自动发现
# ============================================================


def test_all_8_engines_registered():
    """8 个外部引擎应全部在 _EXTERNAL_ENGINES 规格里。"""
    names = {e["name"] for e in _EXTERNAL_ENGINES}
    assert EXPECTED_ENGINES.issubset(names)


def test_list_external_engines_returns_all():
    out = set(list_external_engines())
    assert EXPECTED_ENGINES.issubset(out)


def test_external_engines_registered_in_singleton():
    """外部引擎在模块 import 时自注册到 registry 单例 (参数化注册, 非 autodiscover)。"""
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        assert reg.has(name), f"未在单例中发现 {name}"


# ============================================================
# 2. 元数据 + 边界 (全部 adapter)
# ============================================================


def test_all_external_mode_and_no_live_order():
    """全部外部引擎: mode=EXTERNAL_PROCESS + allow_live_order=False + code_copy=False。"""
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        m = reg.get(name).metadata()
        assert m.mode == IntegrationMode.EXTERNAL_PROCESS, f"{name} mode 错"
        assert m.allow_live_order is False, f"{name} live 错"
        # 外部进程模式: code_copy 恒 False (许可证防火墙)
        assert m.code_copy_allowed is False, f"{name} code_copy 错"


def test_license_classification_correct():
    """GPL/LGPL → copyleft_risk; MIT/Apache → safe。"""
    reg = get_registry()
    expected = {
        "lean": LicenseSafety.SAFE,  # Apache
        "nautilus": LicenseSafety.COPILEFT_RISK,  # LGPL
        "hftbacktest": LicenseSafety.SAFE,  # MIT
        "freqtrade": LicenseSafety.COPILEFT_RISK,  # GPL
        "jesse": LicenseSafety.SAFE,  # MIT
        "vnpy": LicenseSafety.COPILEFT_RISK,  # LGPL
        "quantaxis": LicenseSafety.SAFE,  # MIT
        "stocksharp": LicenseSafety.SAFE,  # Apache
    }
    for name, safety in expected.items():
        m = reg.get(name).metadata()
        assert m.license_safety == safety, f"{name} license_safety 应是 {safety}, 实际 {m.license_safety}"


def test_no_live_capabilities_exposed():
    """外部引擎不暴露任何 live trading 能力 (即使引擎本身支持)。"""
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        m = reg.get(name).metadata()
        for cap in m.capabilities:
            low = cap.name.lower()
            for tok in (
                "submit_order",
                "place_order",
                "live",
                "connect_broker",
                "auto_trade",
            ):
                assert tok not in low, f"{name} 能力 {cap.name} 含禁止 token {tok}"


# ============================================================
# 3. 健康检查 (三态, 不抛)
# ============================================================


def test_healthcheck_returns_valid_status():
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        h = reg.get(name).healthcheck()
        assert h.status in (
            HealthStatus.HEALTHY,
            HealthStatus.UNAVAILABLE,
            HealthStatus.DEGRADED,
        ), f"{name} health 状态异常"
        assert h.message  # 必须有说明文字


def test_healthcheck_message_includes_install_hint():
    """UNAVAILABLE 时 message 应含安装指引 (docker/路径)。"""
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        h = reg.get(name).healthcheck()
        if h.status == HealthStatus.UNAVAILABLE:
            assert "docker" in h.message.lower() or "pip install" in h.message.lower() or "外部进程" in h.message


# ============================================================
# 4. run_backtest 骨架 (失败安全)
# ============================================================


def test_run_backtest_returns_research_only_empty_result():
    """骨架 run_backtest 应返回 research_only=True 的空结果, 不抛。"""
    reg = get_registry()
    for name in EXPECTED_ENGINES:
        res = reg.get(name).run_backtest("s1", ["X"], "2024-01-01", "2024-06-30")
        assert res.engine_name == name
        assert res.research_only is True
        assert res.assumptions.engine_name == name
        # 假设卡应标注命令白名单 + 严禁 live trading
        assert "严禁" in (res.assumptions.note or "") or "live" in (res.assumptions.note or "").lower()


def test_run_backtest_assumptions_mention_external_process():
    """假设卡应标注数据来自外部进程。"""
    reg = get_registry()
    res = reg.get("lean").run_backtest("s", ["X"], "2024-01-01", "2024-06-30")
    assert "外部进程" in (res.assumptions.note or "") or "外部进程" in (res.assumptions.data_source or "")


# ============================================================
# 5. allowed_commands 白名单 (规划 §13.1 Mode C 安全)
# ============================================================


def test_allowed_commands_only_backtest_class():
    """每个引擎的 allowed_commands 只含 backtest/research 类, 不含 live/trade。"""
    for spec in _EXTERNAL_ENGINES:
        cmds = spec["allowed_commands"]
        for c in cmds:
            low = c.lower()
            for forbidden in ("live", "trade", "order", "broker", "execute"):
                assert forbidden not in low, f"{spec['name']} 命令 {c} 含禁止 token"


def test_freqtrade_allowed_commands_excludes_live():
    """Freqtrade 明确排除 live/dry-run-trade, 只留 backtesting/hyperopt/dry-run。"""
    spec = next(e for e in _EXTERNAL_ENGINES if e["name"] == "freqtrade")
    cmds = set(spec["allowed_commands"])
    assert "backtesting" in cmds
    assert "live" not in cmds
    # dry-run 是研究模式 (不接真实密钥), 允许
    assert "dry-run" in cmds
