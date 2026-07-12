"""CSV/Excel 上传数据源 API(v1.9.4, compass §7.2)。

让用户上传自带行情数据, 自动发现 schema, 入价格查询面 —— 与内置数据源同样被
registry 选中用于回测/分析。

端点:
  GET    /api/providers/csv/datasets        列出已上传数据集(含 schema 概览)
  POST   /api/providers/csv/upload          上传 CSV/Excel(multipart file)
  DELETE /api/providers/csv/{filename}       删除某数据集
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, UploadFile

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/providers/csv", tags=["providers-csv"])


@router.get("/datasets", response_model=ApiResponse[dict])
def csv_datasets():
    """列出上传目录下所有 CSV/Excel 数据集及其 schema 概览。"""
    from backend.providers.csv_provider import list_datasets

    datasets = list_datasets()
    return ApiResponse(
        success=True,
        data={
            "total": len(datasets),
            "valid": sum(1 for d in datasets if d.get("valid")),
            "datasets": datasets,
        },
    )


@router.post("/upload", response_model=ApiResponse[dict])
async def csv_upload(file: UploadFile = File(...)):
    """上传 CSV/Excel 行情文件, 自动发现 schema 并返回概览。

    文件建议以「股票代码」命名(如 ``600519.csv``), 以便按代码匹配。
    """
    from backend.providers.csv_provider import MAX_UPLOAD_BYTES, save_upload

    try:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        summary = save_upload(file.filename or "upload.csv", content)
    except ValueError as e:
        return ApiResponse(success=False, error=str(e))
    except Exception as e:  # noqa: BLE001
        logger.warning("[csv_upload] 上传处理失败: %s", e)
        return ApiResponse(success=False, error=f"上传处理失败: {e}")

    if not summary.get("valid"):
        return ApiResponse(
            success=True,
            data={
                **summary,
                "warning": "已保存, 但未发现完整的 date/OHLC 列, 暂不能用于行情查询。"
                "请确认表头含 日期/开/高/低/收 等列。",
            },
        )
    return ApiResponse(success=True, data=summary)


@router.delete("/{filename}", response_model=ApiResponse[dict])
def csv_delete(filename: str):
    """删除一个已上传数据集(只按 basename, 防目录穿越)。"""
    from pathlib import Path

    from backend.providers.csv_provider import _csv_dir

    safe = Path(filename).name
    target = _csv_dir() / safe
    if not target.exists():
        return ApiResponse(success=False, error=f"未找到文件: {safe}")
    try:
        target.unlink()
    except Exception as e:  # noqa: BLE001
        return ApiResponse(success=False, error=f"删除失败: {e}")
    return ApiResponse(success=True, data={"deleted": safe})
