"""risk_controller 测试 — check_stop_loss 除零防护 + 触发逻辑。

锁住 entry_price<=0 不崩(返回 invalid_entry_price)+ 正常亏损触发 + 未触发。
"""

from __future__ import annotations

from backend.quant.risk_controller import RiskController


def test_check_stop_loss_zero_entry_price_no_crash():
    """entry_price=0(分红除权/split bug 致数据异常)不应 ZeroDivisionError, 返回数据异常结果。"""
    rc = RiskController()
    result = rc.check_stop_loss("600519", entry_price=0, current_price=100)
    assert result.allowed is False
    assert result.rule == "invalid_entry_price"
    assert "异常" in result.reason


def test_check_stop_loss_negative_entry_price():
    """entry_price 负数同样防护。"""
    rc = RiskController()
    result = rc.check_stop_loss("600519", entry_price=-5, current_price=100)
    assert result.allowed is False
    assert result.rule == "invalid_entry_price"


def test_check_stop_loss_triggers_on_big_loss():
    """亏损超阈值(默认 -10%)触发止损。"""
    rc = RiskController()  # stop_loss_pct=-10
    # entry=100, current=85 → pnl=-15% < -10% → 触发
    result = rc.check_stop_loss("600519", entry_price=100, current_price=85)
    assert result.allowed is False
    assert result.rule == "stop_loss"


def test_check_stop_loss_passes_within_threshold():
    """亏损未超阈值不触发。"""
    rc = RiskController()
    # entry=100, current=95 → pnl=-5% > -10% → 通过
    result = rc.check_stop_loss("600519", entry_price=100, current_price=95)
    assert result.allowed is True
