"""TickFlow HTTP/JSON 自定义数据表 API(v1.9.19)。

让用户配置外部 JSON 行情接口(URL + 记录路径 + 字段映射), 点「拉取」把远端 JSON
映射成标准 OHLCV 物化到本地缓存, 此后像 csv_upload 一样进入价格查询与回测面板。
网络仅在「拉取/预览」时发生且失败安全;热路径读本地缓存, 离线确定性。

端点:
  GET    /api/tickflow/sources              列出已配置源
  POST   /api/tickflow/sources             新增/更新源
  DELETE /api/tickflow/sources/{id}        删除源
  POST   /api/tickflow/sources/{id}/refresh 拉取并物化(可选 limit)
  POST   /api/tickflow/preview             试抓 URL, 返回样本记录 + 推断字段映射
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, field_validator

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickflow", tags=["tickflow"])


# 请求体必须是模块级类(FastAPI + from __future__ import annotations 前置引用求值)。
def _validate_http_url(url: str) -> str:
    """url 非空时必须是 http/https 开头(防完全无效地址到 dispatch 时才崩)。"""
    u = (url or "").strip()
    if u and not (u.startswith("http://") or u.startswith("https://")):
        raise ValueError("url 必须以 http:// 或 https:// 开头")
    return u


class SourceBody(BaseModel):
    """HTTP/JSON 源配置。"""

    id: Optional[str] = None
    name: str = "自定义源"
    url: str = ""
    symbol: str = ""
    method: Literal["GET", "POST"] = "GET"
    headers: Optional[dict[str, Any]] = None
    body: Optional[Any] = None
    records_path: str = ""
    field_map: Optional[dict[str, Any]] = None

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class PreviewBody(BaseModel):
    """试抓预览请求。"""

    url: str = ""
    method: Literal["GET", "POST"] = "GET"
    headers: Optional[dict[str, Any]] = None
    body: Optional[Any] = None
    records_path: str = ""

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


@router.get("/sources", response_model=ApiResponse[dict])
def tickflow_sources():
    """列出已配置的 HTTP/JSON 源。"""
    from backend.providers.http_json_provider import list_sources

    sources = list_sources()
    return ApiResponse(
        success=True,
        data={"total": len(sources), "sources": sources},
    )


@router.post("/sources", response_model=ApiResponse[dict])
def tickflow_save_source(body: SourceBody):
    """新增或更新一个源(按 id 去重)。"""
    from backend.providers.http_json_provider import save_source

    saved = save_source(body.model_dump())
    if not saved:
        return ApiResponse(success=False, error="保存失败")
    return ApiResponse(success=True, data=saved)


@router.delete("/sources/{source_id}", response_model=ApiResponse[dict])
def tickflow_delete_source(source_id: str):
    """删除一个源(不删已物化缓存)。"""
    from backend.providers.http_json_provider import delete_source

    ok = delete_source(source_id)
    return ApiResponse(success=ok, data={"deleted": ok})


@router.post("/sources/{source_id}/refresh", response_model=ApiResponse[dict])
def tickflow_refresh(source_id: str, limit: int = Query(1000, ge=1, le=2000)):
    """拉取一次源并物化(失败安全, 失败不清空既有缓存)。"""
    from backend.providers.http_json_provider import refresh_source

    result = refresh_source(source_id, limit=limit)
    return ApiResponse(
        success=bool(result.get("ok")),
        data=result,
        error=result.get("error") if not result.get("ok") else None,
    )


@router.post("/preview", response_model=ApiResponse[dict])
def tickflow_preview(body: PreviewBody):
    """试抓 URL, 返回样本记录 + 推断字段映射(辅助配置, 不物化)。"""
    from backend.providers.http_json_provider import preview_fetch

    result = preview_fetch(
        url=body.url,
        method=body.method,
        headers=body.headers,
        body=body.body,
        records_path=body.records_path,
    )
    return ApiResponse(
        success=bool(result.get("ok")),
        data=result,
        error=result.get("error") if not result.get("ok") else None,
    )
