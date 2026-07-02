"""证据链管理 API — CRUD + 证据链构建"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


# ============== Request Models ==============


class EvidenceCreateRequest(BaseModel):
    evidence_type: str = Field(
        description="证据类型: news/report/announcement/price/fund_flow/fundamental/other"
    )
    title: str = Field(description="证据标题")
    source: str = Field(description="数据来源")
    claim: str = Field(default="", description="支撑的结论")
    content_summary: str = Field(default="", description="内容摘要")
    symbols: list[str] = Field(default_factory=list, description="关联股票")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="可信度")
    source_url: str = Field(default="", description="原始链接")
    data_date: str = Field(default="", description="数据日期")
    relevance: float = Field(default=0.5, ge=0.0, le=1.0, description="相关度")


class EvidenceSearchRequest(BaseModel):
    query: str = Field(description="搜索关键词")
    limit: int = Field(default=20, description="最大结果数")


class ChainBuildRequest(BaseModel):
    evidence: list[dict] = Field(description="证据列表")
    agent_signals: list[dict] | None = Field(default=None, description="Agent 信号列表")


# ============== Endpoints ==============


@router.get("")
async def list_evidence(
    evidence_type: str | None = None, symbol: str | None = None, limit: int = Query(50, ge=1, le=500)
):
    """证据列表"""
    from backend.evidence_store import list_evidence as _list

    items = _list(evidence_type=evidence_type, symbol=symbol, limit=limit)
    return ApiResponse(success=True, data={"evidence": items, "total": len(items)})


# 注意路由顺序: 字面 /aggregate 必须先于参数 /{evidence_id}, 否则被吞(id="aggregate")。
@router.get("/aggregate")
async def aggregate_evidence(
    symbol: str, data_type: str = "news", max_sources: int = Query(3, ge=1, le=5)
):
    """多源证据聚合 + 交叉验证(激活沉睡的 evidence_aggregator)。

    并行查多个 provider, 跨源去重 + 矛盾检测, 返回 AggregatedEvidence(is_multi_source/
    is_high_confidence/items/source_names/conflicts)。不改主证据链路, 独立诊断/研究端点。
    """
    try:
        from backend.quality.evidence_aggregator import get_evidence_aggregator

        agg = get_evidence_aggregator()
        result = agg.collect_and_validate(symbol, data_type=data_type, max_sources=max_sources)
        return ApiResponse(success=True, data=result.to_dict())
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/{evidence_id}")
async def get_evidence(evidence_id: str):
    """证据详情"""
    from backend.evidence_store import get_evidence as _get

    item = _get(evidence_id)
    if not item:
        return ApiResponse(success=False, error="证据不存在")
    return ApiResponse(success=True, data=item)


@router.post("")
async def create_evidence(req: EvidenceCreateRequest):
    """创建证据"""
    from backend.evidence_store import save_evidence as _save

    item = _save(
        evidence_type=req.evidence_type,
        title=req.title,
        source=req.source,
        claim=req.claim,
        content_summary=req.content_summary,
        symbols=req.symbols,
        confidence=req.confidence,
        source_url=req.source_url,
        data_date=req.data_date,
        relevance=req.relevance,
    )
    return ApiResponse(success=True, data=item, message="证据创建成功")


@router.post("/search")
async def search_evidence(req: EvidenceSearchRequest):
    """搜索证据"""
    from backend.evidence_store import search_evidence as _search

    items = _search(req.query, limit=req.limit)
    return ApiResponse(
        success=True,
        data={"query": req.query, "results": items, "total": len(items)},
    )


@router.post("/chain")
async def build_chain(req: ChainBuildRequest):
    """构建证据链"""
    from backend.quality.evidence_chain import build_evidence_chain

    chain = build_evidence_chain(req.evidence, agent_signals=req.agent_signals)
    return ApiResponse(success=True, data=chain)


@router.delete("/{evidence_id}")
async def delete_evidence(evidence_id: str):
    """删除证据"""
    from backend.evidence_store import delete_evidence as _delete

    deleted = _delete(evidence_id)
    if not deleted:
        return ApiResponse(success=False, error="证据不存在")
    return ApiResponse(success=True, data={"deleted": evidence_id})


# ============== Evidence Chain Graph (v1.1.4) ==============


class ChainGraphRequest(BaseModel):
    evidence: list[dict] = Field(default_factory=list, description="证据列表")
    symbol: str | None = Field(default=None, description="股票代码过滤")


@router.post("/chain/graph")
async def build_chain_graph(req: ChainGraphRequest):
    """构建证据链可视化图谱数据 (v1.1.4)

    返回 nodes 和 edges 用于前端图谱渲染。
    """
    nodes = []
    edges = []
    pillar_colors = {
        "fundamental": "#6366f1",
        "quant": "#10b981",
        "sentiment": "#f59e0b",
        "liquidity": "#06b6d4",
        "default": "#737373",
    }

    # Build from provided evidence
    for i, ev in enumerate(req.evidence):
        ev_type = ev.get("evidence_type", ev.get("type", "other"))
        pillar = _classify_pillar(ev_type)
        nodes.append(
            {
                "id": ev.get("id", f"ev_{i}"),
                "label": ev.get("title", f"证据 {i + 1}"),
                "type": ev_type,
                "pillar": pillar,
                "color": pillar_colors.get(pillar, pillar_colors["default"]),
                "confidence": ev.get("confidence", 0.5),
                "source": ev.get("source", ""),
            }
        )

    # Build edges from shared symbols or claims
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            ev_i = req.evidence[i] if i < len(req.evidence) else {}
            ev_j = req.evidence[j] if j < len(req.evidence) else {}
            shared_symbols = set(ev_i.get("symbols", [])) & set(ev_j.get("symbols", []))
            if shared_symbols or _related_claims(
                ev_i.get("claim", ""), ev_j.get("claim", "")
            ):
                edges.append(
                    {
                        "source": nodes[i]["id"],
                        "target": nodes[j]["id"],
                        "weight": len(shared_symbols) * 0.3 + 0.2,
                    }
                )

    # Also try loading from evidence store if no evidence provided
    if not nodes and req.symbol:
        try:
            from backend.evidence_store import list_evidence as _list

            items = _list(symbol=req.symbol, limit=20)
            for i, ev in enumerate(items):
                ev_type = ev.get("evidence_type", "other")
                pillar = _classify_pillar(ev_type)
                nodes.append(
                    {
                        "id": ev.get("id", f"ev_{i}"),
                        "label": ev.get("title", f"证据 {i + 1}"),
                        "type": ev_type,
                        "pillar": pillar,
                        "color": pillar_colors.get(pillar, pillar_colors["default"]),
                        "confidence": ev.get("confidence", 0.5),
                        "source": ev.get("source", ""),
                    }
                )
        except Exception:
            pass

    return ApiResponse(
        success=True,
        data={
            "nodes": nodes,
            "edges": edges,
            "pillars": list(pillar_colors.keys()),
        },
    )


def _classify_pillar(evidence_type: str) -> str:
    """Classify evidence type into a pillar category."""
    mapping = {
        "fundamental": "fundamental",
        "report": "fundamental",
        "announcement": "fundamental",
        "price": "quant",
        "technical": "quant",
        "fund_flow": "liquidity",
        "news": "sentiment",
        "sentiment": "sentiment",
        "other": "default",
    }
    return mapping.get(evidence_type, "default")


def _related_claims(claim_a: str, claim_b: str) -> bool:
    """Simple check if two claims are related (share keywords)."""
    if not claim_a or not claim_b:
        return False
    words_a = set(claim_a.split())
    words_b = set(claim_b.split())
    common = words_a & words_b
    return len(common) >= 2
