"""No-Live-Order 边界测试 (Phase 0).

把「AlphaScope 不连接真实券商、不自动下单」从 README 文字变成可执行断言。
任何 PR 若引入实盘下单能力, 本测试会立刻失败。

覆盖三道防线:
1. 配置防线: legal_boundaries.yaml 的 live/auto 标志必须全 False。
2. 不变量防线: TradingBoundary 启动期断言通过, live_order_blocked == True。
3. 源码防线: backend/ 下不得把 submit_order/place_order/execute_trade/
   auto_trade/live_gateway 定义为函数/类/方法名。

Phase 1 Integration Registry 落地后, 这里还会追加第 4 道:
   所有注册集成都不得 advertise live-order capability。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.security.trading_boundary import (
    FORBIDDEN_SYMBOL_NAMES,
    BoundaryViolation,
    TradingBoundary,
    describe_capabilities,
    get_boundary,
    scan_forbidden_symbols,
)


# ----------------------------- 1. 配置防线 -----------------------------


_MUST_BE_FALSE = (
    "allow_live_broker_order",
    "allow_llm_direct_order",
    "allow_auto_execution",
    "allow_real_api_secret_for_trading",
)


def test_live_order_flags_are_false() -> None:
    """所有 live/auto 下单标志必须为 False。"""
    b = get_boundary()
    for flag in _MUST_BE_FALSE:
        assert b.flags.get(flag) is False, f"交易边界违规: {flag} 必须为 False (当前 {b.flags.get(flag)!r})"


def test_allowed_capabilities_remain_true() -> None:
    """研究/回测/纸面/确认单能力不受影响。"""
    b = get_boundary()
    assert b.is_allowed("allow_paper_trading") is True
    assert b.is_allowed("allow_backtest") is True
    assert b.is_allowed("allow_manual_ticket_export") is True


# ----------------------------- 2. 不变量防线 -----------------------------


def test_boundary_passes_startup_invariant() -> None:
    """启动期不变量校验通过。"""
    b = get_boundary()
    b.assert_invariant()  # 不抛即通过
    assert b.live_order_blocked is True


def test_invariant_detects_violation() -> None:
    """若有人把 live 标志改 True, assert_invariant 必须立刻抛错。"""
    bad = TradingBoundary(flags={**get_boundary().flags, "allow_live_broker_order": True})
    with pytest.raises(BoundaryViolation):
        bad.assert_invariant()


def test_assert_no_live_order_guard_is_safe_to_call() -> None:
    """运行期守卫可安全调用 (代表「这条路径自证不是 live order」)。"""
    get_boundary().assert_no_live_order("paper_broker.fill")


# ----------------------------- 3. 源码防线 -----------------------------


def test_no_forbidden_symbol_definitions_in_backend() -> None:
    """backend/ 源码不得定义 submit_order/place_order/... 等实盘下单符号名。"""
    findings = scan_forbidden_symbols()
    if findings:
        lines = [
            f"  {p.relative_to(Path.cwd()) if Path.cwd() in p.parents else p}:{name}:{ln}" for p, name, ln in findings
        ]
        pytest.fail(
            "发现禁止的实盘下单符号定义 (应改用 create_paper_order / create_research_ticket 等研究语义):\n"
            + "\n".join(lines)
        )


def test_forbidden_symbol_names_nonempty() -> None:
    """禁止词表不能被意外清空。"""
    assert len(FORBIDDEN_SYMBOL_NAMES) >= 5
    assert "submit_order" in FORBIDDEN_SYMBOL_NAMES
    assert "place_order" in FORBIDDEN_SYMBOL_NAMES


def test_scan_detects_forbidden_definition(tmp_backend: Path) -> None:
    findings = scan_forbidden_symbols(root=tmp_backend)
    assert len(findings) == 1
    _, name, _ = findings[0]
    assert name == "submit_order"


@pytest.fixture
def tmp_backend(tmp_path: Path) -> Path:
    """构造一个临时 backend 目录, 内含一个禁止定义, 验证扫描器识别。"""
    pkg = tmp_path / "backend"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "evil.py").write_text(
        "def submit_order(symbol, qty):\n    return ('LIVE', symbol, qty)\n",
        encoding="utf-8",
    )
    return tmp_path


# ----------------------------- 4. (Phase 1 占位) -----------------------------


def test_describe_capabilities_exposes_boundary_for_ui() -> None:
    """describe_capabilities() 供 UI「安全边界」面板, 且 live_order_blocked=True。"""
    info = describe_capabilities()
    assert info["live_order_blocked"] is True
    assert "allow_live_broker_order" in info["flags"]
    assert info["flags"]["allow_live_broker_order"] is False
    assert "forbidden_symbol_names" in info
