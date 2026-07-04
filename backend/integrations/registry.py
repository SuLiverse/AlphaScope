"""Integration Registry / 插件中心 (Phase 1).

所有外部项目通过本注册表接入 AlphaScope。提供:

1. 显式注册: ``@register`` 装饰 adapter 子类。
2. 自动发现: ``autodiscover()`` 扫描 backend/integrations/{data,factor,backtest,agent}
   子包里的 adapter。
3. 统一查询: ``all_metadata()`` / ``get()`` / ``healthcheck_all()``。
4. **交易边界第四道防线** (Phase 0 §13.3): 注册时强制断言每个 adapter
   ``allow_live_order=False`` 且不暴露禁止能力 (submit_order/place_order/...)。
5. 许可证防火墙: 对 copyleft/非商业/商业 adapter, 警告若 ``code_copy_allowed=True``。

合规: 注册表本身不执行任何交易, 只负责能力描述与健康探测。
"""

from __future__ import annotations

import importlib
import pkgutil
import threading

from backend.integrations.base import BaseAdapter
from backend.integrations.schemas import (
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    LicenseSafety,
)
from backend.security.trading_boundary import get_boundary

# adapter 暴露的能力名里不得出现这些 token (Phase 0 第四道防线)
_FORBIDDEN_CAPABILITY_TOKENS: tuple[str, ...] = (
    "submit_order",
    "place_order",
    "execute_trade",
    "auto_trade",
    "live_brokerage",
    "live_order",
)

# 自动发现时扫描的子包
_AUTODISCOVER_SUBPACKAGES: tuple[str, ...] = (
    "data",
    "factor",
    "backtest",
    "agent",
    "document",
    "ui",
)


