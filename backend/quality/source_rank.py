"""数据源可信度排序

根据 config/data_sources.yaml 中的 source_trust_levels 对数据源进行排序和评分。
"""

from __future__ import annotations

import logging
import yaml

from backend.project_paths import CONFIG_DIR

logger = logging.getLogger(__name__)

_CONFIG_PATH = CONFIG_DIR / "data_sources.yaml"

# 可信度等级对应的分值范围
_TRUST_SCORE_RANGES = {
    "S": (0.90, 0.99),  # 交易所/官方
    "A": (0.80, 0.94),  # 专业数据源
    "B": (0.60, 0.84),  # 主流媒体
    "C": (0.30, 0.64),  # 社交/聚合
    "D": (0.10, 0.39),  # 未知来源
}


class SourceRanker:
    """数据源可信度排序器"""

    def __init__(self) -> None:
        self._trust_map: dict[str, str] = {}
        self._load_config()

    def _load_config(self) -> None:
        """从配置加载可信度映射"""
        if not _CONFIG_PATH.exists():
            return
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            trust_levels = config.get("source_trust_levels", {})
            for level, sources in trust_levels.items():
                for source in sources:
                    self._trust_map[source] = level
        except Exception as e:
            logger.warning("加载数据源可信度配置失败: %s", e)

    def get_trust_level(self, source: str) -> str:
        """获取数据源的可信度等级"""
        return self._trust_map.get(source, "D")

    def get_trust_score(self, source: str) -> float:
        """获取数据源的可信度分值 (0.0 ~ 1.0)"""
        level = self.get_trust_level(source)
        low, high = _TRUST_SCORE_RANGES.get(level, (0.1, 0.3))
        # 取中间值
        return (low + high) / 2

    def rank_items(self, items: list[dict], source_key: str = "source") -> list[dict]:
        """按可信度排序数据条目 (高可信度在前)"""
        return sorted(
            items,
            key=lambda x: self.get_trust_score(x.get(source_key, "")),
            reverse=True,
        )

    def merge_by_trust(self, items: list[dict], source_key: str = "source") -> list[dict]:
        """合并多源数据, 高可信度源优先

        对相同内容(需先去重)的数据, 保留可信度最高的版本。
        """
        # 简单实现: 按可信度排序后返回
        return self.rank_items(items, source_key)
