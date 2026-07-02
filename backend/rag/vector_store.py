"""向量存储层 - 基于 ChromaDB 的向量检索"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.project_paths import CACHE_DIR

CHROMA_DIR = CACHE_DIR / "chroma_db"


class _OpenAIEmbeddingFunction:
    """Chroma embedding adapter backed by a configured OpenAI-compatible provider."""

    def __init__(
        self, *, provider_id: str, model: str, base_url: str, api_key: str
    ) -> None:
        self.provider_id = provider_id
        self.model = model
        self.base_url = base_url
        self.api_key = api_key

    def __call__(self, input):  # Chroma validates this exact parameter name.
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=30.0)
        response = client.embeddings.create(model=self.model, input=list(input))
        return [item.embedding for item in response.data]


def _configured_embedding_function() -> tuple[Optional[_OpenAIEmbeddingFunction], str]:
    try:
        from backend.settings_store import get_app_preferences, get_provider

        knowledge = get_app_preferences().get("knowledge", {})
        if not knowledge.get("enabled", True):
            return None, "default"

        provider_id = str(knowledge.get("embedding_provider_id") or "").strip()
        model = str(knowledge.get("embedding_model") or "").strip()
        if not provider_id or not model:
            return None, "default"

        provider = get_provider(provider_id)
        if not provider or not provider.get("enabled", True):
            return None, "default"
        base_url = str(provider.get("base_url") or "").strip()
        api_key = str(provider.get("api_key") or "").strip()
        if not base_url or not api_key:
            return None, "default"

        signature = f"{provider_id}:{model}:{base_url}"
        return (
            _OpenAIEmbeddingFunction(
                provider_id=provider_id,
                model=model,
                base_url=base_url,
                api_key=api_key,
            ),
            signature,
        )
    except Exception as exc:
        logger.debug("自定义嵌入模型配置读取失败，回退 Chroma 默认 embedding: %s", exc)
        return None, "default"


class VectorStore:
    """ChromaDB 向量存储管理

    Thread-safe singleton with double-checked locking.
    """

    _instance: Optional["VectorStore"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "VectorStore":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._collections: dict = {}
        self._collection_signatures: dict[str, str] = {}

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb
            except ImportError:
                logger.warning(
                    "chromadb 未安装，RAG 向量检索功能不可用。安装命令: pip install chromadb==0.6.3"
                )
                return None
            self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        return self._client

    def get_collection(self, name: str):
        """获取或创建 collection"""
        embedding_function, signature = _configured_embedding_function()
        if (
            name not in self._collections
            or self._collection_signatures.get(name) != signature
        ):
            client = self._get_client()
            if client is None:
                raise RuntimeError("chromadb 未安装，无法创建向量集合")
            kwargs: dict[str, Any] = {
                "name": name,
                "metadata": {"hnsw:space": "cosine"},
            }
            if embedding_function is not None:
                kwargs["embedding_function"] = embedding_function
            self._collections[name] = client.get_or_create_collection(**kwargs)
            self._collection_signatures[name] = signature
        return self._collections[name]

    def add_documents(
        self,
        collection_name: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
    ) -> None:
        """添加文档到向量库"""
        collection = self.get_collection(collection_name)
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        logger.info(
            "向量库 %s 添加 %d 个文档",
            collection_name,
            len(documents),
        )

    def query(
        self,
        collection_name: str,
        query_text: str,
        n_results: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """查询相似文档"""
        collection = self.get_collection(collection_name)
        kwargs = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = collection.query(**kwargs)

        # ChromaDB 无命中或返回结构异常时 documents 可能是 [] 或缺键 — 防索引越界。
        doc_batches = results.get("documents") or []
        if not doc_batches:
            return []
        meta_batches = results.get("metadatas") or []
        dist_batches = results.get("distances") or []
        id_batches = results.get("ids") or []
        first_docs = doc_batches[0] if doc_batches else []
        first_meta = meta_batches[0] if meta_batches else []
        first_dist = dist_batches[0] if dist_batches else []
        first_ids = id_batches[0] if id_batches else []

        docs = []
        for i in range(len(first_docs)):
            docs.append(
                {
                    "text": first_docs[i],
                    "metadata": first_meta[i] if i < len(first_meta) else {},
                    "distance": first_dist[i] if i < len(first_dist) else 0,
                    "id": first_ids[i] if i < len(first_ids) else "",
                }
            )
        return docs

    def get_collection_stats(self) -> dict:
        """获取所有 collection 统计"""
        client = self._get_client()
        if client is None:
            return {}
        stats = {}
        for col in client.list_collections():
            stats[col.name] = col.count()
        return stats
