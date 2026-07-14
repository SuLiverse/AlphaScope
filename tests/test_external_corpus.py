"""Tests for the safe external strategy-corpus audit/import boundary."""

from __future__ import annotations

import json

import pytest


def _make_corpus(tmp_path, *, license_file: bool = False):
    root = tmp_path / "corpus"
    first = root / "articles" / "001_etf_rotation"
    second = root / "articles" / "002_duplicate"
    for article in (first, second):
        (article / "code").mkdir(parents=True)
        (article / "meta.json").write_text(json.dumps({"title": "ETF RSRS Rotation"}), encoding="utf-8")
    content = """# ETF RSRS Rotation

This is prose about an ETF rotation research idea.

```python
print('external code must not be imported')
```
"""
    (first / "content.md").write_text(content, encoding="utf-8")
    (second / "content.md").write_text(content, encoding="utf-8")
    (first / "code" / "snippet.py").write_text("def broken(:\n", encoding="utf-8")
    (second / "code" / "snippet.py").write_text("get_price('510300.XSHG')\n", encoding="utf-8")
    if license_file:
        (root / "LICENSE").write_text("MIT License", encoding="utf-8")
    return root, first, second


def test_audit_classifies_hashes_and_never_exposes_code(tmp_path):
    from backend.rag.external_corpus import audit_corpus

    root, _first, _second = _make_corpus(tmp_path)
    manifest = audit_corpus(root, repository_url="https://example.test/corpus", generated_at="2026-01-01T00:00:00Z")

    assert manifest["summary"]["articles"] == 2
    first = manifest["articles"][0]
    second = manifest["articles"][1]
    assert "etf_rotation" in first["categories"]
    assert first["static_analysis"]["syntax_errors"] == 1
    assert "license_unknown" in first["risk"]["tags"]
    assert "provenance_missing" in first["risk"]["tags"]
    assert first["candidate_tier"] == "B"  # syntax-invalid code blocks cannot lead the implementation queue
    assert second["duplicate_of"] == first["id"]
    assert "external code must not be imported" not in json.dumps(manifest, ensure_ascii=False)
    assert manifest["manifest_sha256"]


def test_audit_fingerprint_ignores_reporting_timestamp(tmp_path):
    from backend.rag.external_corpus import audit_corpus

    root, _first, _second = _make_corpus(tmp_path)
    first = audit_corpus(root, generated_at="2026-01-01T00:00:00Z")
    second = audit_corpus(root, generated_at="2026-01-02T00:00:00Z")

    assert first["manifest_sha256"] == second["manifest_sha256"]


@pytest.mark.parametrize("marker", ["`", "~"])
def test_long_fence_is_not_closed_by_shorter_marker(marker):
    from backend.rag.external_corpus import _strip_fenced_code

    opening = marker * 4
    shorter = marker * 3
    closing = marker * 5
    prose = _strip_fenced_code(
        "\n".join(
            [
                "# Safe heading",
                "",
                "Intro prose.",
                "",
                f"{opening}python",
                'secret = "must never be imported"',
                shorter,
                'literal_marker = "also code"',
                closing,
                "",
                "Closing prose.",
            ]
        )
    )

    assert "Intro prose." in prose
    assert "Closing prose." in prose
    assert "secret" not in prose
    assert "literal_marker" not in prose


@pytest.mark.parametrize(
    "license_text",
    [
        "Mozilla Public License Version 2.0",
        "GNU AFFERO GENERAL PUBLIC LICENSE",
        "GNU LESSER GENERAL PUBLIC LICENSE",
    ],
)
def test_common_copyleft_licenses_are_restricted(tmp_path, license_text):
    from backend.rag.external_corpus import audit_corpus

    root, _first, _second = _make_corpus(tmp_path, license_file=True)
    (root / "LICENSE").write_text(license_text, encoding="utf-8")

    assert audit_corpus(root)["source"]["license_status"] == "restricted"


def test_import_rejects_unknown_license_without_explicit_confirmation(tmp_path):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path)
    manifest = audit_corpus(root)
    with pytest.raises(ValueError, match="confirm_unverified"):
        import_audited_corpus(manifest, root)


