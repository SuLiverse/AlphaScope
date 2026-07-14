"""进程内滑动窗口限流 — API / 分析等高成本路径。

从 config/safety.yaml 读取默认 rpm/rph; 环境变量可覆盖:
  ALPHASCOPE_RATE_LIMIT_RPM / ALPHASCOPE_RATE_LIMIT_RPH
  ALPHASCOPE_RATE_LIMIT_DISABLED=1 关闭

纯内存、线程安全、失败时放行(不因限流模块异常阻断服务)。
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Optional

_lock = threading.Lock()
_windows: dict[str, Deque[float]] = defaultdict(deque)
_config_loaded = False
_rpm = 30
_rph = 200
_disabled = False


def _load_config() -> None:
    global _config_loaded, _rpm, _rph, _disabled
    if _config_loaded:
        return
    _config_loaded = True
    if os.getenv("ALPHASCOPE_RATE_LIMIT_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        _disabled = True
        return
    try:
        _rpm = int(os.getenv("ALPHASCOPE_RATE_LIMIT_RPM", "0") or 0)
        _rph = int(os.getenv("ALPHASCOPE_RATE_LIMIT_RPH", "0") or 0)
    except ValueError:
        _rpm, _rph = 0, 0
    if _rpm <= 0 or _rph <= 0:
        try:
            from pathlib import Path

            import yaml

            from backend.project_paths import CONFIG_DIR

            path = CONFIG_DIR / "safety.yaml"
            if path.is_file():
                raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                rl = (raw.get("security") or {}).get("rate_limit") or {}
                if _rpm <= 0:
                    _rpm = int(rl.get("requests_per_minute") or 30)
                if _rph <= 0:
                    _rph = int(rl.get("requests_per_hour") or 200)
        except Exception:
            _rpm = _rpm or 30
            _rph = _rph or 200
    _rpm = max(1, _rpm)
    _rph = max(_rpm, _rph)


def reset_for_tests() -> None:
    """测试用: 清空状态。"""
    global _config_loaded, _disabled
    with _lock:
        _windows.clear()
        _config_loaded = False
        _disabled = False


def check_rate_limit(key: str = "global", *, cost: int = 1) -> dict[str, Any]:
    """检查是否允许请求。返回 {allowed, retry_after_sec, remaining_minute}。"""
    try:
        _load_config()
        if _disabled:
            return {"allowed": True, "retry_after_sec": 0, "remaining_minute": 999, "disabled": True}

        now = time.time()
        with _lock:
            q = _windows[key]
            # 淘汰 1 小时外
            while q and now - q[0] > 3600:
                q.popleft()
            minute_count = sum(1 for t in q if now - t <= 60)
            hour_count = len(q)
            if minute_count + cost > _rpm:
                oldest_in_min = next((t for t in q if now - t <= 60), now)
                retry = max(0.1, 60 - (now - oldest_in_min))
                return {
                    "allowed": False,
                    "retry_after_sec": round(retry, 2),
                    "remaining_minute": 0,
                    "reason": "rpm",
                    "limit_rpm": _rpm,
                }
            if hour_count + cost > _rph:
                oldest = q[0] if q else now
                retry = max(0.1, 3600 - (now - oldest))
                return {
                    "allowed": False,
                    "retry_after_sec": round(retry, 2),
                    "remaining_minute": max(0, _rpm - minute_count),
                    "reason": "rph",
                    "limit_rph": _rph,
                }
            for _ in range(max(1, cost)):
                q.append(now)
            return {
                "allowed": True,
                "retry_after_sec": 0,
                "remaining_minute": max(0, _rpm - minute_count - cost),
                "limit_rpm": _rpm,
                "limit_rph": _rph,
            }
    except Exception as exc:  # noqa: BLE001
        return {"allowed": True, "retry_after_sec": 0, "remaining_minute": 999, "error": type(exc).__name__}


def client_key_from_request(request: Any) -> str:
    """从 FastAPI Request 提取限流键。"""
    try:
        token = (
            request.headers.get("X-AlphaScope-Local-Token")
            or request.query_params.get("local_token")
            or ""
        )
        if token:
            return f"tok:{token[:16]}"
        client = getattr(request, "client", None)
        host = getattr(client, "host", None) or "unknown"
        return f"ip:{host}"
    except Exception:
        return "global"


# 高成本路径前缀(子串匹配)
EXPENSIVE_PREFIXES = (
    "/api/analysis",
    "/api/quant/backtest",
    "/api/quant/evolve",
    "/api/quant/walk-forward",
    "/api/quant/compare",
    "/api/integrations/",
    "/api/vision",
    "/api/chat",
)


def is_expensive_path(path: str) -> bool:
    p = path or ""
    return any(p.startswith(pref) or pref.rstrip("/") in p for pref in EXPENSIVE_PREFIXES)
