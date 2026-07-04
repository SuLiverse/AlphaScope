"""文档分块器 - 将长文本切分为适合向量检索的 chunks"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


class TextChunker:
    """文本分块器

    支持按段落、句子、固定长度切分, 每个 chunk 带元数据。
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 50,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk_text(
        self,
        text: str,
        metadata: Optional[dict] = None,
    ) -> list[dict]:
        """将文本切分为 chunks

        Args:
            text: 原始文本
            metadata: 附加元数据 (source, symbol, doc_type 等)

        Returns:
            chunk 列表, 每个包含 text, chunk_id, metadata
        """
        if not text or len(text.strip()) < self.min_chunk_size:
            return []

        metadata = metadata or {}
        # 先按段落切分
        paragraphs = self._split_paragraphs(text)
        chunks = []
        current_text = ""

        for para in paragraphs:
            if len(current_text) + len(para) <= self.chunk_size:
                current_text += para + "\n"
            else:
                if current_text.strip():
                    chunks.append(self._make_chunk(current_text.strip(), len(chunks), metadata))
                # 处理段落本身超长的情况
                if len(para) > self.chunk_size:
                    sub_chunks = self._split_long_text(para, metadata, len(chunks))
                    chunks.extend(sub_chunks)
                    current_text = ""
                else:
                    current_text = para + "\n"

        if current_text.strip() and len(current_text.strip()) >= self.min_chunk_size:
            chunks.append(self._make_chunk(current_text.strip(), len(chunks), metadata))

        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """按段落切分"""
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_long_text(self, text: str, metadata: dict, start_idx: int) -> list[dict]:
        """切分超长段落"""
        chunks = []
        sentences = re.split(r"[。！？.!?\n]", text)
        current = ""
        for sent in sentences:
            if not sent.strip():
                continue
            if len(current) + len(sent) <= self.chunk_size:
                current += sent + "。"
            else:
                if current.strip():
                    chunks.append(self._make_chunk(current.strip(), start_idx + len(chunks), metadata))
                current = sent + "。"
        if current.strip():
            chunks.append(self._make_chunk(current.strip(), start_idx + len(chunks), metadata))
        return chunks

    def _make_chunk(self, text: str, index: int, metadata: dict) -> dict:
        """生成 chunk 条目"""
        chunk_id = hashlib.md5(f"{metadata.get('source', '')}_{index}_{text[:100]}".encode()).hexdigest()[:16]
        return {
            "text": text,
            "chunk_id": chunk_id,
            "chunk_index": index,
            "char_count": len(text),
            **metadata,
        }