def test_import_rejects_restricted_license_even_with_confirmation(tmp_path):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path, license_file=True)
    (root / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE", encoding="utf-8")
    manifest = audit_corpus(root)

    assert manifest["source"]["license_status"] == "restricted"
    with pytest.raises(ValueError, match="Restricted"):
        import_audited_corpus(manifest, root, confirm_unverified=True)


def test_mpl_corpus_is_restricted_and_cannot_be_imported(tmp_path, monkeypatch):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path, license_file=True)
    (root / "LICENSE").write_text("Mozilla Public License Version 2.0", encoding="utf-8")
    manifest = audit_corpus(root)
    called = False

    def _should_not_write(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("write must not occur")

    monkeypatch.setattr("backend.file_store.save_document", _should_not_write)

    assert manifest["source"]["license_status"] == "restricted"
    assert "license_restricted" in manifest["articles"][0]["risk"]["tags"]
    assert manifest["articles"][0]["import"]["eligible"] is False
    assert manifest["articles"][0]["import"]["reason"] == "license_restricted"
    with pytest.raises(ValueError, match="Restricted"):
        import_audited_corpus(manifest, root, confirm_unverified=True)
    assert called is False


def test_import_rechecks_license_state_before_any_write(tmp_path, monkeypatch):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path, license_file=True)
    manifest = audit_corpus(root)
    (root / "LICENSE").write_text("GNU GENERAL PUBLIC LICENSE", encoding="utf-8")
    called = False

    def _should_not_write(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("write must not occur")

    monkeypatch.setattr("backend.file_store.save_document", _should_not_write)
    with pytest.raises(ValueError, match="Restricted"):
        import_audited_corpus(manifest, root)
    assert called is False


def test_import_rechecks_file_drift_before_any_write(tmp_path, monkeypatch):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, first, _second = _make_corpus(tmp_path, license_file=True)
    manifest = audit_corpus(root)
    (first / "content.md").write_text("# Changed after audit", encoding="utf-8")
    called = False

    def _should_not_write(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("write must not occur")

    monkeypatch.setattr("backend.file_store.save_document", _should_not_write)
    with pytest.raises(ValueError, match="changed after audit"):
        import_audited_corpus(manifest, root)
    assert called is False


def test_controlled_import_persists_prose_only_to_isolated_collection(tmp_path, monkeypatch):
    from backend.rag.external_corpus import VECTOR_COLLECTION, audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path)
    manifest = audit_corpus(root)
    saved_chunks = []
    vector_calls = []

    monkeypatch.setattr("backend.file_store.find_documents_by_content_hash", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.file_store.save_document", lambda **kwargs: {"id": "doc-001", **kwargs})
    monkeypatch.setattr(
        "backend.file_store.save_chunks",
        lambda doc_id, chunks, embedding_ids: saved_chunks.append((doc_id, chunks, embedding_ids)) or len(chunks),
    )

    class _VectorStore:
        def add_documents(self, **kwargs):
            vector_calls.append(kwargs)

        def delete_documents(self, *args, **kwargs):
            return None

    monkeypatch.setattr("backend.rag.vector_store.VectorStore", _VectorStore)

    result = import_audited_corpus(
        manifest,
        root,
        confirm_unverified=True,
        selected_ids=["001_etf_rotation"],
    )

    assert len(result["imported"]) == 1
    assert saved_chunks
    assert "external code must not be imported" not in "\n".join(saved_chunks[0][1])
    assert vector_calls[0]["collection_name"] == VECTOR_COLLECTION
    assert vector_calls[0]["metadatas"][0]["citation_allowed"] is False


def test_controlled_import_rolls_back_document_when_chunk_write_fails(tmp_path, monkeypatch):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, _second = _make_corpus(tmp_path, license_file=True)
    manifest = audit_corpus(root)
    deleted = []
    monkeypatch.setattr("backend.file_store.find_documents_by_content_hash", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.file_store.save_document", lambda **kwargs: {"id": "doc-failed", **kwargs})
    monkeypatch.setattr(
        "backend.file_store.save_chunks", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    monkeypatch.setattr("backend.file_store.delete_document", lambda doc_id: deleted.append(doc_id) or True)

    with pytest.raises(RuntimeError, match="db down"):
        import_audited_corpus(manifest, root, selected_ids=["001_etf_rotation"])
    assert deleted == ["doc-failed"]


def test_remove_batch_keeps_chunk_ids_when_vector_cleanup_fails(monkeypatch):
    from backend.rag.external_corpus import VECTOR_COLLECTION, remove_import_batch

    document = {"id": "doc-001", "metadata": {"batch_id": "corpus-batch"}}
    deleted = []
    vector_calls = []
    state = {"fail": True}

    monkeypatch.setattr("backend.file_store.list_documents", lambda *args, **kwargs: [document])
    monkeypatch.setattr(
        "backend.file_store.get_chunks",
        lambda doc_id: [{"document_id": doc_id, "embedding_id": "doc-001_chunk_0"}],
    )
    monkeypatch.setattr("backend.file_store.delete_document", lambda doc_id: deleted.append(doc_id) or True)

    class _VectorStore:
        def delete_documents(self, collection_name, ids):
            vector_calls.append((collection_name, ids))
            if state["fail"]:
                raise RuntimeError("chroma unavailable")

    monkeypatch.setattr("backend.rag.vector_store.VectorStore", _VectorStore)

    with pytest.raises(RuntimeError, match="Vector cleanup failed"):
        remove_import_batch("corpus-batch")
    assert deleted == []

    state["fail"] = False
    result = remove_import_batch("corpus-batch")
    assert result["deleted_documents"] == 1
    assert deleted == ["doc-001"]
    assert vector_calls == [
        (VECTOR_COLLECTION, ["doc-001_chunk_0"]),
        (VECTOR_COLLECTION, ["doc-001_chunk_0"]),
    ]


def test_import_rollback_keeps_records_when_vector_cleanup_fails(tmp_path, monkeypatch):
    from backend.rag.external_corpus import audit_corpus, import_audited_corpus

    root, _first, second = _make_corpus(tmp_path, license_file=True)
    (second / "content.md").write_text("# Different article\n\nDifferent prose.", encoding="utf-8")
    manifest = audit_corpus(root)
    deleted = []
    saved_ids = iter(["doc-001", "doc-002"])
    chunk_calls = 0

    monkeypatch.setattr("backend.file_store.find_documents_by_content_hash", lambda *args, **kwargs: [])
    monkeypatch.setattr("backend.file_store.save_document", lambda **kwargs: {"id": next(saved_ids), **kwargs})

    def _save_chunks(*args, **kwargs):
        nonlocal chunk_calls
        chunk_calls += 1
        if chunk_calls == 2:
            raise RuntimeError("db down")
        return 1

    monkeypatch.setattr("backend.file_store.save_chunks", _save_chunks)
    monkeypatch.setattr("backend.file_store.delete_document", lambda doc_id: deleted.append(doc_id) or True)

    class _VectorStore:
        def add_documents(self, **kwargs):
            return None

        def delete_documents(self, *args, **kwargs):
            raise RuntimeError("chroma unavailable")

    monkeypatch.setattr("backend.rag.vector_store.VectorStore", _VectorStore)

    with pytest.raises(RuntimeError, match="batch corpus-"):
        import_audited_corpus(manifest, root)
    assert deleted == []
