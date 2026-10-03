"""TextChunker 回归测试 — 短文档不丢整篇、短尾不丢弃、句读保留小数不破坏。"""

from __future__ import annotations

from backend.rag.chunker import TextChunker


def test_short_document_returns_single_chunk():
    """非空短文档整篇输出单条 chunk, 不再因 < min_chunk_size 返回 []。"""
    c = TextChunker()
    chunks = c.chunk_text("很短的文档。")
    assert len(chunks) == 1
    assert chunks[0]["text"] == "很短的文档。"


def test_empty_or_whitespace_text_returns_empty():
    """纯空白/空文本仍返回空列表。"""
    c = TextChunker()
    assert c.chunk_text("") == []
    assert c.chunk_text("   \n\n   ") == []


def test_decimal_not_corrupted_in_long_paragraph():
    """超长单段切分保留原始句读: 12.50 不被破坏成 12。50。"""
    c = TextChunker()
    para = "支撑位在12.50元附近，随后回落到11.20元。" + "填充内容。" * 100
    chunks = c.chunk_text(para)

    assert chunks, "超长段落必须产出 chunks"
    joined = "".join(t["text"] for t in chunks)
    assert "12.50元附近，随后回落到11.20元。" in joined
    assert "12。50" not in joined
    assert "11。20" not in joined


def test_short_tail_merged_into_last_chunk():
    """末段过短时并入最后一个 chunk (换行连接), 不再静默丢弃。"""
    c = TextChunker()
    text = "句子内容。" * 120 + "\n\n尾。"
    chunks = c.chunk_text(text)

    assert len(chunks) >= 2
    assert chunks[-1]["text"].endswith("\n尾。")
    assert "尾。" in chunks[-1]["text"]
    # 并入后 char_count 与文本保持一致
    assert chunks[-1]["char_count"] == len(chunks[-1]["text"])


def test_normal_tail_still_own_chunk():
    """足够长的尾段仍独立成 chunk, 不受短尾合并影响。"""
    c = TextChunker()
    text = "句子内容。" * 120 + "\n\n" + "结尾段落内容。" * 20
    chunks = c.chunk_text(text)

    assert len(chunks) >= 2
    assert chunks[-1]["text"].startswith("结尾段落内容。")
