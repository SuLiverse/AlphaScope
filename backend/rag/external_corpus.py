"""Static audit and controlled import for externally supplied strategy corpora.

This module deliberately treats a corpus as untrusted text.  It never imports
or runs source files from the corpus: Python snippets are inspected only with
``ast.parse`` and importable RAG material is derived from Markdown with fenced
code removed.  The two-stage flow is:

1. ``audit_corpus`` creates a deterministic manifest with provenance, exact
   duplicate detection, topic tags, and risk flags.
2. ``import_audited_corpus`` re-checks file hashes before writing only approved
   prose into the isolated ``unverified_strategy_ideas`` collection.

An unknown licence is intentionally a hard confirmation boundary.  This keeps
research ideas useful without silently turning an unattributed article dump
into distributable project content or evidence.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


AUDIT_SCHEMA_VERSION = 1
DEFAULT_MAX_TEXT_BYTES = 2 * 1024 * 1024
SOURCE_TYPE = "external_strategy_corpus"
VECTOR_COLLECTION = "unverified_strategy_ideas"
TRUST_SCORE = 0.2

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_FIRST_HEADING_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)
_SPACE_RE = re.compile(r"\s+")

_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("etf_rotation", ("etf", "rsrs")),
    ("asset_allocation", ("多资产", "再平衡", "风险均衡", "risk parity")),
    ("multi_factor", ("多因子", "因子选股", "因子筛选")),
    ("dividend_value", ("高股息", "股息", "红利", "低波", "低估值", "价值", "质量")),
    ("momentum_timing", ("动量", "择时", "均线", "趋势")),
    ("limit_up_intraday", ("涨停", "打板", "日内", "竞价")),
    ("ml_statistical", ("机器学习", "深度学习", "强化学习", "svr", "pca", "聚类")),
)

_PLATFORM_API_RE = re.compile(
    r"\b(?:jqdata|jqfactor|get_price|get_fundamentals|get_factor_values|"
    r"attribute_history|order_target_value|run_daily|run_weekly|set_benchmark)\b",
    re.IGNORECASE,
)
_LIVE_TRADING_RE = re.compile(
    r"\b(?:xtquant|qmt|order_stock_async|easytrader|broker)\b|实盘|自动下单|券商",
    re.IGNORECASE,
)
_SYNTHETIC_DATA_RE = re.compile(r"\b(?:random\.seed|random\.uniform)\b|随机生成|模拟行情", re.IGNORECASE)
_ZERO_SLIPPAGE_RE = re.compile(r"FixedSlippage\(\s*0(?:\.0+)?\s*\)", re.IGNORECASE)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_within(root: Path, candidate: Path) -> bool:
    """Return whether a resolved candidate remains within the corpus root."""
    try:
        candidate.resolve(strict=True).relative_to(root)
        return True
    except (FileNotFoundError, OSError, ValueError):
        return False


def _safe_read_text(root: Path, path: Path, max_bytes: int) -> tuple[str, str, str | None]:
    """Read a small text file without following a symlink outside ``root``."""
    if path.is_symlink():
        return "", "", "symlink_skipped"
    if not _is_within(root, path) or not path.is_file():
        return "", "", "path_outside_root"
    try:
        if path.stat().st_size > max_bytes:
            return "", "", "file_too_large"
        raw = path.read_bytes()
    except OSError:
        return "", "", "read_error"
    return raw.decode("utf-8", errors="replace"), _sha256_bytes(raw), None


def _strip_fenced_code(markdown: str) -> str:
    """Extract prose from Markdown while retaining headings and ordinary text."""
    kept: list[str] = []
    fence_char = ""
    fence_length = 0
    for line in markdown.splitlines():
        match = _FENCE_RE.match(line)
        if match:
            token = match.group(1)
            if not fence_char:
                fence_char = token[0]
                fence_length = len(token)
            elif token[0] == fence_char and len(token) >= fence_length and not line[match.end() :].strip():
                fence_char = ""
                fence_length = 0
            continue
        if not fence_char:
            kept.append(line)
    return "\n".join(kept).strip()


def _normalise_text(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _first_heading(text: str) -> str:
    match = _FIRST_HEADING_RE.search(text)
    return match.group(1).strip() if match else ""


def _read_meta(root: Path, article_dir: Path, max_bytes: int) -> dict[str, Any]:
    path = article_dir / "meta.json"
    if not path.exists():
        return {}
    raw, _digest, issue = _safe_read_text(root, path, max_bytes)
    if issue:
        return {"_read_issue": issue}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {"_read_issue": "invalid_json"}
    return loaded if isinstance(loaded, dict) else {"_read_issue": "invalid_meta_shape"}


def _git_value(root: Path, *args: str) -> str:
    """Read Git metadata only.  No repository hook or project code is run."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _repo_metadata(root: Path, repository_url: str | None) -> dict[str, Any]:
    licence_candidates = [
        path
        for path in root.iterdir()
        if path.is_file() and path.name.casefold() in {"license", "license.md", "copying", "notice"}
    ]
    licence_path = licence_candidates[0] if licence_candidates else None
    licence = licence_path.name if licence_path else ""
    licence_text = ""
    licence_hash = ""
    if licence_path:
        licence_text, licence_hash, _issue = _safe_read_text(root, licence_path, DEFAULT_MAX_TEXT_BYTES)
    licence_lower = licence_text.casefold()
    if any(
        token in licence_lower
        for token in (
            "agpl",
            "gnu affero general public license",
            "gnu lesser general public license",
            "gnu general public license",
            "lgpl-",
            "gpl-",
            "creative commons attribution-noncommercial",
            "creative commons attribution-sharealike",
            "mozilla public license",
            "mpl-2.0",
            "eclipse public license",
            "european union public licence",
        )
    ):
        licence_status = "restricted"
        licence_name = "restricted_or_copyleft"
    elif any(token in licence_lower for token in ("mit license", "apache license", "bsd license", "isc license")):
        licence_status = "safe"
        licence_name = licence.split(".")[0] or "recognized"
    else:
        licence_status = "unknown"
        licence_name = ""
    remote = repository_url or _git_value(root, "config", "--get", "remote.origin.url")
    return {
        "repository_url": remote,
        "commit": _git_value(root, "rev-parse", "HEAD"),
        "license_file": licence,
        "license_sha256": licence_hash,
        "license_name": licence_name,
        "license_status": licence_status,
    }


