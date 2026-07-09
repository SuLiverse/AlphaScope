"""
Key Vault: API Key 加密存储与管理。

职责：
- API Key 加密/解密（AES-GCM 优先，XOR 降级）
- Key 轮换支持
- 脱敏显示
- 未设 master key 时拒绝加密
"""

import base64
import hashlib
import logging
import os

logger = logging.getLogger(__name__)

# 检查 cryptography 库是否可用
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _HAS_AES = True
except ImportError:
    _HAS_AES = False
    logger.info("cryptography 库未安装，API Key 加密降级为 XOR 模式")


def _dev_fallback_enabled() -> bool:
    """Return True only when dev fallback encryption is explicitly enabled."""
    return os.getenv("AI_FINANCE_ALLOW_DEV_KEY_FALLBACK", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_encryption_key(*, allow_dev_fallback: bool = True) -> bytes:
    """获取加密密钥（从环境变量）。"""
    key = os.getenv("AI_FINANCE_MASTER_KEY", "")
    if key:
        return hashlib.sha256(key.encode()).digest()

    if not allow_dev_fallback or not _dev_fallback_enabled():
        raise RuntimeError(
            "AI_FINANCE_MASTER_KEY must be set before encrypting non-empty API keys. "
            "Set AI_FINANCE_ALLOW_DEV_KEY_FALLBACK=1 only for local development."
        )

    # 无 master key 时仅在显式本地开发 opt-in 后使用 dev key 并警告
    logger.warning(
        "未设置 AI_FINANCE_MASTER_KEY 环境变量，正在使用显式启用的开发 fallback key。"
        "仅可用于本地开发，请勿用于生产环境。"
    )
    return hashlib.sha256(b"dev-only-not-for-production").digest()


def encrypt_key(plain_key: str) -> str:
    """
    加密 API Key。

    优先使用 AES-GCM（需 cryptography 库 + AI_FINANCE_MASTER_KEY）。
    降级为 XOR + base64。
    """
    if not plain_key:
        return ""

    key = _get_encryption_key()
    data = plain_key.encode("utf-8")

    if _HAS_AES:
        try:
            # AES-GCM: 12 字节 nonce + 密文 + 16 字节 tag
            import os as _os

            nonce = _os.urandom(12)
            aes = AESGCM(key[:32])
            ct = aes.encrypt(nonce, data, None)
            # 格式: "aes:" + base64(nonce + ct)
            payload = base64.urlsafe_b64encode(nonce + ct).decode("ascii")
            return f"aes:{payload}"
        except Exception as e:
            if not _dev_fallback_enabled():
                raise RuntimeError(
                    "AES-GCM 加密失败且未允许开发降级。"
                    "请安装 cryptography 或设置 AI_FINANCE_ALLOW_DEV_KEY_FALLBACK=1（仅本地开发）。"
                ) from e
            logger.warning("AES-GCM 加密失败，开发模式降级为 XOR: %s", e)
    elif not _dev_fallback_enabled():
        raise RuntimeError(
            "cryptography 未安装，拒绝使用弱 XOR 加密。"
            "请 pip install cryptography，或仅在本地设置 AI_FINANCE_ALLOW_DEV_KEY_FALLBACK=1。"
        )

    # XOR 仅在显式开发 opt-in 后可用（兼容旧密文解密仍见 decrypt_key）
    logger.warning("正在使用 XOR 弱加密写入新密钥（开发模式）。请勿用于生产。")
    encrypted = bytes(d ^ key[i % len(key)] for i, d in enumerate(data))
    return "xor:" + base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_key(encrypted_key: str) -> str:
    """
    解密 API Key。

    自动识别加密格式（aes: / xor:）。
    """
    if not encrypted_key:
        return ""

    key = _get_encryption_key()

    # AES-GCM 解密
    if encrypted_key.startswith("aes:"):
        if not _HAS_AES:
            logger.error("无法解密 AES-GCM 密文：cryptography 库未安装")
            return ""
        try:
            payload = base64.urlsafe_b64decode(encrypted_key[4:].encode("ascii"))
            nonce = payload[:12]
            ct = payload[12:]
            aes = AESGCM(key[:32])
            return aes.decrypt(nonce, ct, None).decode("utf-8")
        except Exception as e:
            logger.error("AES-GCM 解密失败: %s", e)
            return ""

    # XOR 解密（兼容旧格式）
    raw = encrypted_key
    if raw.startswith("xor:"):
        raw = raw[4:]

    try:
        data = base64.urlsafe_b64decode(raw.encode("ascii"))
        decrypted = bytes(d ^ key[i % len(key)] for i, d in enumerate(data))
        return decrypted.decode("utf-8")
    except Exception:
        return ""


def mask_key(key: str) -> str:
    """脱敏显示 API Key，只显示前4位和后4位"""
    if not key or len(key) < 12:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


def validate_key_format(key: str, provider: str = "") -> bool:
    """验证 API Key 格式是否合理"""
    if not key or len(key) < 8:
        return False
    if provider == "deepseek" and not key.startswith("sk-"):
        return False
    if provider == "openai" and not key.startswith("sk-"):
        return False
    return True
