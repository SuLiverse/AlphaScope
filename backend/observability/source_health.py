"""数据源健康监控

汇总所有 Provider 的健康状态, 提供前端展示接口。
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


# ---- quality_score 阈值(红黄绿) ----
QUALITY_GOOD = 80.0  # >= 80 绿
QUALITY_WARN = 50.0  # 50-79 黄
# < 50 红


def _quality_grade(score: float) -> str:
    """质量分 → 红黄绿等级(供前端着色)。"""
    if score >= QUALITY_GOOD:
        return "good"
    if score >= QUALITY_WARN:
        return "warn"
    return "poor"


def compute_quality_score(
    health: dict,
    now: float | None = None,
    fresh_window_s: float = 3600.0,
) -> dict:
    """计算单个 Provider 的质量分(v1.9.4, compass §7.2)。

    质量分 = 成功率 × 新鲜度 × 完整度(归一到 0-100), 纯函数、可单测。

    输入取自 BaseProvider.health_check(): status / last_success /
    consecutive_failures / avg_latency_ms。

    Args:
        health: 单个 provider 的 health_check() 字典。
        now: 当前时间戳(测试注入); 默认 time.time()。
        fresh_window_s: 数据新鲜度窗口(秒), 默认 1 小时内算新鲜。

    Returns:
        {quality_score, grade, success_rate, freshness_score, completeness_score}
    """
    now = time.time() if now is None else now

    status = str(health.get("status", "healthy"))
    failures = int(health.get("consecutive_failures", 0))
    last_success = float(health.get("last_success", 0) or 0)
    latency = float(health.get("avg_latency_ms", 0) or 0)

    # 1) 成功率: 由 status + 连续失败次数反推。健康=100, 每次连续失败扣分。
    if status == "healthy":
        success_rate = max(0.0, 100.0 - failures * 15.0)
    elif status == "degraded":
        success_rate = max(0.0, 60.0 - failures * 10.0)
    else:  # unhealthy
        success_rate = max(0.0, 25.0 - failures * 5.0)

    # 2) 新鲜度: last_success 距 now 越近越高。从未成功(=0)→ 0。
    if last_success <= 0:
        freshness_score = 0.0
    else:
        age = max(0.0, now - last_success)
        # fresh_window_s 内满分, 之后线性衰减到 0(衰减窗口 = 24h)。
        decay_window = 24.0 * 3600.0
        if age <= fresh_window_s:
            freshness_score = 100.0
        else:
            freshness_score = max(0.0, 100.0 * (1.0 - (age - fresh_window_s) / decay_window))

    # 3) 完整度: 以延迟代理(响应越快越完整可用)。>2s 大幅扣分; 0 延迟(未调用)中性给 50。
    if latency <= 0:
        completeness_score = 50.0
    elif latency <= 500:
        completeness_score = 100.0
    elif latency <= 2000:
        completeness_score = 80.0
    else:
        completeness_score = max(0.0, 80.0 - (latency - 2000) / 50.0)

    quality = round((success_rate * freshness_score * completeness_score) / (100.0 * 100.0), 1)
    return {
        "quality_score": quality,
        "grade": _quality_grade(quality),
        "success_rate": round(success_rate, 1),
        "freshness_score": round(freshness_score, 1),
        "completeness_score": round(completeness_score, 1),
    }


class SourceHealthMonitor:
    """数据源健康监控器"""

    def __init__(self) -> None:
        self._check_interval = 300  # 5分钟检查一次
        self._last_check = 0.0

    def get_health_report(self) -> dict:
        """获取所有数据源的健康报告"""
        try:
            from backend.providers.registry import get_registry

            registry = get_registry()
            providers = registry.get_all_health()

            healthy = sum(1 for p in providers if p["status"] == "healthy")
            degraded = sum(1 for p in providers if p["status"] == "degraded")
            unhealthy = sum(1 for p in providers if p["status"] == "unhealthy")

            return {
                "timestamp": time.time(),
                "total": len(providers),
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
                "providers": providers,
            }
        except Exception as e:
            logger.error("获取健康报告失败: %s", e)
            return {
                "timestamp": time.time(),
                "total": 0,
                "healthy": 0,
                "degraded": 0,
                "unhealthy": 0,
                "providers": [],
                "error": str(e),
            }

    def get_source_summary(self) -> str:
        """生成数据源状态摘要 (适合 LLM 上下文)"""
        report = self.get_health_report()
        lines = [f"数据源状态: {report['healthy']}/{report['total']} 正常"]
        for p in report.get("providers", []):
            status_icon = {"healthy": "✓", "degraded": "⚠", "unhealthy": "✗"}.get(p["status"], "?")
            latency = f"{p['avg_latency_ms']:.0f}ms" if p["avg_latency_ms"] > 0 else "N/A"
            lines.append(f"  {status_icon} {p['name']}: {p['status']} ({latency})")
        return "\n".join(lines)

    def get_quality_report(self, now: float | None = None) -> dict:
        """获取带质量分的数据源报告(v1.9.4)。

        在 get_health_report 基础上, 为每个 provider 附加 quality_score /
        grade(good|warn|poor)/ success_rate / freshness_score / completeness_score,
        并汇总红黄绿计数, 供前端数据源终端着色展示。

        Args:
            now: 当前时间戳(测试注入); 默认 time.time()。
        """
        base = self.get_health_report()
        providers = []
        good = warn = poor = 0
        for p in base.get("providers", []):
            scored = {**p, **compute_quality_score(p, now=now)}
            grade = scored["grade"]
            if grade == "good":
                good += 1
            elif grade == "warn":
                warn += 1
            else:
                poor += 1
            providers.append(scored)
        base["providers"] = providers
        base["quality_good"] = good
        base["quality_warn"] = warn
        base["quality_poor"] = poor
        base["avg_quality"] = (
            round(sum(p["quality_score"] for p in providers) / len(providers), 1) if providers else 0.0
        )
        return base
