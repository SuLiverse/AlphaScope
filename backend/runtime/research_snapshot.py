"""Deterministic metadata for reproducible research runs."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time as datetime_time
from typing import Any, Iterable


def normalize_date(value: Any) -> str:
    """Return ``YYYY-MM-DD`` for supported date/datetime strings, else empty."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = text[:10].replace("/", "-")
    try:
        return date.fromisoformat(candidate).isoformat()
    except ValueError:
        if len(text) == 8 and text.isdigit():
            try:
                return datetime.strptime(text, "%Y%m%d").date().isoformat()
            except ValueError:
                pass
    return ""


def evidence_on_or_before(data_date: Any, as_of: Any) -> bool:
    """Historical cutoffs exclude undated evidence to prevent look-ahead leakage."""
    cutoff = normalize_date(as_of)
    if not cutoff:
        return True
    evidence_date = normalize_date(data_date)
    return bool(evidence_date) and evidence_date <= cutoff


def as_of_timestamp(value: Any) -> float | None:
    """Return local end-of-day timestamp for deterministic historical freshness."""
    normalized = normalize_date(value)
    if not normalized:
        return None
    return datetime.combine(date.fromisoformat(normalized), datetime_time.max).timestamp()


def build_research_snapshot(
    stock_data: dict[str, Any] | None,
    evidence_pool: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build stable metadata and a content hash for one research data snapshot."""
    stock = stock_data or {}
    evidence = [dict(item) for item in evidence_pool or [] if isinstance(item, dict)]
    requested_as_of = normalize_date(stock.get("as_of"))
    price_data_date = normalize_date(stock.get("price_data_date"))
    question = str(stock.get("research_question") or "").strip()

    evidence_rows = []
    dated_values = []
    undated_count = 0
    for item in evidence:
        data_date = normalize_date(item.get("published_at") or item.get("data_date"))
        if data_date:
            dated_values.append(data_date)
        else:
            undated_count += 1
        evidence_rows.append(
            {
                "evidence_id": str(item.get("evidence_id") or item.get("id") or ""),
                "source": str(item.get("source") or "unknown"),
                "data_date": data_date,
                "content": str(item.get("preview") or item.get("claim") or item.get("title") or "").strip(),
            }
        )

    effective_as_of = requested_as_of or price_data_date or date.today().isoformat()
    canonical = {
        "symbol": str(stock.get("symbol") or ""),
        "as_of": effective_as_of,
        "price_data_date": price_data_date,
        "price_fingerprint": {
            key: stock.get(key) for key in ("close", "day_change", "period_change", "volume", "ma5", "ma20", "ma60")
        },
        "research_question": question,
        "factor_data_policy": str(stock.get("factor_data_policy") or "not_recorded"),
        "evidence": sorted(
            evidence_rows,
            key=lambda row: (row["evidence_id"], row["source"], row["data_date"], row["content"]),
        ),
    }
    digest = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()[:16]

    warnings = []
    if not requested_as_of:
        warnings.append("未显式指定数据截止日；后续重跑可能检索到更新数据。")
    if undated_count:
        warnings.append(f"{undated_count} 条证据缺少日期，无法证明其满足历史截止约束。")
    if not price_data_date:
        warnings.append("行情快照缺少明确数据日期。")

    return {
        "snapshot_id": digest,
        "requested_as_of": requested_as_of,
        "effective_as_of": effective_as_of,
        "cutoff_enforced": bool(requested_as_of),
        "price_data_date": price_data_date,
        "latest_evidence_date": max(dated_values, default=""),
        "evidence_count": len(evidence_rows),
        "undated_evidence_count": undated_count,
        "research_question": question,
        "factor_data_policy": str(stock.get("factor_data_policy") or "not_recorded"),
        "warnings": warnings,
    }
