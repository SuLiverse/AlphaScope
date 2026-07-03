"""
Evidence Aggregator (v0.12)

Cross-validate data from multiple providers.
Collect same-type data from N sources, boost confidence for multi-source confirmation.

Replaces the simple "first one wins" fallback chain with "collect and cross-validate".
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AggregatedEvidence:
    """Result of cross-validating data from multiple sources"""

    data_type: str  # news, report, announcement, price
    items: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    confidence: float = 0.6  # Base confidence
    confirmed_by: int = 0  # Number of sources confirming the same event
    contradictions: List[str] = field(default_factory=list)

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.8

    @property
    def is_multi_source(self) -> bool:
        return self.confirmed_by >= 2

    def to_dict(self) -> Dict[str, Any]:
        # 暴露精简 items(前 20 条, 取通用字段), 供前端多源聚合可视化按源着色展示。
        sample_items = []
        for it in (self.items or [])[:20]:
            if not isinstance(it, dict):
                continue
            sample_items.append(
                {
                    "title": str(it.get("title") or it.get("name") or "")[:120],
                    "source": str(it.get("source") or it.get("source_name") or "")[:40],
                    "published_at": str(it.get("published_at") or it.get("date") or "")[:25],
                    "sentiment": it.get("sentiment"),
                    "url": str(it.get("source_url") or it.get("url") or "")[:200],
                }
            )
        return {
            "data_type": self.data_type,
            "item_count": len(self.items),
            "sources": self.sources,
            "confidence": round(self.confidence, 2),
            "confirmed_by": self.confirmed_by,
            "contradictions": self.contradictions,
            "is_high_confidence": self.is_high_confidence,
            "is_multi_source": self.is_multi_source,
            "sample_items": sample_items,
        }


class EvidenceAggregator:
    """
    Collect data from multiple providers and cross-validate.

    Instead of "first provider that works wins", collect from up to N providers
    and boost confidence when multiple sources confirm the same information.
    """

    # Confidence boost per additional confirming source
    CONFIRMATION_BOOST = 0.1

    # Maximum confidence cap
    MAX_CONFIDENCE = 0.95

    # Base confidence for single source
    SINGLE_SOURCE_CONFIDENCE = 0.6

    # Trust level multipliers (from data_sources.yaml)
    TRUST_MULTIPLIERS = {
        "S": 1.2,  # Highest trust (e.g., CNINFO, HKEX)
        "A": 1.1,  # High trust (e.g., Eastmoney, Cailian)
        "B": 1.0,  # Standard trust
        "C": 0.9,  # Lower trust
        "D": 0.8,  # Lowest trust
    }

    def __init__(self, registry=None):
        self._registry = registry

    def collect_and_validate(
        self,
        query: str,
        data_type: str,
        max_sources: int = 3,
        market: str = "CN",
    ) -> AggregatedEvidence:
        """
        Collect data from multiple providers and cross-validate.

        Args:
            query: Search query (symbol, keyword, etc.)
            data_type: Type of data to collect (news, reports, announcements, prices)
            max_sources: Maximum number of sources to query
            market: Market code (CN, HK, US)

        Returns:
            AggregatedEvidence with cross-validated results
        """
        if not self._registry:
            return AggregatedEvidence(data_type=data_type)

        # Get providers sorted by priority
        providers = self._select_providers(data_type, market, max_sources)
        if not providers:
            return AggregatedEvidence(data_type=data_type)

        # Collect from each provider
        all_items = []
        source_names = []
        errors = []

        # Map data_type to provider method
        method_map = {
            "news": "get_news",
            "reports": "get_reports",
            "announcements": "get_announcements",
            "prices": "get_prices",
            "fund_flow": "get_fund_flow",
        }
        method_name = method_map.get(data_type, "get_news")

        def _fetch_one(provider):
            method = getattr(provider, method_name, None)
            if method is None:
                return None
            return provider.name, method({"symbol": query, "limit": 20})

        with ThreadPoolExecutor(max_workers=min(len(providers), 4)) as pool:
            futures = {pool.submit(_fetch_one, p): p for p in providers}
            for future in as_completed(futures, timeout=15):
                try:
                    result = future.result()
                    if result:
                        name, items = result
                        if items:
                            all_items.extend(items)
                            source_names.append(name)
                except Exception as e:
                    provider = futures[future]
                    errors.append(f"{provider.name}: {e}")
                    logger.debug("Provider %s failed: %s", provider.name, e)

        if not all_items:
            return AggregatedEvidence(data_type=data_type)

        # Deduplicate across sources
        deduped = self._cross_source_dedup(all_items, data_type)

        # Calculate confidence based on source agreement
        confidence, confirmed = self._calculate_confidence(deduped, source_names)

        # Detect contradictions
        contradictions = self._detect_contradictions(deduped, data_type)

        result = AggregatedEvidence(
            data_type=data_type,
            items=deduped,
            sources=source_names,
            confidence=confidence,
            confirmed_by=confirmed,
            contradictions=contradictions,
        )

        if confirmed >= 2:
            logger.info(
                "多源确认: %s 数据来自 %d 个源, 置信度 %.2f",
                data_type,
                confirmed,
                confidence,
            )

        return result

    def _select_providers(self, data_type: str, market: str, max_sources: int) -> list:
        """Select top N providers for the given data type and market"""
        if not self._registry:
            return []

        try:
            # Get all providers that support this data type and market
            all_providers = self._registry.list_providers()
            candidates = []
            for p_info in all_providers:
                p = self._registry.get(p_info.get("name", ""))
                if p and hasattr(p, "data_types") and data_type in p.data_types:
                    if hasattr(p, "markets") and market in p.markets:
                        candidates.append(p)

            # Sort by priority/trust level
            candidates.sort(key=lambda p: getattr(p, "priority", 99))
            return candidates[:max_sources]
        except Exception as e:
            logger.debug("Provider selection failed: %s", e)
            return []

    def _cross_source_dedup(
        self, items: List[Dict[str, Any]], data_type: str
    ) -> List[Dict[str, Any]]:
        """Deduplicate items across different sources"""
        if not items:
            return []

        seen = {}
        for item in items:
            # Create dedup key based on data type
            if data_type == "news":
                key = self._news_dedup_key(item)
            elif data_type == "announcements":
                key = self._announcement_dedup_key(item)
            elif data_type == "reports":
                key = self._report_dedup_key(item)
            else:
                key = self._generic_dedup_key(item)

            if key not in seen:
                seen[key] = item
                seen[key]["_source_count"] = 1
                seen[key]["_sources"] = [item.get("source", "unknown")]
            else:
                seen[key]["_source_count"] += 1
                src = item.get("source", "unknown")
                if src not in seen[key]["_sources"]:
                    seen[key]["_sources"].append(src)

        return list(seen.values())

    def _news_dedup_key(self, item: Dict[str, Any]) -> str:
        """Create dedup key for news items"""
        title = (item.get("title") or "").strip()
        dt = (item.get("datetime") or item.get("published_at") or "")[:10]
        return f"{title}|{dt}"

    def _announcement_dedup_key(self, item: Dict[str, Any]) -> str:
        """Create dedup key for announcements"""
        title = (item.get("title") or "").strip()
        symbol = (item.get("symbol") or item.get("stock_code") or "").strip()
        dt = (item.get("datetime") or item.get("published_at") or "")[:10]
        return f"{symbol}|{title}|{dt}"

    def _report_dedup_key(self, item: Dict[str, Any]) -> str:
        """Create dedup key for research reports"""
        title = (item.get("title") or "").strip()
        institution = (item.get("institution") or item.get("org") or "").strip()
        return f"{institution}|{title}"

    def _generic_dedup_key(self, item: Dict[str, Any]) -> str:
        """Generic dedup key"""
        title = (item.get("title") or "").strip()
        dt = (item.get("datetime") or "")[:10]
        return f"{title}|{dt}"

    def _calculate_confidence(
        self,
        items: List[Dict[str, Any]],
        source_names: List[str],
    ) -> Tuple[float, int]:
        """
        Calculate confidence based on multi-source confirmation.

        Returns:
            (confidence, confirmed_source_count)
        """
        if not items:
            return 0.0, 0

        # Count items confirmed by multiple sources
        multi_source_items = [i for i in items if i.get("_source_count", 1) >= 2]
        confirmed = len(
            set(src for item in multi_source_items for src in item.get("_sources", []))
        )

        if confirmed >= 2:
            # Multi-source confirmation
            confidence = min(
                self.SINGLE_SOURCE_CONFIDENCE
                + (confirmed - 1) * self.CONFIRMATION_BOOST,
                self.MAX_CONFIDENCE,
            )
        else:
            confidence = self.SINGLE_SOURCE_CONFIDENCE

        return confidence, confirmed

    def _detect_contradictions(
        self,
        items: List[Dict[str, Any]],
        data_type: str,
    ) -> List[str]:
        """Detect contradictions between sources"""
        contradictions = []

        if data_type == "news":
            # Check for sentiment contradictions
            sentiments = {}
            for item in items:
                src = item.get("source", "unknown")
                sentiment = item.get("sentiment")
                if sentiment is not None:
                    sentiments[src] = sentiment

            if len(sentiments) >= 2:
                values = list(sentiments.values())
                if max(values) - min(values) > 0.5:
                    contradictions.append(f"情绪分歧: {sentiments}")

        return contradictions


# Module-level instance
_aggregator: Optional[EvidenceAggregator] = None


def get_evidence_aggregator(registry=None) -> EvidenceAggregator:
    """Get or create the global EvidenceAggregator"""
    global _aggregator
    if _aggregator is None:
        _aggregator = EvidenceAggregator(registry)
    return _aggregator
