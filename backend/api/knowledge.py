"""知识库管理 API — 文件上传、文档管理、语义搜索"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi import APIRouter, File, Query, UploadFile
from pydantic import BaseModel, Field

from backend.project_paths import UPLOADS_DIR
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

SUPPORTED_FORMATS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".csv",
    ".txt",
    ".md",
    ".json",
}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


# ============== Request Models ==============


class SearchRequest(BaseModel):
    query: str = Field(description="搜索关键词")
    limit: int = Field(default=20, description="最大结果数")


def _sanitize_upload_filename(filename: str) -> str:
    raw_name = Path(filename or "").name.strip()
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name)
    safe_name = safe_name.strip("._-")
    if not safe_name:
        raise ValueError("文件名无效")
    return safe_name


# ============== Endpoints ==============


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文件 → 解析 → 分块 → 索引"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        return ApiResponse(
            success=False,
            error=f"不支持的文件格式: {suffix}，支持: {', '.join(SUPPORTED_FORMATS)}",
        )

    try:
        safe_filename = _sanitize_upload_filename(file.filename or "")
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        return ApiResponse(success=False, error="文件大小超过 20MB 限制")

    # 保存到磁盘
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    c_hash = hashlib.sha256(content).hexdigest()[:16]
    save_name = f"{c_hash}_{safe_filename}"
    save_path = UPLOADS_DIR / save_name
    save_path.write_bytes(content)

    # 处理并索引
    from backend.rag.document_pipeline import get_document_pipeline

    pipeline = get_document_pipeline()
    doc = pipeline.process_and_persist(
        str(save_path), metadata={"original_name": safe_filename}
    )

    if not doc:
        return ApiResponse(success=False, error="文件处理失败")

    return ApiResponse(
        success=True,
        data={
            "doc_id": doc.doc_id,
            "filename": doc.filename,
            "chunks": doc.chunk_count,
            "processing_time_ms": doc.processing_time_ms,
            "file_size": len(content),
        },
        message="文件上传并处理成功",
    )


@router.get("/documents")
async def list_documents(source_type: str | None = None, limit: int = Query(50, ge=1, le=500)):
    """文档列表"""
    from backend.file_store import list_documents as _list

    docs = _list(source_type=source_type, limit=limit)
    return ApiResponse(success=True, data={"documents": docs, "total": len(docs)})


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    """文档详情 + chunks"""
    from backend.file_store import get_chunks, get_document as _get

    doc = _get(doc_id)
    if not doc:
        return ApiResponse(success=False, error="文档不存在")

    chunks = get_chunks(doc_id)
    doc["chunks"] = chunks
    return ApiResponse(success=True, data=doc)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档 + chunks"""
    from backend.file_store import delete_document as _delete

    deleted = _delete(doc_id)
    if not deleted:
        return ApiResponse(success=False, error="文档不存在")
    return ApiResponse(success=True, data={"deleted": doc_id})


@router.post("/search")
async def search_knowledge(req: SearchRequest):
    """搜索知识库 — ChromaDB 语义搜索 / SQLite 降级"""
    results = []

    # 尝试语义搜索（ChromaDB）
    try:
        from backend.rag.vector_store import VectorStore

        store = VectorStore()
        vector_results = store.query(
            collection_name="user_documents",
            query_text=req.query,
            n_results=req.limit,
        )
        results = [
            {
                "text": r["text"],
                "metadata": r["metadata"],
                "distance": r["distance"],
                "source": "vector",
            }
            for r in vector_results
        ]
    except (RuntimeError, Exception):
        # 降级到 SQLite 关键词搜索
        from backend.file_store import search_documents

        docs = search_documents(req.query, limit=req.limit)
        results = [
            {
                "text": d["title"],
                "metadata": {"doc_id": d["id"], "source_type": d["source_type"]},
                "distance": 1.0,
                "source": "sqlite",
            }
            for d in docs
        ]

    return ApiResponse(
        success=True,
        data={"query": req.query, "results": results, "total": len(results)},
    )
