"""Durable research versions, evidence-bound reviews and deterministic comparisons."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.storage.db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def public_config(value: Any) -> Any:
    """Never persist credentials or endpoints supplied in model overrides."""
    if isinstance(value, dict):
        return {key: public_config(item) for key, item in value.items() if not _private_config_field(key)}
    if isinstance(value, list):
        return [public_config(item) for item in value]
    return value


def _private_config_field(key: str) -> bool:
    normalized = key.lower().replace("_", "").replace("-", "")
    return (
        normalized
        in {"apikey", "apikeys", "token", "accesstoken", "authtoken", "apitoken", "authorization", "endpoint"}
        or normalized.endswith("url")
        or any(word in normalized for word in ("secret", "password", "header"))
    )


class ResearchWorkspaceStore:
    def __init__(self):
        self.db = Database()
        with self.db.transaction() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS research_workspaces (
                    id TEXT PRIMARY KEY, draft_json TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS research_versions (
                    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, number INTEGER NOT NULL,
                    task_id TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending',
                    stage TEXT NOT NULL DEFAULT 'market', error TEXT NOT NULL DEFAULT '',
                    input_json TEXT NOT NULL, stock_json TEXT, result_json TEXT,
                    parent_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                    UNIQUE(workspace_id, number)
                );
                CREATE TABLE IF NOT EXISTS research_claim_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, version_id TEXT NOT NULL,
                    claim_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    review_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(version_id, claim_id, revision)
                );
            """)

    def save_workspace(self, draft: dict, workspace_id: str = "") -> dict:
        now = _now()
        with self.db.transaction() as conn:
            if workspace_id:
                row = conn.execute("SELECT * FROM research_workspaces WHERE id=?", (workspace_id,)).fetchone()
                if not row:
                    raise KeyError("Workspace not found")
                if json.loads(row["draft_json"])["stock_symbol"] != draft["stock_symbol"]:
                    raise ValueError("A workspace cannot change its stock")
                conn.execute(
                    "UPDATE research_workspaces SET draft_json=?, updated_at=? WHERE id=?",
                    (_json(draft), now, workspace_id),
                )
            else:
                workspace_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO research_workspaces VALUES (?, ?, ?, ?)",
                    (workspace_id, _json(draft), now, now),
                )
            conn.commit()
        return self.workspace(workspace_id)

    def list_workspaces(self) -> list[dict]:
        with self.db.transaction() as conn:
            rows = conn.execute("SELECT * FROM research_workspaces ORDER BY updated_at DESC LIMIT 200").fetchall()
        return [
            {"id": row["id"], "updated_at": row["updated_at"], "draft": json.loads(row["draft_json"])} for row in rows
        ]

    def workspace(self, workspace_id: str) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM research_workspaces WHERE id=?", (workspace_id,)).fetchone()
            versions = conn.execute(
                "SELECT id, number, task_id, status, stage, error, parent_id, created_at "
                "FROM research_versions WHERE workspace_id=? ORDER BY number DESC",
                (workspace_id,),
            ).fetchall()
        if not row:
            raise KeyError("Workspace not found")
        return {"id": row["id"], "draft": json.loads(row["draft_json"]), "versions": [dict(v) for v in versions]}

    def create_version(self, workspace_id: str, inputs: dict, parent_id: str = "", stock: dict | None = None) -> str:
        version_id = uuid.uuid4().hex
        with self.db.transaction() as conn:
            if not conn.execute("SELECT 1 FROM research_workspaces WHERE id=?", (workspace_id,)).fetchone():
                raise KeyError("Workspace not found")
            active = conn.execute(
                "SELECT 1 FROM research_versions WHERE workspace_id=? AND status IN ('pending', 'running')",
                (workspace_id,),
            ).fetchone()
            if active:
                raise ValueError("This workspace already has an active run")
            number = conn.execute(
                "SELECT COALESCE(MAX(number), 0)+1 FROM research_versions WHERE workspace_id=?", (workspace_id,)
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO research_versions (id, workspace_id, number, input_json, stock_json, parent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (version_id, workspace_id, number, _json(inputs), _json(stock) if stock else None, parent_id, _now()),
            )
            conn.execute("UPDATE research_workspaces SET updated_at=? WHERE id=?", (_now(), workspace_id))
            conn.commit()
        return version_id

    def version(self, version_id: str) -> dict:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM research_versions WHERE id=?", (version_id,)).fetchone()
        if not row:
            raise KeyError("Version not found")
        data = dict(row)
        for key in ("input", "stock", "result"):
            data[key] = json.loads(data.pop(f"{key}_json") or "null")
        return data

    def checkpoint(self, version_id: str, **updates) -> None:
        allowed = {"task_id", "status", "stage", "error", "stock_json", "result_json"}
        if not updates or not set(updates) <= allowed:
            raise ValueError("Invalid checkpoint")
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE research_versions SET {', '.join(f'{key}=?' for key in updates)} "
                "WHERE id=? AND status IN ('pending', 'running')",
                (*updates.values(), version_id),
            )
            conn.commit()

    def reviews(self, version_id: str) -> dict[str, list[dict]]:
        with self.db.transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM research_claim_reviews WHERE version_id=? ORDER BY revision DESC", (version_id,)
            ).fetchall()
        result: dict[str, list[dict]] = {}
        for row in rows:
            result.setdefault(row["claim_id"], []).append(
                {
                    **json.loads(row["review_json"]),
                    "revision": row["revision"],
                    "created_at": row["created_at"],
                }
            )
        return result

    def review(self, version_id: str, claim_id: str, review: dict) -> dict:
        version = self.version(version_id)
        if version["status"] != "success":
            raise ValueError("Only completed versions can be reviewed")
        if claim_id not in {c["id"] for c in extract_claims(version["result"])}:
            raise KeyError("Claim not found in this version")
        evidence_ids = {e["evidence_id"] for e in (version["result"] or {}).get("evidence_pool", [])}
        if not set(review["evidence_relations"]) <= evidence_ids:
            raise ValueError("Evidence must belong to this version")
        with self.db.transaction() as conn:
            revision = conn.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM research_claim_reviews WHERE version_id=? AND claim_id=?",
                (version_id, claim_id),
            ).fetchone()[0]
            if revision != review["expected_revision"]:
                raise ValueError("Review changed; reload before saving")
            now = _now()
            conn.execute(
                "INSERT INTO research_claim_reviews (version_id, claim_id, revision, review_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (version_id, claim_id, revision + 1, _json(review), now),
            )
            conn.commit()
        return {**review, "revision": revision + 1, "created_at": now}


