"""Provider Registry - 数据源自动发现、优先级选择和故障降级"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from pathlib import Path
from typing import Optional

import yaml

from .base import BaseProvider

logger = logging.getLogger(__name__)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DATA_SOURCES_CONFIG = _PROJECT_ROOT / "config" / "data_sources.yaml"


class ProviderRegistry:
    """数据源注册中心

    功能:
    - 注册/注销 Provider 实例
    - 按 data_type + market 自动选择最优 Provider
    - 故障降级: 主源失败自动尝试下一优先级
    - 从 config/data_sources.yaml 读取配置
    - 动态发现: 自动扫描 providers/ 和 custom_providers/ 目录
    """

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._source_origin: dict[str, str] = {}  # name -> "builtin" | "custom"
        self._config: dict = {}
        self._load_config()

    def _load_config(self) -> None:
        """加载数据源配置"""
        if _DATA_SOURCES_CONFIG.exists():
            try:
                with open(_DATA_SOURCES_CONFIG, "r", encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
                logger.info("已加载数据源配置: %s", _DATA_SOURCES_CONFIG)
            except Exception as e:
                logger.warning("加载数据源配置失败: %s", e)
                self._config = {}

    def register(self, provider: BaseProvider, origin: str = "builtin") -> None:
        """注册一个 Provider"""
        if provider.name in self._providers:
            logger.warning(
                "Provider '%s' 已存在, 将被覆盖 (原: %s, 新: %s)",
                provider.name,
                type(self._providers[provider.name]).__name__,
                type(provider).__name__,
            )
        self._providers[provider.name] = provider
        self._source_origin[provider.name] = origin
        logger.info(
            "已注册 Provider: %s (markets=%s, types=%s, priority=%d, origin=%s)",
            provider.name,
            provider.markets,
            provider.data_types,
            provider.priority,
            origin,
        )

    def unregister(self, name: str) -> None:
        """注销一个 Provider"""
        self._providers.pop(name, None)
        self._source_origin.pop(name, None)

    def get_provider(self, name: str) -> Optional[BaseProvider]:
        """按名称获取 Provider"""
        return self._providers.get(name)

    def list_providers(self) -> list[dict]:
        """列出所有已注册 Provider"""
        return [
            {
                "name": p.name,
                "markets": p.markets,
                "data_types": p.data_types,
                "priority": p.priority,
                "status": p.health.status.value,
                "origin": self._source_origin.get(p.name, "unknown"),
                "cost_tier": getattr(p, "cost_tier", "free"),
                "freshness": getattr(p, "freshness", "daily"),
                "requires_key": getattr(p, "requires_key", False),
            }
            for p in self._providers.values()
        ]

    def reload(self) -> None:
        """重新发现和注册所有 Provider (用于开发/调试)"""
        self._providers.clear()
        self._source_origin.clear()
        self._load_config()
        _discover_and_register(self)

    def get(
        self,
        data_type: str,
        market: str = "CN",
        symbol: str = "",
        **query_kwargs,
    ) -> list:
        """自动选择 Provider 获取数据

        Args:
            data_type: 数据类型 (news/report/announcement/price/fundamental/fund_flow)
            market: 市场 (CN/HK/US)
            symbol: 股票代码 (可选, 用于判断市场)
            **query_kwargs: 传递给 Provider 的查询参数

        Returns:
            Provider 返回的数据列表
        """
        # 按优先级排序的候选 Provider
        candidates = self._get_candidates(data_type, market)
        if not candidates:
            logger.warning("没有可用的 Provider: data_type=%s, market=%s", data_type, market)
            return []

        query = {"market": market, "symbol": symbol, **query_kwargs}
        last_error = None

        for provider in candidates:
            try:
                method = getattr(provider, f"get_{data_type}", None)
                if method is None:
                    continue
                result = method(query)
                if result:
                    logger.info(
                        "[Registry] %s.%s 返回 %d 条数据",
                        provider.name,
                        data_type,
                        len(result) if isinstance(result, list) else 1,
                    )
                    return result
            except NotImplementedError:
                continue
            except Exception as e:
                last_error = e
                logger.warning(
                    "[Registry] %s.%s 失败: %s, 尝试下一源",
                    provider.name,
                    data_type,
                    e,
                )
                continue

        logger.error(
            "[Registry] 所有 Provider 均失败: data_type=%s, market=%s, last_error=%s",
            data_type,
            market,
            last_error,
        )
        return []

    def _get_candidates(self, data_type: str, market: str) -> list[BaseProvider]:
        """获取符合条件的候选 Provider, 按优先级降序排列"""
        candidates = []
        for provider in self._providers.values():
            # 检查是否支持该数据类型
            if data_type not in provider.data_types:
                continue
            # 检查是否支持该市场
            if market not in provider.markets and "ALL" not in provider.markets:
                continue
            # 检查是否在配置中被禁用
            if not self._is_enabled(provider.name, data_type):
                continue
            candidates.append(provider)

        # 按优先级降序排列 (配置优先级 > Provider 默认优先级)
        candidates.sort(
            key=lambda p: self._get_config_priority(p.name, data_type) or p.priority,
            reverse=True,
        )
        return candidates

    def _is_enabled(self, provider_name: str, data_type: str) -> bool:
        """检查 Provider 在配置中是否启用"""
        # data_type 用复数 (如 prices), yaml 用单数键 (如 price), 需映射
        config_key = self._section_key_for(data_type)
        provider_config = self._config.get(config_key, {}).get(provider_name, {})
        return provider_config.get("enabled", True)

    def _get_config_priority(self, provider_name: str, data_type: str) -> Optional[int]:
        """从配置中获取 Provider 优先级"""
        config_key = self._section_key_for(data_type)
        provider_config = self._config.get(config_key, {}).get(provider_name, {})
        return provider_config.get("priority")

    # data_type (复数, provider.data_types) -> yaml 单数键
    _DATA_TYPE_TO_YAML_KEY: dict[str, str] = {
        "prices": "price",
        "announcements": "announcement",
        "reports": "report",
    }

    def _section_key_for(self, data_type: str) -> str:
        return f"{self._DATA_TYPE_TO_YAML_KEY.get(data_type, data_type)}_providers"

    def get_all_health(self) -> list[dict]:
        """获取所有 Provider 的健康状态"""
        return [p.health_check() for p in self._providers.values()]

    def get_all_capabilities(self) -> list[dict]:
        """获取所有 Provider 的标准化能力描述(v1.9.4)。

        对标 tickflow tiers.yaml 的能力驱动: 用同一套 schema 表达每个数据源的
        市场/数据类型/粒度/延迟/成本/速率限制/凭证需求/优先级/可降级, 供前端筛选展示。
        """
        return [p.capability() for p in self._providers.values()]

    def get_source_trust_level(self, source: str) -> str:
        """获取数据源的可信度等级 (S/A/B/C/D)"""
        trust_levels = self._config.get("source_trust_levels", {})
        for level, sources in trust_levels.items():
            if source in sources:
                return level
        return "D"


# 全局单例
_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    """获取全局 ProviderRegistry 单例"""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        _discover_and_register(_registry)
    return _registry


def _scan_directory(directory: Path, package_prefix: str) -> list[type]:
    """扫描目录中的 Python 模块, 找出所有 BaseProvider 子类

    Args:
        directory: 要扫描的目录路径
        package_prefix: 模块的包前缀 (如 "backend.providers")

    Returns:
        找到的 Provider 类列表
    """
    classes = []
    if not directory.is_dir():
        return classes

    for module_info in pkgutil.iter_modules([str(directory)]):
        # 跳过私有模块 (以 _ 开头)
        if module_info.name.startswith("_"):
            continue

        full_name = f"{package_prefix}.{module_info.name}"
        try:
            module = importlib.import_module(full_name)
        except ImportError as e:
            logger.debug("跳过模块 %s (ImportError): %s", full_name, e)
            continue
        except Exception as e:
            logger.warning("导入模块 %s 时出错: %s", full_name, e)
            continue

        # 在模块中查找 BaseProvider 子类
        for attr_name in dir(module):
            try:
                attr = getattr(module, attr_name)
            except Exception:
                continue
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseProvider)
                and attr is not BaseProvider
                and not inspect.isabstract(attr)
            ):
                classes.append(attr)

    return classes


def _discover_and_register(registry: ProviderRegistry) -> None:
    """动态发现并注册所有 Provider

    扫描三个目录:
    1. backend/providers/ (内置 Provider)
    2. backend/providers/commercial/ (商业 Provider)
    3. custom_providers/ (用户自定义 Provider)
    """
    providers_dir = Path(__file__).parent
    commercial_dir = providers_dir / "commercial"
    custom_dir = _PROJECT_ROOT / "custom_providers"

    all_classes: list[tuple[type, str]] = []

    # 扫描内置 Provider
    for cls in _scan_directory(providers_dir, "backend.providers"):
        all_classes.append((cls, "builtin"))

    # 扫描商业 Provider
    for cls in _scan_directory(commercial_dir, "backend.providers.commercial"):
        all_classes.append((cls, "builtin"))

    # 扫描用户自定义 Provider
    for cls in _scan_directory(custom_dir, "custom_providers"):
        all_classes.append((cls, "custom"))

    # 实例化并注册
    registered = 0
    for cls, origin in all_classes:
        # 检查依赖是否满足
        try:
            if not cls.is_available():
                logger.debug("Provider %s 不可用 (依赖未满足), 跳过", cls.__name__)
                continue
        except Exception as e:
            logger.debug("检查 %s.is_available() 失败: %s", cls.__name__, e)
            continue

        try:
            instance = cls()
            registry.register(instance, origin=origin)
            registered += 1
        except Exception as e:
            logger.warning("注册 Provider %s 失败: %s", cls.__name__, e)

    logger.info("动态发现完成, 共注册 %d 个 Provider", registered)