class IntegrationRegistry:
    """进程级单例 adapter 注册表。"""

    def __init__(self) -> None:
        self._classes: dict[str, type[BaseAdapter]] = {}
        self._instances: dict[str, BaseAdapter] = {}
        self._lock = threading.Lock()

    # ---------------- 注册 ----------------
    def register(self, adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
        """注册一个 adapter 类。可作为装饰器使用。

        注册时执行三道边界断言 (Phase 0 第四道防线):
        1. metadata().allow_live_order is False
        2. capabilities 不含禁止 token
        3. copyleft/非商业/商业 adapter 必须 code_copy_allowed=False
        """
        # 临时实例化只为了读 metadata (假设构造无副作用)
        try:
            probe = adapter_cls()
        except Exception as e:  # 构造失败不致命, 跳过注册但记录
            raise RuntimeError(f"adapter {adapter_cls.__name__} 实例化失败: {e}") from e

        meta = probe.metadata()  # BaseAdapter.metadata 已含 allow_live_order 校验

        # 断言 1: 交易边界
        if meta.allow_live_order is not False:
            raise ValueError(f"adapter {meta.name!r} 违反交易边界: allow_live_order 必须 False")

        # 断言 2: 能力黑名单
        for cap in meta.capabilities:
            cap_low = cap.name.lower()
            for tok in _FORBIDDEN_CAPABILITY_TOKENS:
                if tok in cap_low:
                    raise ValueError(
                        f"adapter {meta.name!r} 暴露禁止能力 {cap.name!r} (含 {tok!r}): AlphaScope 不接实盘下单链路。"
                    )

        # 断言 3: 许可证防火墙
        if meta.code_copy_allowed and meta.license_safety in (
            LicenseSafety.COPILEFT_RISK,
            LicenseSafety.NONCOMMERCIAL,
            LicenseSafety.PROPRIETARY,
        ):
            raise ValueError(
                f"adapter {meta.name!r} 许可证 {meta.license_safety.value} 不允许 code_copy_allowed=True; "
                f"应改 mode=external_process + 仅协议兼容。"
            )

        with self._lock:
            self._classes[meta.name] = adapter_cls
            self._instances.pop(meta.name, None)  # 失效旧实例
        return adapter_cls

    # ---------------- 查询 ----------------
    def get(self, name: str) -> BaseAdapter:
        """按名取 adapter 单例实例。"""
        with self._lock:
            if name not in self._classes:
                raise KeyError(f"未注册的 integration: {name!r}")
            if name not in self._instances:
                self._instances[name] = self._classes[name]()
            return self._instances[name]

    def has(self, name: str) -> bool:
        return name in self._classes

    def names(self) -> list[str]:
        return sorted(self._classes.keys())

    def all_metadata(self) -> list[IntegrationMetadata]:
        """所有 adapter 的元数据 (按名排序)。"""
        return [self.get(n).metadata() for n in self.names()]

    def healthcheck_all(self) -> dict[str, IntegrationHealth]:
        """对所有 adapter 做健康检查 (单异常不影响其它)。"""
        out: dict[str, IntegrationHealth] = {}
        for n in self.names():
            try:
                out[n] = self.get(n).healthcheck()
            except Exception as e:
                out[n] = IntegrationHealth(name=n, status=HealthStatus.DOWN, message=f"healthcheck 抛错: {e}")
        return out

    def clear(self) -> None:
        """清空 (测试用)。"""
        with self._lock:
            self._classes.clear()
            self._instances.clear()


# ------------------- 进程级单例 -------------------

_registry_singleton: IntegrationRegistry | None = None
# 必须用 RLock: autodiscover 会 import ``*_adapter.py``, 其模块级 ``@register``
# 装饰器会重入 get_registry()。threading.Lock 不可重入会死锁; RLock 允许同线程多次获取。
_singleton_lock = threading.RLock()


def get_registry() -> IntegrationRegistry:
    """获取进程级 registry 单例, 首次调用触发自动发现。

    防死锁: autodiscover 会 import 各 ``*_adapter.py``, 其模块级 ``@register``
    装饰器会**重入**本函数。因此:
    1. 锁用 RLock (同线程可重入);
    2. autodiscover 前先把单例设上, 重入的 get_registry() 直接拿到正在构建的
       registry (返回已注册部分), 不会再次进入 autodiscover。
    """
    global _registry_singleton
    with _singleton_lock:
        if _registry_singleton is None:
            reg = IntegrationRegistry()
            _registry_singleton = reg  # 先发布, 防止 autodiscover 内的重入死锁
            try:
                autodiscover(registry=reg)
            except Exception:
                _registry_singleton = None  # autodiscover 失败则回滚, 下次重试
                raise
        return _registry_singleton


def reset_registry() -> None:
    """重置单例 (测试用)。"""
    global _registry_singleton
    with _singleton_lock:
        _registry_singleton = None


# ------------------- 装饰器 / 自动发现 -------------------


def register(adapter_cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """``@register`` 装饰器: 注册到单例 registry。"""
    return get_registry().register(adapter_cls)


def autodiscover(registry: IntegrationRegistry | None = None) -> int:
    """扫描 integrations 子包, 自动注册发现的 adapter。

    约定: 子包 (data/factor/backtest/agent/...) 下任何 ``*_adapter.py`` 模块里
    顶层定义的 BaseAdapter 子类都会被发现。重复 import / 已注册会被跳过。

    返回新注册的数量。模块 import 错误被吞掉 (可选依赖缺失不应让系统启动失败)。
    """
    reg = registry or get_registry()
    base_pkg = "backend.integrations"
    added = 0

    for sub in _AUTODISCOVER_SUBPACKAGES:
        pkg_name = f"{base_pkg}.{sub}"
        try:
            pkg = importlib.import_module(pkg_name)
        except Exception:
            continue  # 子包不存在/未装, 跳过

        pkg_path = getattr(pkg, "__path__", None)
        if not pkg_path:
            continue

        for _finder, mod_name, _ispkg in pkgutil.iter_modules(pkg_path):
            if not mod_name.endswith("_adapter"):
                continue
            full = f"{pkg_name}.{mod_name}"
            try:
                mod = importlib.import_module(full)
            except Exception:
                continue  # 可选依赖缺失, 跳过 (adapter 的 healthcheck 会报告 UNAVAILABLE)

            for attr in dir(mod):
                obj = getattr(mod, attr, None)
                if not isinstance(obj, type) or not issubclass(obj, BaseAdapter):
                    continue
                if obj in (BaseAdapter,) or obj.__module__ != full:
                    continue
                name = ""
                try:
                    name = obj().metadata().name
                except Exception:
                    continue
                if name and not reg.has(name):
                    try:
                        reg.register(obj)
                        added += 1
                    except Exception:
                        continue
    return added


def assert_boundary_invariant() -> None:
    """Phase 0 第四道防线入口: 对所有已注册 adapter 复核交易边界。

    由 tests/integrations 与启动期 / CI 调用。
    """
    boundary = get_boundary()
    boundary.assert_invariant()  # 复用 Phase 0 不变量
    reg = get_registry()
    for meta in reg.all_metadata():
        if meta.allow_live_order is not False:
            raise AssertionError(f"integration {meta.name!r} allow_live_order 必须 False (Phase 0 边界)")
        for cap in meta.capabilities:
            low = cap.name.lower()
            for tok in _FORBIDDEN_CAPABILITY_TOKENS:
                if tok in low:
                    raise AssertionError(f"integration {meta.name!r} 暴露禁止能力 {cap.name!r}")