def _categories(title: str, prose: str) -> list[str]:
    # Topic classification intentionally keys off the article title.  Searching
    # the full prose makes broad terms such as "risk" or "rotation" leak into
    # unrelated strategy families and inflates the candidate list.
    del prose
    title_text = title.casefold()
    matched: list[str] = []
    for category, keywords in _CATEGORY_RULES:
        if any(keyword.casefold() in title_text for keyword in keywords):
            matched.append(category)
    return matched or ["general_strategy"]


def _candidate_tier(categories: Iterable[str]) -> tuple[str, int]:
    category_set = set(categories)
    if category_set & {"limit_up_intraday", "ml_statistical"}:
        return "C", 20
    if "etf_rotation" in category_set or "asset_allocation" in category_set:
        return "A", 90
    if category_set & {"multi_factor", "dividend_value", "momentum_timing"}:
        return "B", 60
    return "C", 30


def _provenance_missing(meta: dict[str, Any]) -> bool:
    required = ("author", "source_url", "published_at")
    return any(not str(meta.get(key) or "").strip() for key in required)


def _risk_level(tags: list[str]) -> str:
    high = {"license_unknown", "license_restricted", "live_trading_reference", "path_outside_root"}
    medium = {
        "platform_specific_api",
        "code_syntax_error",
        "provenance_missing",
        "synthetic_market_data",
        "zero_slippage",
    }
    if high.intersection(tags):
        return "high"
    if medium.intersection(tags):
        return "medium"
    return "low"


