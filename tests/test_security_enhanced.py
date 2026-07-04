"""Tests for Security Enhancements — key_vault AES-GCM + log_sanitizer"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


class TestKeyVault:
    """测试 key_vault 加密/解密"""

    def test_encrypt_without_master_key_refuses_non_empty_key_by_default(self):
        """Non-empty API keys must not be encrypted with the repository-known fallback key."""
        from backend.security.key_vault import encrypt_key

        with patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "", "AI_FINANCE_ALLOW_DEV_KEY_FALLBACK": ""},
            clear=False,
        ):
            with pytest.raises(RuntimeError, match="AI_FINANCE_MASTER_KEY"):
                encrypt_key("sk-test-1234567890abcdef")

    def test_encrypt_decrypt_roundtrip_requires_explicit_dev_fallback_opt_in(self):
        """Dev fallback encryption remains available only for explicit local-development opt-in."""
        from backend.security.key_vault import decrypt_key, encrypt_key

        with patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "", "AI_FINANCE_ALLOW_DEV_KEY_FALLBACK": "1"},
            clear=False,
        ):
            encrypted = encrypt_key("sk-test-1234567890abcdef")
            assert encrypted
            decrypted = decrypt_key(encrypted)
            assert decrypted == "sk-test-1234567890abcdef"

    def test_encrypt_empty(self):
        from backend.security.key_vault import encrypt_key

        assert encrypt_key("") == ""

    def test_decrypt_empty(self):
        from backend.security.key_vault import decrypt_key

        assert decrypt_key("") == ""

    def test_mask_key(self):
        from backend.security.key_vault import mask_key

        assert mask_key("sk-abcdefghijklmnop") == "sk-a...mnop"
        assert mask_key("short") == "****"
        assert mask_key("") == "****"

    def test_validate_key_format(self):
        from backend.security.key_vault import validate_key_format

        assert validate_key_format("sk-abc123def456", "deepseek") is True
        assert validate_key_format("invalid", "deepseek") is False
        assert validate_key_format("short") is False

    def test_aes_encrypt_decrypt_roundtrip(self):
        """AES-GCM 模式加密解密往返（如果 cryptography 可用）"""
        from backend.security.key_vault import _HAS_AES, decrypt_key, encrypt_key

        if not _HAS_AES:
            pytest.skip("cryptography 库未安装")

        with patch.dict(os.environ, {"AI_FINANCE_MASTER_KEY": "test-master-key-123"}, clear=False):
            encrypted = encrypt_key("sk-real-api-key-1234567890")
            assert encrypted.startswith("aes:")
            decrypted = decrypt_key(encrypted)
            assert decrypted == "sk-real-api-key-1234567890"

    def test_aes_wrong_key_fails(self):
        """不同 master key 解密失败"""
        from backend.security.key_vault import _HAS_AES, decrypt_key, encrypt_key

        if not _HAS_AES:
            pytest.skip("cryptography 库未安装")

        with patch.dict(os.environ, {"AI_FINANCE_MASTER_KEY": "key-A"}, clear=False):
            encrypted = encrypt_key("sk-secret-key")

        with patch.dict(os.environ, {"AI_FINANCE_MASTER_KEY": "key-B"}, clear=False):
            decrypted = decrypt_key(encrypted)

        assert decrypted == ""


class TestLogSanitizer:
    """测试日志脱敏"""

    def test_sanitize_api_key(self):
        from backend.security.log_sanitizer import sanitize_log_message

        msg = "Using key sk-abc123def456ghi789jkl012mno"
        result = sanitize_log_message(msg)
        assert "sk-abc123" not in result
        assert "****" in result

    def test_sanitize_aws_key(self):
        from backend.security.log_sanitizer import sanitize_log_message

        msg = "AWS key AKIAIOSFODNN7EXAMPLE"
        result = sanitize_log_message(msg)
        assert "AKIAIOSFODNN7" not in result

    def test_sanitize_bearer_token(self):
        from backend.security.log_sanitizer import sanitize_log_message

        msg = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = sanitize_log_message(msg)
        assert "eyJhbGci" not in result

    def test_sanitize_dict(self):
        from backend.security.log_sanitizer import sanitize_dict

        data = {
            "api_key": "sk-very-long-key-1234567890",
            "name": "test",
            "nested": {"password": "my-secret-password-123"},
        }
        result = sanitize_dict(data)
        assert "sk-very-long-key" not in str(result)
        assert result["name"] == "test"

    def test_sanitize_dict_sensitive_fields(self):
        from backend.security.log_sanitizer import sanitize_dict

        data = {"token": "abc123def456ghi789", "normal": "keep this"}
        result = sanitize_dict(data)
        assert result["token"] != "abc123def456ghi789"
        assert result["normal"] == "keep this"

    def test_sanitize_empty(self):
        from backend.security.log_sanitizer import sanitize_dict, sanitize_log_message

        assert sanitize_log_message("") == ""
        assert sanitize_dict({}) == {}
