"""Lightweight agent memory backed by the local document store."""

from __future__ import annotations

from typing import Any


def build_agent_memory_context(symbol: str = "", stock_name: str = "", limit: int = 5) -> str:
    """Return recent agent memory snippets for the current analysis target."""
    try:
        from backend.file_store import search_documents

        query = " ".join(part for part in (stock_name, symbol, "agent memory") if part)
        docs = search_documents(query or "agent memory", limit=limit)
        memory_docs = [doc for doc in docs if (doc.get("metadata") or {}).get("doc_type") == "agent_memory"]
    except Exception:
        return ""

    if not memory_docs:
        return ""

    lines = ["【Agent 记忆】以下是历史分析中可复用的本地记忆，请只作为参考线索，关键结论仍需重新核验。"]
    for index, doc in enumerate(memory_docs[:limit], 1):
        metadata = doc.get("metadata") or {}
        title = doc.get("title", "")
        created_at = doc.get("created_at", "")
        summary = str(metadata.get("summary") or metadata.get("signal") or "").strip()
        lines.append(f"[M{index}] {title} | {created_at} | {summary}")
    return "\n".join(lines)


def save_agent_run_memory(
    stock_data: dict[str, Any],
    agent_results: dict[str, dict[str, Any]],
) -> int:
    """Persist one compact memory document per successful agent result."""
    try:
        from backend.file_store import save_chunks, save_document
    except Exception:
        return 0

    symbol = str(stock_data.get("symbol") or "").strip()
    stock_name = str(stock_data.get("name") or "").strip()
    saved = 0
    for agent_key, result in agent_results.items():
        if not result.get("ok"):
            continue
        title = f"Agent memory - {stock_name or symbol or 'unknown'} - {result.get('name') or agent_key}"
        reason = str(result.get("reason") or "").strip()
        risks = result.get("risks") or []
        evidence = result.get("evidence") or []
        content = "\n".join(
            [
                f"target: {stock_name} {symbol}".strip(),
                f"agent: {result.get('name') or agent_key}",
                f"signal: {result.get('signal', '')}",
                f"confidence: {result.get('confidence', '')}",
                f"reason: {reason}",
                f"risks: {', '.join(map(str, risks[:3])) if isinstance(risks, list) else risks}",
                f"evidence: {evidence}",
            ]
        )
        metadata = {
            "doc_type": "agent_memory",
            "symbol": symbol,
            "stock_name": stock_name,
            "agent_id": agent_key,
            "agent_name": result.get("name") or agent_key,
            "signal": result.get("signal", ""),
            "confidence": result.get("confidence", 0),
            "summary": reason[:160],
        }
        try:
            doc = save_document(
                title=title,
                source_type="agent_memory",
                metadata=metadata,
            )
            if doc:
                save_chunks(doc["id"], [content])
                saved += 1
        except Exception:
            continue
    return saved