def _analyse_code(root: Path, article_dir: Path, max_bytes: int) -> tuple[int, int, list[str], str]:
    code_dir = article_dir / "code"
    if not code_dir.is_dir() or code_dir.is_symlink():
        return 0, 0, [], ""
    snippets = sorted(path for path in code_dir.rglob("*.py") if _is_within(root, path))
    syntax_errors = 0
    issues: list[str] = []
    scan_parts: list[str] = []
    for path in snippets:
        text, _digest, issue = _safe_read_text(root, path, max_bytes)
        if issue:
            issues.append(issue)
            continue
        scan_parts.append(text)
        try:
            ast.parse(text, filename=str(path))
        except SyntaxError:
            syntax_errors += 1
    return len(snippets), syntax_errors, sorted(set(issues)), "\n".join(scan_parts)


def _article_risks(
    *,
    prose: str,
    content: str,
    code_text: str,
    syntax_errors: int,
    code_issues: list[str],
    has_downloads: bool,
    licence_status: str,
    provenance_missing: bool,
) -> list[str]:
    scan = "\n".join((content, code_text))
    tags: list[str] = []
    if licence_status == "unknown":
        tags.append("license_unknown")
    elif licence_status == "restricted":
        tags.append("license_restricted")
    if provenance_missing:
        tags.append("provenance_missing")
    if syntax_errors:
        tags.append("code_syntax_error")
    if code_issues:
        tags.extend(code_issues)
    if _PLATFORM_API_RE.search(scan):
        tags.append("platform_specific_api")
    if _LIVE_TRADING_RE.search(scan):
        tags.append("live_trading_reference")
    if _SYNTHETIC_DATA_RE.search(scan):
        tags.append("synthetic_market_data")
    if _ZERO_SLIPPAGE_RE.search(scan):
        tags.append("zero_slippage")
    if has_downloads:
        tags.append("external_download_removed")
    if "回测" not in prose:
        tags.append("no_backtest_method")
    if "样本外" not in prose and "walk-forward" not in prose.casefold():
        tags.append("no_oos_method")
    return sorted(set(tags))


def _manifest_hash(manifest: dict[str, Any]) -> str:
    copy = dict(manifest)
    copy.pop("manifest_sha256", None)
    # ``generated_at`` is a reporting timestamp, not corpus state.  Excluding it
    # keeps the audit fingerprint stable when the same immutable source is
    # re-audited, while file/body hashes still make source drift fail import.
    copy.pop("generated_at", None)
    return _sha256_bytes(_canonical_json(copy).encode("utf-8"))


