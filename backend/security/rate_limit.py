"""进程内滑动窗口限流 — API / 分析等高成本路径。

从 config/safety.yaml 读取默认 rpm/rph; 环境变量可覆盖:
  ALPHASCOPE_RATE_LIMIT_RPM / ALPHASCOPE_RATE_LIMIT_RPH
  ALPHASCOPE_RATE_LIMIT_DISABLED=1 关闭

纯内存、线程安全、失败时放行(不因限流模块异常阻断服务)。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import deque
from typing import Any, Deque

_lock = threading.Lock()
_windows: dict[str, Deque[float]] = {}
_last_seen: dict[str, float] = {}
_config_loaded = False
_rpm = 30
_rph = 200
_disabled = False
_max_buckets = 4096
_config_signature: tuple[str, str, str, str] | None = None

_DEFAULT_RPM = 30
_DEFAULT_RPH = 200
_DEFAULT_MAX_BUCKETS = 4096
_WINDOW_SECONDS = 3600.0
_OVERFLOW_BUCKET = "__overflow__"


def _environment_signature() -> tuple[str, str, str, str]:
    return (
        os.getenv("ALPHASCOPE_RATE_LIMIT_DISABLED", ""),
        os.getenv("ALPHASCOPE_RATE_LIMIT_RPM", ""),
        os.getenv("ALPHASCOPE_RATE_LIMIT_RPH", ""),
        os.getenv("ALPHASCOPE_RATE_LIMIT_MAX_BUCKETS", ""),
    )


def _positive_int(value: str) -> int:
    try:
        return max(0, int(value or 0))
    except ValueError:
        return 0


def _load_config() -> None:
    global _config_loaded, _rpm, _rph, _disabled, _max_buckets, _config_signature
    signature = _environment_signature()
    if _config_loaded and signature == _config_signature:
        return
    with _lock:
        if _config_loaded and signature == _config_signature:
            return
        _disabled = signature[0].strip().lower() in {"1", "true", "yes", "on"}
        rpm = _positive_int(signature[1])
        rph = _positive_int(signature[2])
        max_buckets = _positive_int(signature[3])
        if rpm <= 0 or rph <= 0:
            try:
                import yaml

                from backend.project_paths import CONFIG_DIR

                path = CONFIG_DIR / "safety.yaml"
                if path.is_file():
                    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    rate_config = (raw.get("security") or {}).get("rate_limit") or {}
                    if rpm <= 0:
                        rpm = int(rate_config.get("requests_per_minute") or _DEFAULT_RPM)
                    if rph <= 0:
                        rph = int(rate_config.get("requests_per_hour") or _DEFAULT_RPH)
            except Exception:
                rpm = rpm or _DEFAULT_RPM
                rph = rph or _DEFAULT_RPH
        _rpm = max(1, rpm or _DEFAULT_RPM)
        _rph = max(_rpm, rph or _DEFAULT_RPH)
        _max_buckets = max(1, max_buckets or _DEFAULT_MAX_BUCKETS)
        _windows.clear()
        _last_seen.clear()
        _config_loaded = True
        _config_signature = signature


def reset_for_tests() -> None:
    """测试用: 清空状态。"""
    global _config_loaded, _rpm, _rph, _disabled, _max_buckets, _config_signature
    with _lock:
        _windows.clear()
        _last_seen.clear()
        _config_loaded = False
        _rpm = _DEFAULT_RPM
        _rph = _DEFAULT_RPH
        _disabled = False
        _max_buckets = _DEFAULT_MAX_BUCKETS
        _config_signature = None


def _prune_stale_buckets(now: float) -> None:
    stale: list[str] = []
    for bucket_key, window in _windows.items():
        while window and now - window[0] > _WINDOW_SECONDS:
            window.popleft()
        if not window and now - _last_seen.get(bucket_key, 0.0) > _WINDOW_SECONDS:
            stale.append(bucket_key)
    for bucket_key in stale:
        _windows.pop(bucket_key, None)
        _last_seen.pop(bucket_key, None)


def _bounded_bucket(key: str, now: float) -> Deque[float]:
    bucket = _windows.get(key)
    if bucket is not None:
        _last_seen[key] = now
        return bucket
    if len(_windows) >= _max_buckets:
        key = _OVERFLOW_BUCKET
        bucket = _windows.get(key)
        if bucket is not None:
            _last_seen[key] = now
            return bucket
        oldest_key = min(_last_seen, key=_last_seen.get)
        _windows.pop(oldest_key, None)
        _last_seen.pop(oldest_key, None)
    bucket = deque()
    _windows[key] = bucket
    _last_seen[key] = now
    return bucket


def _state_for_tests() -> dict[str, int | bool]:
    """Return non-sensitive in-memory state for isolation and bound assertions."""
    with _lock:
        return {
            "bucket_count": len(_windows),
            "rpm": _rpm,
            "rph": _rph,
            "max_buckets": _max_buckets,
            "disabled": _disabled,
        }


def check_rate_limit(key: str = "global", *, cost: int = 1) -> dict[str, Any]:
    """检查是否允许请求。返回 {allowed, retry_after_sec, remaining_minute}。"""
    try:
        _load_config()
        if _disabled:
            return {"allowed": True, "retry_after_sec": 0, "remaining_minute": 999, "disabled": True}

        normalized_cost = max(1, int(cost))
        now = time.time()
        with _lock:
            _prune_stale_buckets(now)
            q = _bounded_bucket(str(key or "global"), now)
            minute_count = sum(1 for t in q if now - t <= 60)
            hour_count = len(q)
            if minute_count + normalized_cost > _rpm:
                oldest_in_min = next((t for t in q if now - t <= 60), now)
                retry = max(0.1, 60 - (now - oldest_in_min))
                return {
                    "allowed": False,
                    "retry_after_sec": round(retry, 2),
                    "remaining_minute": 0,
                    "reason": "rpm",
                    "limit_rpm": _rpm,
                }
            if hour_count + normalized_cost > _rph:
                oldest = q[0] if q else now
                retry = max(0.1, _WINDOW_SECONDS - (now - oldest))
                return {
                    "allowed": False,
                    "retry_after_sec": round(retry, 2),
                    "remaining_minute": max(0, _rpm - minute_count),
                    "reason": "rph",
                    "limit_rph": _rph,
                }
            for _ in range(normalized_cost):
                q.append(now)
            return {
                "allowed": True,
                "retry_after_sec": 0,
                "remaining_minute": max(0, _rpm - minute_count - normalized_cost),
                "limit_rpm": _rpm,
                "limit_rph": _rph,
            }
    except Exception as exc:  # noqa: BLE001
        return {"allowed": True, "retry_after_sec": 0, "remaining_minute": 999, "error": type(exc).__name__}


def client_key_from_request(request: Any) -> str:
    """从 FastAPI Request 提取限流键。"""
    try:
        token = request.headers.get("X-AlphaScope-Local-Token") or request.query_params.get("local_token") or ""
        expected = os.getenv("ALPHASCOPE_LOCAL_API_TOKEN", "").strip()
        if token and expected and hmac.compare_digest(token, expected):
            digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
            return f"tok:{digest}"
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
    "/api/quant/portfolio/",
    "/api/quant/experiments",
    "/api/quant/compare-strategies",
    "/api/datalake/",
    "/api/integrations/",
    "/api/settings/local-llm-presets/probe",
    "/api/vision",
    "/api/chat",
)


def is_expensive_path(path: str) -> bool:
    normalized = (path or "").rstrip("/") or "/"
    if any(
        normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/")
        for prefix in EXPENSIVE_PREFIXES
    ):
        return True
    parts = normalized.strip("/").split("/")
    return len(parts) == 5 and parts[:3] == ["api", "settings", "providers"] and parts[-1] == "test"
