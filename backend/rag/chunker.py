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
        if not text or not text.strip():
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

        # 短尾处理: 末段非空即收, 不再因 < min_chunk_size 丢弃;
        # 若尾段过短且已有 chunks, 并入最后一个 chunk, 避免信息割裂。
        tail = current_text.strip()
        if tail:
            if len(tail) < self.min_chunk_size and chunks:
                last = chunks[-1]
                last["text"] = last["text"] + "\n" + tail
                last["char_count"] = len(last["text"])
            else:
                chunks.append(self._make_chunk(tail, len(chunks), metadata))

        # 非空文本若仍产出 0 chunks (如整篇短文档), 输出单条整文 chunk
        if not chunks:
            chunks.append(self._make_chunk(text.strip(), 0, metadata))

        return chunks

    def _split_paragraphs(self, text: str) -> list[str]:
        """按段落切分"""
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_long_text(self, text: str, metadata: dict, start_idx: int) -> list[dict]:
        """切分超长段落

        用捕获组切分并成对重接原句读, 保留原始分隔符 —
        避免把 "12.50" 这类小数破坏成 "12。50"。
        """
        chunks = []
        # 捕获组使 re.split 保留分隔符, parts 形如 [句子, 分隔符, 句子, 分隔符, ...]
        parts = re.split(r"([。！？.!?\n])", text)
        sentences: list[str] = []
        for i in range(0, len(parts), 2):
            sent = parts[i]
            sep = parts[i + 1] if i + 1 < len(parts) else ""
            if not sent.strip():
                # 连续句读产生的空句子段: 把分隔符并回前一句, 避免丢失
                if sep and sentences:
                    sentences[-1] += sep
                continue
            sentences.append(sent + sep)

        current = ""
        for sent in sentences:
            if len(current) + len(sent) <= self.chunk_size:
                current += sent
            else:
                if current.strip():
                    chunks.append(self._make_chunk(current.strip(), start_idx + len(chunks), metadata))
                current = sent
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
