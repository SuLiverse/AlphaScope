"""数据源配置 API — 预置付费源目录 / 权重启停 / API Key 管理 / 连通测试。

端点:
  GET  /api/datasources/presets        预置付费数据源目录 (含官网跳转/说明/key状态)
  GET  /api/datasources/config         所有数据源在各 data_type 下的优先级/启停
  PUT  /api/datasources/config         更新某 provider 在某 data_type 的启停/优先级 (热生效)
  GET  /api/datasources/credentials    列出已存 key (脱敏)
  POST /api/datasources/credentials    保存某数据源 key (加密落盘 + 热重载)
  DELETE /api/datasources/credentials/{name}  删除某数据源 key
  POST /api/datasources/credentials/{name}/test  测试某数据源连通 (用已存 key)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import datasource_config as dsc
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/datasources", tags=["datasources"])


class ProviderConfigUpdate(BaseModel):
    provider: str = Field(..., description="数据源名称, 如 tushare")
    data_type: str = Field(..., description="数据类型, 如 prices / fundamentals / reports")
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=100)


class CredentialSave(BaseModel):
    name: str = Field(..., description="数据源名称, 如 tushare")
    api_key: str = Field(..., description="API Key 明文, 后端加密存储")
    token_env: str | None = None


@router.get("/presets")
def presets() -> ApiResponse:
    """预置付费数据源目录 (含官网跳转、特点、key 是否已配置)。"""
    return ApiResponse(success=True, data={"datasources": dsc.list_presets()})


@router.get("/config")
def get_config() -> ApiResponse:
    """所有数据源在各 data_type 下的优先级/启停。"""
    return ApiResponse(success=True, data=dsc.get_config_summary())


@router.put("/config")
def put_config(req: ProviderConfigUpdate) -> ApiResponse:
    """更新某 provider 在某 data_type 的启停/优先级 (落盘 + 热重载, 立即生效)。"""
    try:
        result = dsc.update_provider_config(
            provider_name=req.provider,
            data_type=req.data_type,
            enabled=req.enabled,
            priority=req.priority,
        )
        return ApiResponse(success=True, data=result, message="数据源配置已保存并热生效。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/credentials")
def list_credentials() -> ApiResponse:
    """列出已保存的数据源 key (脱敏)。"""
    _creds = dsc._list_credentials_map()  # 已脱敏
    return ApiResponse(success=True, data={"credentials": list(_creds.values())})


@router.post("/credentials")
def save_credential(req: CredentialSave) -> ApiResponse:
    """保存数据源 API Key (加密落盘 + 注入环境变量 + 热重载)。"""
    try:
        result = dsc.save_credential(req.name, req.api_key, req.token_env)
        return ApiResponse(success=True, data=result, message="API Key 已加密保存并立即生效。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/credentials/{name}")
def delete_credential(name: str) -> ApiResponse:
    """删除某数据源 key。"""
    ok = dsc.delete_credential(name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"数据源 {name} 未保存凭证")
    return ApiResponse(success=True, data={"deleted": name}, message="凭证已删除。")


@router.post("/credentials/{name}/test")
def test_credential(name: str) -> ApiResponse:
    """测试某数据源连通性 (检查 registry 中该 provider 是否已注册并 healthy)。"""
    from backend.providers.registry import get_registry

    registry = get_registry()
    target = registry.get_provider(name)
    if target is None:
        return ApiResponse(
            success=False,
            error=f"数据源 {name} 未注册 (可能未填 Key 或依赖未安装)",
            error_code="DATASOURCE_NOT_REGISTERED",
        )
    # provider.health 是 ProviderHealth 对象 (注意不是 health_check() 那个返回 dict 的方法)
    health = target.health
    status = health.status.value if hasattr(health.status, "value") else str(health.status)
    return ApiResponse(
        success=True,
        data={
            "name": name,
            "status": status,
            "consecutive_failures": health.consecutive_failures,
            "avg_latency_ms": round(health.avg_latency_ms, 1),
            "last_error": health.error_message,
            "data_types": target.data_types,
            "markets": target.markets,
        },
        message=f"数据源 {name} 当前状态: {status}",
    )
