"""交易日历 / Trading Calendar (Phase A #6).

把 ``exchange_calendars`` 接入 AlphaScope, 补齐回测/数据校验所需的「真实交易日」判断
(节假日/周末/特殊休市), 而不是仅靠 bar index 或周末启发式。对应战略规划 Phase A 第
6 项「exchange_calendars 交易日历」与 §2「数据质量与数据契约」。

设计要点 (延续项目「确定性 · 失败安全」基线):
- **可选依赖 + 优雅降级**: ``exchange_calendars`` 用 import-guard 包裹, 没装不影响其余
  功能 — 回落到「周末启发式」(周六周日非交易日, 节假日不识别, 并在结果里标注降级)。
- **纯函数**: 对外暴露 ``is_trading_day / trading_days / count_trading_days /
  next_trading_day / previous_trading_day``, 全部失败安全、可单测。
- **市场代码**: 默认 ``XSHG``(上交所, A 股); 也支持 ``XSHE``(深交所)、``XHKG``(港股)、
  ``NYSE``/``NASDAQ``(美股) 等 exchange_calendars 内置日历。
- **合规**: 本模块只描述交易日历结构, 不预测、不荐股、不构成投资建议。

A​PI 已对照 exchange_calendars 4.x 真实源码核对 (非臆测):
- ``xc.get_calendar(market)`` → calendar 对象
- ``cal.sessions_in_range(start, end)`` → DatetimeIndex (交易日)
- ``cal.is_session(ts)`` → bool
- ``cal.next_session(ts)`` / ``cal.previous_session(ts)`` → Timestamp
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# ----- 可选依赖: exchange_calendars 缺失时优雅降级 (周末启发式) -----
try:
    import exchange_calendars as xc  # type: ignore[import-untyped]
    import pandas as pd

    _XC_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    xc = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    _XC_AVAILABLE = False

# 默认市场 (A 股上交所); exchange_calendars 用 XSHG 标识
_DEFAULT_MARKET = "XSHG"

# 单例缓存: 同一市场只创建一次 calendar 对象 (exchange_calendars 初始化较重)
_CAL_CACHE: dict[str, Any] = {}


def _get_cal(market: str = _DEFAULT_MARKET) -> Any | None:
    """获取 (并缓存) exchange_calendars 的 calendar 对象; 失败返回 None。"""
    if not _XC_AVAILABLE:
        return None
    if market not in _CAL_CACHE:
        try:
            _CAL_CACHE[market] = xc.get_calendar(market)  # type: ignore[union-attr]
        except Exception:
            _CAL_CACHE[market] = None  # 未知市场代码 → 降级
    return _CAL_CACHE[market]


def _to_timestamp(d: str | date | datetime) -> Any:
    """把 str/date/datetime 转成 pandas.Timestamp (exchange_calendars 要求)。"""
    if pd is None:
        return d
    return pd.Timestamp(d)


def _to_date(d: str | date | datetime | Any) -> date:
    """把任意输入归一化成 datetime.date (输出统一)。"""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d[:10]).date()
        except ValueError:
            try:
                return date.fromisoformat(d[:10])
            except ValueError:
                return None  # type: ignore[return-value]
    # pandas.Timestamp
    try:
        return d.date()  # type: ignore[union-attr]
    except Exception:
        return None  # type: ignore[return-value]


# ============================================================
# 公开 API
# ============================================================


def is_available(market: str = _DEFAULT_MARKET) -> bool:
    """exchange_calendars 是否就绪 (装了且该市场日历可加载)。"""
    return _get_cal(market) is not None


def is_trading_day(d: str | date | datetime, market: str = _DEFAULT_MARKET) -> bool:
    """判断某日是否为指定市场的交易日。

    失败安全: exchange_calendars 不可用或日期非法时, 回落到「周末启发式」
    (周六/周日 → False, 其余 → True, **不识别节假日**), 调用方应意识到这是降级。
    """
    dt = _to_date(d)
    if dt is None:
        return False
    cal = _get_cal(market)
    if cal is None:
        # 降级: 仅判断周末 (节假日不识别)
        return dt.weekday() < 5
    try:
        return bool(cal.is_session(_to_timestamp(dt)))
    except Exception:
        return dt.weekday() < 5


def trading_days(
    start: str | date | datetime,
    end: str | date | datetime,
    market: str = _DEFAULT_MARKET,
) -> list[date]:
    """返回 [start, end] 区间内的交易日列表 (升序, 含端点)。

    失败安全: 降级时返回区间内所有工作日 (周一~周五, 节假日不识别)。
    """
    s, e = _to_date(start), _to_date(end)
    if s is None or e is None or s > e:
        return []
    cal = _get_cal(market)
    if cal is None:
        return [s + timedelta(days=i) for i in range((e - s).days + 1) if (s + timedelta(days=i)).weekday() < 5]
    try:
        sessions = cal.sessions_in_range(_to_timestamp(s), _to_timestamp(e))
        return [ts.date() for ts in sessions]
    except Exception:
        return [s + timedelta(days=i) for i in range((e - s).days + 1) if (s + timedelta(days=i)).weekday() < 5]


def count_trading_days(
    start: str | date | datetime,
    end: str | date | datetime,
    market: str = _DEFAULT_MARKET,
) -> int:
    """[start, end] 区间内的交易日数 (含端点)。失败安全: 降级为工作日数。"""
    return len(trading_days(start, end, market))


def next_trading_day(
    d: str | date | datetime,
    market: str = _DEFAULT_MARKET,
    n: int = 1,
) -> date | None:
    """d 之后第 n 个交易日 (n=1 默认; n 可负表示向前)。失败安全: 逐日周末启发式。

    注意: 若 d 本身是交易日, 「之后」不含 d (从次日开始数)。
    """
    dt = _to_date(d)
    if dt is None:
        return None
    if n == 0:
        return dt
    cal = _get_cal(market)
    if cal is not None:
        try:
            if n > 0:
                cur = cal.next_session(_to_timestamp(dt))
                for _ in range(n - 1):
                    cur = cal.next_session(cur)
                return cur.date()
            else:
                cur = cal.previous_session(_to_timestamp(dt))
                for _ in range(-n - 1):
                    cur = cal.previous_session(cur)
                return cur.date()
        except Exception:
            pass
    # 降级: 逐日推进, 跳过周末
    step = 1 if n > 0 else -1
    remaining = abs(n)
    cur = dt
    while remaining > 0:
        cur = cur + timedelta(days=step)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def previous_trading_day(
    d: str | date | datetime,
    market: str = _DEFAULT_MARKET,
    n: int = 1,
) -> date | None:
    """d 之前第 n 个交易日。等价于 next_trading_day(d, n=-n)。"""
    return next_trading_day(d, market, -n)


def describe(market: str = _DEFAULT_MARKET) -> dict[str, Any]:
    """交易日历概览 (供 UI/调试)。失败安全: 标 available + 降级说明。"""
    cal = _get_cal(market)
    if cal is None:
        return {
            "market": market,
            "available": False,
            "mode": "weekend_heuristic",
            "note": "exchange_calendars 未安装或该市场不支持; 仅判断周末, 节假日不识别。pip install exchange_calendars",
        }
    try:
        return {
            "market": market,
            "available": True,
            "mode": "exchange_calendars",
            "calendar_name": getattr(cal, "name", market),
            "version": getattr(xc, "__version__", "unknown"),  # type: ignore[union-attr]
        }
    except Exception:
        return {"market": market, "available": True, "mode": "exchange_calendars"}
