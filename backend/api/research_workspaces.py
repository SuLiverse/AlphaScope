"""Research workspace API. All versions and reviews are local, durable records."""

from __future__ import annotations

from datetime import date
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.research_workspace import ResearchWorkspaceStore, compare_versions, extract_claims
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/research-workspaces", tags=["research-workspaces"])


class ResearchMaterial(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_url: str = Field(default="", max_length=2000)
    published_at: date | None = None
    excerpt: str = Field(min_length=1, max_length=12000)

    @field_validator("source_url")
    @classmethod
    def http_url(cls, value):
        if value:
            parsed = urlsplit(value)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError("Source URL must be an HTTP(S) URL without credentials")
        return value


class WorkspaceDraft(BaseModel):
    stock_symbol: str = Field(min_length=1, max_length=24, pattern=r"^[A-Za-z0-9._-]+$")
    stock_name: str = Field(default="", max_length=100)
    research_question: str = Field(default="", max_length=2000)
    as_of: date | None = None
    report_template: Literal["standard", "macro", "risk"] = "standard"
    materials: list[ResearchMaterial] = Field(default_factory=list, max_length=30)

    @field_validator("as_of")
    @classmethod
    def cutoff(cls, value):
        if value and value > date.today():
            raise ValueError("Research cutoff cannot be in the future")
        return value


class ClaimReview(BaseModel):
    status: Literal["supported", "partial", "unsupported", "needs_evidence"]
    reason: str = Field(min_length=1, max_length=4000)
    revised_text: str = Field(default="", max_length=4000)
    evidence_relations: dict[str, Literal["supports", "opposes", "unclassified"]] = Field(default_factory=dict)
    expected_revision: int = Field(default=0, ge=0)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Review reason is required")
        return value.strip()


def _store_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.get("")
def list_workspaces():
    return ApiResponse(success=True, data={"workspaces": ResearchWorkspaceStore().list_workspaces()})


@router.post("")
def create_workspace(draft: WorkspaceDraft):
    return ApiResponse(success=True, data=ResearchWorkspaceStore().save_workspace(draft.model_dump(mode="json")))


@router.put("/{workspace_id}")
def save_workspace(workspace_id: str, draft: WorkspaceDraft):
    return ApiResponse(
        success=True,
        data=_store_call(
            ResearchWorkspaceStore().save_workspace,
            draft.model_dump(mode="json"),
            workspace_id,
        ),
    )


@router.get("/versions/{version_id}")
def get_version(version_id: str):
    store = ResearchWorkspaceStore()
    version = _store_call(store.version, version_id)
    return ApiResponse(
        success=True,
        data={**version, "claims": extract_claims(version["result"]), "reviews": store.reviews(version_id)},
    )


@router.put("/versions/{version_id}/claims/{claim_id}")
def review_claim(version_id: str, claim_id: str, review: ClaimReview):
    return ApiResponse(
        success=True,
        data=_store_call(
            ResearchWorkspaceStore().review,
            version_id,
            claim_id,
            review.model_dump(),
        ),
    )


@router.get("/{workspace_id}/compare")
def compare(workspace_id: str, before: str, after: str):
    store = ResearchWorkspaceStore()
    left, right = _store_call(store.version, before), _store_call(store.version, after)
    if left["workspace_id"] != workspace_id or right["workspace_id"] != workspace_id:
        raise HTTPException(404, detail="Version not found in workspace")
    return ApiResponse(success=True, data=_store_call(compare_versions, left, right))


@router.get("/{workspace_id}")
def get_workspace(workspace_id: str):
    return ApiResponse(success=True, data=_store_call(ResearchWorkspaceStore().workspace, workspace_id))