def audit_corpus(
    root: str | Path,
    *,
    repository_url: str | None = None,
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a read-only audit manifest for a corpus with ``articles/*/content.md``.

    The returned manifest contains hashes rather than article prose, so it can
    be committed or shared without reproducing the external material.
    """
    root_path = Path(root).resolve()
    articles_dir = root_path / "articles"
    if not root_path.is_dir() or not articles_dir.is_dir():
        raise ValueError("Corpus root must contain an articles directory")
    if max_text_bytes < 1024:
        raise ValueError("max_text_bytes must be at least 1024")

    repo = _repo_metadata(root_path, repository_url)
    article_dirs = sorted(
        path
        for path in articles_dir.iterdir()
        if path.is_dir() and not path.is_symlink() and _is_within(root_path, path)
    )
    articles: list[dict[str, Any]] = []
    seen_bodies: dict[str, str] = {}

    for article_dir in article_dirs:
        content_path = article_dir / "content.md"
        content, content_hash, content_issue = _safe_read_text(root_path, content_path, max_text_bytes)
        if content_issue:
            # A directory without readable content cannot be an import candidate,
            # but retaining it in the audit makes the omission visible.
            content = ""
            content_hash = ""
        meta = _read_meta(root_path, article_dir, max_text_bytes)
        prose = _strip_fenced_code(content)
        title = str(meta.get("title") or _first_heading(content) or article_dir.name).strip()
        categories = _categories(title, prose)
        tier, priority = _candidate_tier(categories)
        code_count, syntax_errors, code_issues, code_text = _analyse_code(root_path, article_dir, max_text_bytes)
        provenance_missing = _provenance_missing(meta)
        has_downloads = (article_dir / "downloads.md").is_file()
        tags = _article_risks(
            prose=prose,
            content=content,
            code_text=code_text,
            syntax_errors=syntax_errors,
            code_issues=code_issues,
            has_downloads=has_downloads,
            licence_status=repo["license_status"],
            provenance_missing=provenance_missing,
        )
        if content_issue:
            tags = sorted(set([*tags, content_issue]))
        # A compelling topic is not automatically an implementation priority.
        # Broken snippets, live-trading references, or synthetic-market examples
        # are still useful for research review, but should not lead the queue.
        if tier == "A" and {"code_syntax_error", "live_trading_reference", "synthetic_market_data"}.intersection(tags):
            tier, priority = "B", 55
        normalised_body = _normalise_text(prose)
        body_hash = _sha256_bytes(normalised_body.encode("utf-8")) if normalised_body else ""
        duplicate_of = seen_bodies.get(body_hash) if body_hash else None
        if body_hash and duplicate_of is None:
            seen_bodies[body_hash] = article_dir.name

        import_eligible = bool(prose) and duplicate_of is None and repo["license_status"] == "safe"
        if not prose:
            import_reason = "no_readable_prose"
        elif duplicate_of:
            import_reason = "exact_duplicate"
        elif repo["license_status"] == "restricted":
            import_reason = "license_restricted"
        elif repo["license_status"] == "unknown":
            import_reason = "license_unknown_requires_explicit_confirmation"
        else:
            import_reason = "eligible_after_review"

        articles.append(
            {
                "id": article_dir.name,
                "title": title,
                "relative_path": article_dir.relative_to(root_path).as_posix(),
                "content_path": content_path.relative_to(root_path).as_posix(),
                "content_sha256": content_hash,
                "body_sha256": body_hash,
                "body_characters": len(prose),
                "categories": categories,
                "candidate_tier": tier,
                "priority": priority,
                "duplicate_of": duplicate_of,
                "risk": {"level": _risk_level(tags), "tags": tags},
                "static_analysis": {
                    "code_snippets": code_count,
                    "syntax_errors": syntax_errors,
                    "content_read_issue": content_issue or "",
                },
                "provenance": {
                    "author": str(meta.get("author") or ""),
                    "source_url": str(meta.get("source_url") or meta.get("url") or ""),
                    "published_at": str(meta.get("published_at") or meta.get("date") or ""),
                    "complete": not provenance_missing,
                },
                "import": {
                    "body_only": True,
                    "eligible": import_eligible,
                    "reason": import_reason,
                },
            }
        )

    category_counts = Counter(category for article in articles for category in article["categories"])
    tier_counts = Counter(article["candidate_tier"] for article in articles)
    risk_counts = Counter(tag for article in articles for tag in article["risk"]["tags"])
    duplicate_count = sum(1 for article in articles if article["duplicate_of"])
    manifest: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source": {
            **repo,
            "root_name": root_path.name,
            "article_directory": "articles",
        },
        "policy": {
            "body_only": True,
            "code_execution": "forbidden",
            "unknown_license_requires_confirmation": True,
            "target_collection": VECTOR_COLLECTION,
            "trust_score": TRUST_SCORE,
        },
        "summary": {
            "articles": len(articles),
            "exact_body_duplicates": duplicate_count,
            "categories": dict(sorted(category_counts.items())),
            "candidate_tiers": dict(sorted(tier_counts.items())),
            "risk_tags": dict(sorted(risk_counts.items())),
            "eligible_without_override": sum(1 for article in articles if article["import"]["eligible"]),
        },
        "articles": articles,
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def render_audit_markdown(manifest: dict[str, Any]) -> str:
    """Render a compact human review report without article body text."""
    source = manifest.get("source", {}) or {}
    summary = manifest.get("summary", {}) or {}
    lines = [
        "# External Strategy Corpus Audit",
        "",
        f"- Articles: {summary.get('articles', 0)}",
        f"- Exact body duplicates: {summary.get('exact_body_duplicates', 0)}",
        f"- Repository: {source.get('repository_url') or 'unknown'}",
        f"- Commit: {source.get('commit') or 'unknown'}",
        f"- License status: {source.get('license_status') or 'unknown'}",
        f"- Manifest SHA-256: {manifest.get('manifest_sha256', '')}",
        "",
        "## Candidate Families",
        "",
        "| Tier | Article | Categories | Risk | Import status |",
        "| --- | --- | --- | --- | --- |",
    ]
    articles = sorted(
        manifest.get("articles", []),
        key=lambda item: (item.get("candidate_tier", "Z"), -int(item.get("priority", 0)), item.get("id", "")),
    )
    for article in articles:
        if article.get("candidate_tier") != "A":
            continue
        categories = ", ".join(article.get("categories", []))
        risk = ", ".join(article.get("risk", {}).get("tags", []))
        lines.append(
            "| {tier} | {title} | {categories} | {risk} | {reason} |".format(
                tier=article.get("candidate_tier", ""),
                title=str(article.get("title", "")).replace("|", "\\|"),
                categories=categories,
                risk=risk,
                reason=article.get("import", {}).get("reason", ""),
            )
        )
    lines.extend(["", "## Risk Summary", ""])
    for tag, count in sorted((summary.get("risk_tags", {}) or {}).items()):
        lines.append(f"- {tag}: {count}")
    lines.extend(
        [
            "",
            "This audit is static. It neither executes corpus code nor treats the material as investment evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_audit_outputs(manifest: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    """Write the JSON manifest and a compact Markdown review report."""
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "audit.json"
    markdown_path = target / "audit.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_audit_markdown(manifest), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(markdown_path)}


def load_audit(path: str | Path) -> dict[str, Any]:
    """Load and integrity-check an audit manifest written by this module."""
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError("Unsupported audit manifest")
    expected = str(manifest.get("manifest_sha256") or "")
    if not expected or expected != _manifest_hash(manifest):
        raise ValueError("Audit manifest integrity check failed")
    return manifest


def _selected_articles(manifest: dict[str, Any], selected_ids: Iterable[str] | None) -> list[dict[str, Any]]:
    selected = {str(item) for item in selected_ids or [] if str(item)}
    articles = [article for article in manifest.get("articles", []) if isinstance(article, dict)]
    if selected:
        missing = selected - {str(article.get("id") or "") for article in articles}
        if missing:
            raise ValueError(f"Unknown article ids in selection: {', '.join(sorted(missing))}")
        articles = [article for article in articles if article.get("id") in selected]
    return articles


def _read_import_body(root: Path, article: dict[str, Any], max_text_bytes: int) -> tuple[str, str]:
    relative = str(article.get("content_path") or "")
    path = root / relative
    content, content_hash, issue = _safe_read_text(root, path, max_text_bytes)
    if issue:
        raise ValueError(f"Cannot re-read {relative}: {issue}")
    if content_hash != article.get("content_sha256"):
        raise ValueError(f"Corpus changed after audit: {relative}")
    prose = _strip_fenced_code(content)
    body_hash = _sha256_bytes(_normalise_text(prose).encode("utf-8")) if prose else ""
    if body_hash != article.get("body_sha256"):
        raise ValueError(f"Corpus body changed after audit: {relative}")
    return prose, body_hash


def _verify_import_source(root: Path, source: dict[str, Any]) -> None:
    """Reject an import when the audited repository or licence state changed."""
    if source.get("license_status") == "restricted":
        raise ValueError("Restricted or copyleft corpus license cannot be imported")

    current = _repo_metadata(root, str(source.get("repository_url") or "") or None)
    if current.get("license_status") == "restricted":
        raise ValueError("Restricted or copyleft corpus license cannot be imported")

    # A commit change can alter files other than article prose.  License files
    # are also individually hashed so non-git corpora receive the same guard.
    expected_commit = str(source.get("commit") or "")
    if expected_commit and current.get("commit") != expected_commit:
        raise ValueError("Corpus repository changed after audit; run a new audit before importing")
    for field in ("license_file", "license_name", "license_status"):
        if current.get(field, "") != source.get(field, ""):
            raise ValueError("Corpus license state changed after audit; run a new audit before importing")
    if "license_sha256" in source and current.get("license_sha256", "") != source.get("license_sha256", ""):
        raise ValueError("Corpus license state changed after audit; run a new audit before importing")


def _chunk_text(content: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    if not content:
        return []
    if len(content) <= chunk_size:
        return [content]
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = min(len(content), start + chunk_size)
        if end < len(content):
            for separator in ("\n", "。", ".", "！", "!", "？", "?"):
                split_at = content.rfind(separator, start + chunk_size // 2, end)
                if split_at > start:
                    end = split_at + 1
                    break
        chunk = content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(content):
            break
        start = max(start + 1, end - overlap)
    return chunks


def import_audited_corpus(
    manifest: dict[str, Any],
    root: str | Path,
    *,
    confirm_unverified: bool = False,
    selected_ids: Iterable[str] | None = None,
    max_text_bytes: int = DEFAULT_MAX_TEXT_BYTES,
) -> dict[str, Any]:
    """Import audited prose into an isolated low-trust RAG collection.

    Every selected file is hash-checked before the first database write.  Corpus
    code is never imported, and a source with an unknown licence requires an
    explicit caller confirmation.
    """
    if manifest.get("schema_version") != AUDIT_SCHEMA_VERSION or _manifest_hash(manifest) != manifest.get(
        "manifest_sha256"
    ):
        raise ValueError("Audit manifest integrity check failed")
    root_path = Path(root).resolve()
    source = manifest.get("source", {}) or {}
    _verify_import_source(root_path, source)
    if source.get("license_status") == "unknown" and not confirm_unverified:
        raise ValueError("Unknown corpus licence requires confirm_unverified=True")

    prepared: list[tuple[dict[str, Any], str, str]] = []
    skipped: list[dict[str, str]] = []
    for article in _selected_articles(manifest, selected_ids):
        if article.get("duplicate_of"):
            skipped.append({"id": str(article.get("id") or ""), "reason": "exact_duplicate"})
            continue
        prose, body_hash = _read_import_body(root_path, article, max_text_bytes)
        if not prose:
            skipped.append({"id": str(article.get("id") or ""), "reason": "no_readable_prose"})
            continue
        prepared.append((article, prose, body_hash))

    # Import only after all drift checks above complete successfully.
    batch_seed = "|".join(
        [
            str(source.get("repository_url") or ""),
            str(source.get("commit") or ""),
            str(manifest.get("manifest_sha256") or ""),
        ]
    )
    batch_id = "corpus-" + _sha256_bytes(batch_seed.encode("utf-8"))[:16]
    from backend.file_store import find_documents_by_content_hash, save_chunks, save_document

    imported: list[dict[str, Any]] = []
    created_document_ids: list[str] = []
    vector_ids: list[str] = []
    vector_store: Any = None
    try:
        from backend.rag.vector_store import VectorStore

        vector_store = VectorStore()
    except Exception:
        vector_store = None

    try:
        for article, prose, body_hash in prepared:
            stored_hash = f"sha256:{body_hash}"
            if find_documents_by_content_hash(stored_hash, source_type=SOURCE_TYPE):
                skipped.append({"id": str(article.get("id") or ""), "reason": "already_imported"})
                continue
            title = f"[Unverified strategy idea] {article.get('title') or article.get('id') or 'article'}"
            metadata = {
                "batch_id": batch_id,
                "article_id": str(article.get("id") or ""),
                "repository_url": str(source.get("repository_url") or ""),
                "commit": str(source.get("commit") or ""),
                "license_status": str(source.get("license_status") or "unknown"),
                "provenance_complete": bool(article.get("provenance", {}).get("complete")),
                "risk_tags": article.get("risk", {}).get("tags", []),
                "candidate_tier": str(article.get("candidate_tier") or ""),
                "body_only": True,
                "citation_allowed": False,
            }
            saved = save_document(
                title=title,
                file_path=(
                    f"{source.get('repository_url') or 'external-corpus'}@{source.get('commit') or 'unknown'}"
                    f"/{article.get('relative_path') or ''}"
                ),
                content_hash=stored_hash,
                source_type=SOURCE_TYPE,
                source_url=str(source.get("repository_url") or ""),
                trust_score=TRUST_SCORE,
                metadata=metadata,
            )
            doc_id = str(saved["id"])
            created_document_ids.append(doc_id)
            chunks = _chunk_text(prose)
            ids = [f"{doc_id}_chunk_{index}" for index in range(len(chunks))]
            save_chunks(doc_id, chunks, ids)
            indexed = False
            if vector_store and chunks:
                vector_metadata = {
                    "doc_id": doc_id,
                    "article_id": str(article.get("id") or ""),
                    "source_type": SOURCE_TYPE,
                    "source_url": str(source.get("repository_url") or ""),
                    "trust_tier": "D",
                    "corpus_batch": batch_id,
                    "citation_allowed": False,
                    "risk_tags": ",".join(article.get("risk", {}).get("tags", [])),
                }
                try:
                    vector_store.add_documents(
                        collection_name=VECTOR_COLLECTION,
                        documents=chunks,
                        metadatas=[{**vector_metadata, "chunk_index": index} for index in range(len(chunks))],
                        ids=ids,
                    )
                    vector_ids.extend(ids)
                    indexed = True
                except Exception:
                    indexed = False
            imported.append(
                {"id": str(article.get("id") or ""), "doc_id": doc_id, "chunks": len(chunks), "indexed": indexed}
            )
    except Exception as import_error:
        # Best-effort rollback keeps a failed batch from leaving a partly trusted
        # corpus behind.  If vector cleanup fails, retain the SQLite mappings so
        # a later batch removal can still locate and delete the vectors.
        if vector_store and vector_ids:
            try:
                vector_store.delete_documents(VECTOR_COLLECTION, vector_ids)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"Import failed and vector cleanup could not complete for batch {batch_id}; "
                    "document records were retained for removal retry."
                ) from cleanup_error
        try:
            from backend.file_store import delete_document

            for doc_id in created_document_ids:
                delete_document(doc_id)
        except Exception:
            pass
        raise import_error

    return {
        "batch_id": batch_id,
        "collection": VECTOR_COLLECTION,
        "source_type": SOURCE_TYPE,
        "trust_score": TRUST_SCORE,
        "imported": imported,
        "skipped": skipped,
        "disclaimer": "Imported prose is unverified external research material. It is not executable code or investment evidence.",
    }


def remove_import_batch(batch_id: str) -> dict[str, Any]:
    """Remove documents from a controlled-import batch, including vector ids when available."""
    from backend.file_store import delete_document, get_chunks, list_documents

    matches = [
        document
        for document in list_documents(source_type=SOURCE_TYPE, limit=5000)
        if (document.get("metadata") or {}).get("batch_id") == batch_id
    ]
    vector_ids = [
        chunk.get("embedding_id")
        for document in matches
        for chunk in get_chunks(document["id"])
        if chunk.get("embedding_id")
    ]
    try:
        from backend.rag.vector_store import VectorStore

        if vector_ids:
            VectorStore().delete_documents(VECTOR_COLLECTION, vector_ids)
    except Exception as exc:
        raise RuntimeError(
            "Vector cleanup failed; document records were retained so the batch can be retried."
        ) from exc
    deleted = sum(1 for document in matches if delete_document(document["id"]))
    return {"batch_id": batch_id, "deleted_documents": deleted, "requested_documents": len(matches)}