def extract_claims(result: dict | None) -> list[dict]:
    result = result or {}
    pool = {str(e.get("number")): e["evidence_id"] for e in result.get("evidence_pool", [])}
    claims = []
    for agent_id, agent in (result.get("agents") or {}).items():
        texts = [str(agent.get("reason") or ""), *(agent.get("risk_points") or [])]
        for text in texts:
            # Split only at unambiguous sentence boundaries, never decimal points.
            for sentence in re.split(r"(?<=[。！？])\s*|\n+", text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                digest = hashlib.sha256(f"{agent_id}:{sentence}".encode()).hexdigest()[:20]
                if any(c["id"] == digest for c in claims):
                    continue
                ids = [pool[n] for n in re.findall(r"\[(\d+)\]", sentence) if n in pool]
                claims.append(
                    {
                        "id": digest,
                        "agent_id": agent_id,
                        "agent_name": agent.get("name") or agent_id,
                        "text": sentence,
                        "evidence_ids": list(dict.fromkeys(ids)),
                        "agent_evidence_ids": agent.get("evidence_ids") or [],
                    }
                )
    return claims


def _changes(before: dict, after: dict) -> list[dict]:
    return [
        {
            "field": key,
            "before": before.get(key),
            "after": after.get(key),
            "status": "added" if key not in before else "removed" if key not in after else "changed",
        }
        for key in sorted(before.keys() | after.keys())
        if before.get(key) != after.get(key)
    ]


def compare_versions(before: dict, after: dict) -> dict:
    if before["workspace_id"] != after["workspace_id"]:
        raise ValueError("Compare versions from the same workspace")
    if before["status"] != "success" or after["status"] != "success":
        raise ValueError("Only completed versions can be compared")
    if before["number"] >= after["number"]:
        raise ValueError("Baseline must precede the selected version")
    old, new = before["result"] or {}, after["result"] or {}

    def evidence(result):
        return {
            e["evidence_id"]: {k: v for k, v in e.items() if k != "number"} for e in result.get("evidence_pool", [])
        }

    def metrics(version):
        stock = version["stock"] or {}
        values = {k: v for k, v in stock.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
        for group in ("fundamentals", "financial_metrics"):
            if isinstance(stock.get(group), dict):
                values.update({f"{group}.{k}": v for k, v in stock[group].items()})
        return values

    def models(version):
        agents = (version["result"] or {}).get("agents") or {}
        return {
            "requested": public_config(
                {k: version["input"].get(k) for k in ("agent_configs", "global_ai_settings", "mode")}
            ),
            "resolved": (version["result"] or {}).get("model_config_snapshot"),
            "actual": {
                key: {k: value.get(k) for k in ("vendor", "model", "fallback_used")} for key, value in agents.items()
            },
        }

    agent_changes = _changes(
        {
            k: {f: v.get(f) for f in ("signal", "confidence", "reason", "risk_points", "ok")}
            for k, v in (old.get("agents") or {}).items()
        },
        {
            k: {f: v.get(f) for f in ("signal", "confidence", "reason", "risk_points", "ok")}
            for k, v in (new.get("agents") or {}).items()
        },
    )
    evidence_changes = _changes(evidence(old), evidence(new))
    metric_changes = _changes(metrics(before), metrics(after))
    model_changes = _changes(models(before), models(after))
    summary = old.get("summary"), new.get("summary")
    warnings = ["差异仅表示记录发生变化，不自动证明结论变化的因果关系。"]
    if not old.get("model_config_snapshot") or not new.get("model_config_snapshot"):
        warnings.append("至少一个版本缺少完整的已解析模型配置，仅比较已记录字段。")
    if not any(
        k.startswith(("fundamentals.", "financial_metrics.")) for k in metrics(before).keys() | metrics(after).keys()
    ):
        warnings.append("两个版本均未记录结构化财务指标，不能据此判断财务状况不变。")
    if not old.get("evidence_pool") or not new.get("evidence_pool"):
        warnings.append("至少一个版本缺少证据快照，证据差异不完整。")
    return {
        "before_id": before["id"],
        "after_id": after["id"],
        "conclusion": {"before": summary[0], "after": summary[1], "changed": summary[0] != summary[1]},
        "context": _changes(
            {k: before["input"].get(k) for k in ("as_of", "research_question", "report_template", "materials")},
            {k: after["input"].get(k) for k in ("as_of", "research_question", "report_template", "materials")},
        ),
        "evidence": evidence_changes,
        "metrics": metric_changes,
        "agents": agent_changes,
        "models": model_changes,
        "warnings": warnings,
        "summary": f"证据变化 {len(evidence_changes)} 条，指标变化 {len(metric_changes)} 项，"
        f"Agent 观点变化 {len(agent_changes)} 项；已记录模型字段{'有变化' if model_changes else '一致'}。",
    }
