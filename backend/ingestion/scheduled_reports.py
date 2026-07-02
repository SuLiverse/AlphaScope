"""
Scheduled Reports: 定时报告与监控。

职责：
- 每日自动生成市场简报
- 自选股监控
- 异常事件告警
- 定时推送

架构文档要求："观察列表+自动监控"、"结论变更提醒"。
"""

import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WatchListItem:
    """观察列表项目"""

    symbol: str
    name: str
    added_at: float = 0
    last_alert: float = 0
    alert_conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Alert:
    """告警"""

    alert_id: str
    symbol: str
    alert_type: str  # price_change, volume_spike, news_breakout, signal_change
    message: str
    severity: str = "info"  # info, warning, critical
    timestamp: float = 0
    acknowledged: bool = False
    name: str = ""


class ScheduledReportManager:
    """定时报告管理器"""

    def __init__(self):
        self._watchlist: List[WatchListItem] = []
        self._alerts: List[Alert] = []
        self._last_daily_report: float = 0

    # ============== 观察列表管理 ==============

    def add_to_watchlist(
        self, symbol: str, name: str, alert_conditions: Optional[Dict] = None
    ):
        """添加到观察列表"""
        # 检查是否已存在
        for item in self._watchlist:
            if item.symbol == symbol:
                return
        self._watchlist.append(
            WatchListItem(
                symbol=symbol,
                name=name,
                added_at=time.time(),
                alert_conditions=alert_conditions or {},
            )
        )

    def remove_from_watchlist(self, symbol: str):
        """从观察列表移除"""
        self._watchlist = [item for item in self._watchlist if item.symbol != symbol]

    def get_watchlist(self) -> List[Dict[str, Any]]:
        """获取观察列表"""
        return [
            {"symbol": item.symbol, "name": item.name, "added_at": item.added_at}
            for item in self._watchlist
        ]

    # ============== 监控与告警 ==============

    def check_alerts(self, *, persist: bool = True) -> List[Alert]:
        """检查所有自选股的告警条件。

        自选股来源为持久化的 watchlist_store(SQLite),告警写入 alert_store(SQLite)。
        persist=False 时仅返回计算结果不落库(供预览/测试)。
        """
        new_alerts: List[Alert] = []
        items = self._load_watchlist_items()
        for item in items:
            try:
                alerts = self._check_item_alerts(item)
                for a in alerts:
                    a.name = item.name
                new_alerts.extend(alerts)
            except Exception as e:
                logger.debug(f"检查 {item.symbol} 告警失败: {e}")

        self._alerts.extend(new_alerts)
        if persist:
            from backend import alert_store

            for a in new_alerts:
                try:
                    alert_store.add_alert(
                        alert_id=a.alert_id,
                        symbol=a.symbol,
                        name=a.name,
                        alert_type=a.alert_type,
                        message=a.message,
                        severity=a.severity,
                        timestamp=a.timestamp,
                    )
                except Exception as e:
                    logger.debug(f"写入告警失败: {e}")
        return new_alerts

    def _load_watchlist_items(self) -> List[WatchListItem]:
        """从持久化 watchlist_store 加载自选股为内部 WatchListItem。"""
        items: List[WatchListItem] = []
        try:
            from backend.watchlist_store import list_watchlist

            for row in list_watchlist():
                symbol = row.get("symbol", "")
                name = row.get("name", "") or symbol
                cond = row.get("alert_conditions") or {}
                if isinstance(cond, dict):
                    ac = cond
                else:
                    ac = {}
                items.append(
                    WatchListItem(
                        symbol=symbol,
                        name=name,
                        added_at=row.get("added_at", 0),
                        alert_conditions=ac,
                    )
                )
        except Exception as e:
            logger.debug(f"加载自选股失败: {e}")
        return items

    def _check_item_alerts(self, item: WatchListItem) -> List[Alert]:
        """检查单个观察项的告警。

        用「交易日 + 价格涨跌幅」做稳定去重 ID,避免同一交易日重复刷告警。
        """
        alerts = []
        try:
            from backend.price_fetcher import get_price_range

            data = get_price_range(item.symbol, days=5)
            if not data:
                return alerts

            latest = data[-1] if data else {}
            price = latest.get("close", 0)
            volume = latest.get("volume", 0)
            # 用最新一根 K 线的日期做去重维度,同一天同一标的不重复告警
            trade_day = str(latest.get("date") or latest.get("day") or "")[:10]

            # 价格变动告警
            if len(data) >= 2:
                prev_price = data[-2].get("close", 0)
                if prev_price > 0:
                    change_pct = (price - prev_price) / prev_price * 100
                    threshold = item.alert_conditions.get("price_change_pct", 5)
                    if abs(change_pct) >= threshold:
                        direction = "上涨" if change_pct > 0 else "下跌"
                        day_tag = trade_day or int(time.time())
                        alerts.append(
                            Alert(
                                alert_id=f"price_{item.symbol}_{day_tag}",
                                symbol=item.symbol,
                                alert_type="price_change",
                                message=f"{item.name}({item.symbol}) {direction} {abs(change_pct):.1f}%，当前价 ¥{price:.2f}",
                                severity="warning" if abs(change_pct) >= 7 else "info",
                                timestamp=time.time(),
                            )
                        )
                        # 标注名称字段(Alert dataclass 无 name,在 message 体现)

            # 成交量异动告警
            if len(data) >= 5:
                avg_vol = sum(d.get("volume", 0) for d in data[-5:-1]) / 4
                if avg_vol > 0 and volume > avg_vol * 2:
                    day_tag = trade_day or int(time.time())
                    alerts.append(
                        Alert(
                            alert_id=f"vol_{item.symbol}_{day_tag}",
                            symbol=item.symbol,
                            alert_type="volume_spike",
                            message=f"{item.name}({item.symbol}) 成交量放大 {volume / avg_vol:.1f}倍",
                            severity="info",
                            timestamp=time.time(),
                        )
                    )

        except Exception as e:
            logger.debug(f"检查 {item.symbol} 失败: {e}")

        return alerts

    def get_alerts(self, unacknowledged_only: bool = False) -> List[Dict[str, Any]]:
        """获取告警列表"""
        alerts = self._alerts
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return [
            {
                "alert_id": a.alert_id,
                "symbol": a.symbol,
                "type": a.alert_type,
                "message": a.message,
                "severity": a.severity,
                "timestamp": a.timestamp,
                "acknowledged": a.acknowledged,
            }
            for a in alerts
        ]

    def acknowledge_alert(self, alert_id: str):
        """确认告警"""
        for a in self._alerts:
            if a.alert_id == alert_id:
                a.acknowledged = True
                break

    # ============== 每日简报 ==============

    def generate_daily_brief(self, stock_data_list: List[Dict[str, Any]]) -> str:
        """生成每日市场简报"""
        now = time.time()
        self._last_daily_report = now

        parts = ["# 每日市场简报\n"]
        parts.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        # 自选股概况
        if stock_data_list:
            parts.append("## 自选股概况\n")
            for sd in stock_data_list[:10]:
                name = sd.get("name", "")
                symbol = sd.get("symbol", "")
                close = sd.get("close", 0)
                change = sd.get("day_change", 0)
                direction = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
                parts.append(
                    f"- {direction} **{name}**({symbol}): ¥{close:.2f} ({change:+.2f}%)"
                )

        # 待处理告警
        unacked = [a for a in self._alerts if not a.acknowledged]
        if unacked:
            parts.append(f"\n## 待处理告警 ({len(unacked)} 条)\n")
            for a in unacked[-5:]:
                parts.append(f"- [{a.severity}] {a.message}")

        return "\n".join(parts)


# 单例
_manager: Optional[ScheduledReportManager] = None


def get_scheduled_report_manager() -> ScheduledReportManager:
    """获取全局定时报告管理器"""
    global _manager
    if _manager is None:
        _manager = ScheduledReportManager()
    return _manager
