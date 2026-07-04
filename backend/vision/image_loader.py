"""
Image Loader: 图片加载与预处理。

职责：
- 加载上传的图片文件
- 验证图片格式和大小
- 转换为 base64 供视觉模型使用
"""

import base64
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


@dataclass
class LoadedImage:
    """加载后的图片数据"""

    base64_data: str
    mime_type: str
    width: int = 0
    height: int = 0
    file_hash: str = ""
    filename: str = ""
    size_bytes: int = 0


def load_image(file_path: str) -> Optional[LoadedImage]:
    """加载图片文件并转为 base64"""
    p = Path(file_path)
    if not p.exists():
        return None
    if p.suffix.lower() not in SUPPORTED_FORMATS:
        return None
    if p.stat().st_size > MAX_FILE_SIZE:
        return None

    data = p.read_bytes()
    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(p.suffix.lower(), "image/png")
    b64 = base64.b64encode(data).decode("utf-8")
    file_hash = hashlib.md5(data).hexdigest()

    return LoadedImage(
        base64_data=b64,
        mime_type=mime,
        file_hash=file_hash,
        filename=p.name,
        size_bytes=len(data),
    )


def load_image_from_bytes(data: bytes, filename: str = "upload.png") -> Optional[LoadedImage]:
    """从字节数据加载图片"""
    if len(data) > MAX_FILE_SIZE:
        return None

    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        suffix = ".png"

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime = mime_map.get(suffix, "image/png")
    b64 = base64.b64encode(data).decode("utf-8")
    file_hash = hashlib.md5(data).hexdigest()

    return LoadedImage(
        base64_data=b64,
        mime_type=mime,
        file_hash=file_hash,
        filename=filename,
        size_bytes=len(data),
    )
