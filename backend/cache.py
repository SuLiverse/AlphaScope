"""内存 TTL 缓存 — 线程安全，无外部依赖"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    """线程安全的内存 TTL 缓存。

    用法：
        cache = TTLCache(max_size=1000)
        cache.set("key", value, ttl_seconds=300)
        val = cache.get("key")
    """

    def __init__(self, max_size: int = 1000):
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self._max_size = max_size
        self._hits = 0
        self._misses = 0
        self._stale_hits = 0

    def get(self, key: str) -> Any | None:
        """获取缓存值，过期返回 None。"""
        value, _is_stale = self.get_fresh_or_stale(key)
        return value

    def get_fresh_or_stale(self, key: str, max_stale_seconds: int = 0) -> tuple[Any | None, bool]:
        """返回 ``(value, is_stale)``，可在有限窗口内保留过期值用于降级。"""
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None, False
            value, expires_at = item
            now = time.time()
            if expires_at < now:
                if max_stale_seconds > 0 and now <= expires_at + max_stale_seconds:
                    self._stale_hits += 1
                    return value, True
                del self._data[key]
                self._misses += 1
                return None, False
            self._hits += 1
            return value, False

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """设置缓存值。"""
        with self._lock:
            if len(self._data) >= self._max_size:
                self._evict()
            self._data[key] = (value, time.time() + ttl_seconds)

    def delete(self, key: str) -> None:
        """删除缓存项。"""
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._data.clear()
            self._hits = 0
            self._misses = 0
            self._stale_hits = 0

    def stats(self) -> dict[str, Any]:
        """缓存统计。"""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._data),
                "max_size": self._max_size,
                "hits": self._hits,
                "misses": self._misses,
                "stale_hits": self._stale_hits,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0,
            }

    def _evict(self) -> None:
        """淘汰过期项，如仍超限则淘汰最早项。"""
        now = time.time()
        # 先淘汰过期项
        expired = [k for k, (_, exp) in self._data.items() if exp < now]
        for k in expired:
            del self._data[k]
        # 如仍超限，淘汰最早过期的
        if len(self._data) >= self._max_size:
            oldest = min(self._data, key=lambda k: self._data[k][1])
            del self._data[oldest]

    def cleanup_expired(self) -> int:
        """主动清理所有过期项，返回清理数量。"""
        with self._lock:
            now = time.time()
            expired = [k for k, (_, exp) in self._data.items() if exp < now]
            for k in expired:
                del self._data[k]
            return len(expired)


# 全局缓存实例
_global_cache = TTLCache(max_size=2000)


def get_cache() -> TTLCache:
    """获取全局缓存实例。"""
    return _global_cache


def get_cached(key: str, factory: Callable[[], Any], ttl_seconds: int = 300) -> Any:
    """缓存便捷函数：命中返回缓存值，未命中调用 factory 并缓存。

    用法：
        data = get_cached("news:600519", lambda: fetch_news("600519"), ttl_seconds=180)
    """
    cache = get_cache()
    value = cache.get(key)
    if value is not None:
        return value
    value = factory()
    if value is not None:
        cache.set(key, value, ttl_seconds)
    return value
