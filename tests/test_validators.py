"""Tests for backend.validators — pure-function schema normalizers."""

import socket

import pytest

from llm_agents import (
    _extract_json,
    normalize_openai_base_url,
    validate_custom_base_url,
)

from validators import (
    validate_agent_output,
    validate_expert_output,
    AGENT_SIGNALS,
    EXPERT_ACTIONS,
    EVIDENCE_TYPES,
)


# ---------------- validate_agent_output ----------------


class TestValidateAgentOutput:
    def test_full_valid_payload_passes_through(self):
        payload = {
            "signal": "买入",
            "confidence": 75,
            "reason": "基本面+主力资金双重利好",
            "evidence": [
                {
                    "type": "fund_flow",
                    "claim": "近5日主力净流入2.3亿",
                    "data_date": "2026-05-16",
                }
            ],
            "invalid_if": "跌破MA20且主力连续3日流出",
            "risks": ["板块情绪偏弱"],
        }
        out = validate_agent_output(payload)
        assert out["signal"] == "买入"
        assert out["confidence"] == 75
        assert out["reason"].startswith("基本面")
        assert out["evidence"][0]["type"] == "fund_flow"
        assert out["evidence"][0]["data_date"] == "2026-05-16"
        assert out["invalid_if"].startswith("跌破")
        assert out["risks"] == ["板块情绪偏弱"]

    def test_missing_fields_get_safe_defaults(self):
        out = validate_agent_output({})
        assert out["signal"] == "观望"
        assert out["confidence"] == 50
        assert out["reason"] == "无明确观点"
        assert out["evidence"] == []
        assert out["invalid_if"] == ""
        assert out["risks"] == []

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("buy", "买入"),
            ("sell", "卖出"),
            ("LONG", "买入"),
            ("看多", "买入"),
            ("看空", "卖出"),
            ("hold", "观望"),
            ("建议买入", "买入"),
            ("", "观望"),
            (None, "观望"),
            ("nonsense", "观望"),
        ],
    )
    def test_signal_aliases_collapse_to_canonical(self, raw, expected):
        assert validate_agent_output({"signal": raw})["signal"] == expected
        assert validate_agent_output({"signal": expected})["signal"] in AGENT_SIGNALS

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (200, 100),
            (-5, 0),
            ("80", 80),
            ("75%", 75),
            (" 60 ", 60),
            ("abc", 50),  # 非法 -> default
            (None, 50),
            (float("nan"), 50),
        ],
    )
    def test_confidence_clamped_and_coerced(self, raw, expected):
        assert validate_agent_output({"confidence": raw})["confidence"] == expected

    def test_evidence_string_list_is_normalized(self):
        out = validate_agent_output({"evidence": ["MA20 上行", "成交量放大"]})
        assert len(out["evidence"]) == 2
        for ev in out["evidence"]:
            assert ev["type"] == "other"
            assert ev["claim"] in ("MA20 上行", "成交量放大")
            assert ev["data_date"] == ""

    def test_evidence_multiline_string_split_into_items(self):
        out = validate_agent_output({"evidence": "1. MA20 上行\n2. 成交量放大"})
        claims = [ev["claim"] for ev in out["evidence"]]
        assert any("MA20" in c for c in claims)
        assert any("成交量" in c for c in claims)

    def test_evidence_unknown_type_collapses_to_other(self):
        out = validate_agent_output(
            {
                "evidence": [{"type": "vibes", "claim": "感觉不错"}],
            }
        )
        assert out["evidence"][0]["type"] == "other"

    def test_evidence_empty_claim_dropped(self):
        out = validate_agent_output(
            {
                "evidence": [
                    {"type": "technical", "claim": "   "},
                    {"type": "fund_flow", "claim": "净流入"},
                ],
            }
        )
        assert len(out["evidence"]) == 1
        assert out["evidence"][0]["claim"] == "净流入"

    def test_evidence_max_items_trimmed(self):
        many = [{"type": "other", "claim": f"point {i}"} for i in range(20)]
        out = validate_agent_output({"evidence": many})
        assert len(out["evidence"]) <= 8

    def test_risks_normalized_from_string(self):
        out = validate_agent_output({"risks": "1) 利率上行\n2) 行业政策不确定"})
        assert len(out["risks"]) >= 1
        assert all(isinstance(r, str) for r in out["risks"])

    def test_non_dict_input_returns_safe_shell(self):
        out = validate_agent_output("not a dict")
        assert out["signal"] == "观望"
        assert out["evidence"] == []


# ---------------- validate_expert_output ----------------


class TestValidateExpertOutput:
    def test_full_valid_payload_passes_through(self):
        out = validate_expert_output(
            {
                "view": "短期超买",
                "action": "建议减持",
                "position": "30%",
                "stop_loss": "1500.5",
                "evidence": ["RSI > 80", {"type": "technical", "claim": "周线高位"}],
                "invalid_if": "放量突破压力位",
                "risks": ["板块情绪转弱"],
            }
        )
        assert out["view"] == "短期超买"
        assert out["action"] == "减持"
        assert out["position"] == 30
        assert out["stop_loss"] == 1500.5
        assert len(out["evidence"]) == 2
        assert out["invalid_if"].startswith("放量突破")
        assert out["risks"] == ["板块情绪转弱"]

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("买入", "买入"),
            ("建议卖出", "卖出"),
            ("观望", "观望"),
            (
                "减仓",
                "观望",
            ),  # not on whitelist, not a substring of any action -> default
            ("减持", "减持"),
            ("", "观望"),
            ("foo", "观望"),
        ],
    )
    def test_action_collapses_to_canonical(self, raw, expected):
        assert validate_expert_output({"action": raw})["action"] == expected
        for canonical in EXPERT_ACTIONS:
            assert validate_expert_output({"action": canonical})["action"] == canonical

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (-5, 0),
            (250, 100),
            ("50", 50),
            ("75%", 75),
            ("abc", 0),
            (None, 0),
        ],
    )
    def test_position_clamped(self, raw, expected):
        assert validate_expert_output({"position": raw})["position"] == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (None, 0.0),
            ("", 0.0),
            ("not a number", 0.0),
            (-10, 0.0),  # negative -> 0
            ("1500.5", 1500.5),
            (1500, 1500.0),
        ],
    )
    def test_stop_loss_coerced(self, raw, expected):
        out = validate_expert_output({"stop_loss": raw})
        assert out["stop_loss"] == expected

    def test_non_dict_input_returns_safe_shell(self):
        out = validate_expert_output(42)
        assert out["view"]
        assert out["action"] == "观望"
        assert out["position"] == 0
        assert out["evidence"] == []


# ---------------- module surface ----------------


def test_evidence_type_whitelist_includes_finance_categories():
    must_have = {
        "fund_flow",
        "technical",
        "fundamental",
        "news",
        "research",
        "macro",
        "other",
    }
    assert must_have.issubset(EVIDENCE_TYPES)


def test_extract_json_uses_balanced_object_block():
    assert _extract_json('prefix {"a": {"b": 1}, "c": "}"} suffix') == {
        "a": {"b": 1},
        "c": "}",
    }
    assert _extract_json('bad {"a": 1} middle {"b": 2}') == {"a": 1}


def test_normalize_openai_base_url_preserves_version_paths():
    assert normalize_openai_base_url("api.example.com") == "https://api.example.com/v1"
    assert (
        normalize_openai_base_url("https://api.example.com/v2")
        == "https://api.example.com/v2"
    )


def test_validate_custom_base_url_rejects_local_addresses():
    with pytest.raises(ValueError):
        validate_custom_base_url("http://localhost:8000/v1")
    with pytest.raises(ValueError):
        validate_custom_base_url("http://127.0.0.1:8000/v1")
    with pytest.raises(ValueError):
        validate_custom_base_url("http://169.254.169.254/latest/meta-data")


def test_validate_custom_base_url_rejects_resolved_local_addresses(monkeypatch):
    """DNS names resolving to local/private/link-local addresses are unsafe by default."""

    def fake_getaddrinfo(host, *args, **kwargs):
        resolved = {
            "127.0.0.1.nip.io": "127.0.0.1",
            "10.0.0.1.sslip.io": "10.0.0.1",
        }[host]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (resolved, 443))]

    monkeypatch.delenv("ALLOW_LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ValueError, match="默认禁止连接"):
        validate_custom_base_url("https://127.0.0.1.nip.io/v1")
    with pytest.raises(ValueError, match="默认禁止连接"):
        validate_custom_base_url("https://10.0.0.1.sslip.io/v1")


def test_validate_custom_base_url_rejects_unresolved_hostname_by_default(monkeypatch):
    """Unresolved DNS names cannot be proven public and are unsafe by default."""

    def fail_resolution(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.delenv("ALLOW_LOCAL_LLM_BASE_URL", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    with pytest.raises(ValueError, match="DNS|解析"):
        validate_custom_base_url("https://unresolved.example.invalid/v1")


def test_validate_custom_base_url_allows_unresolved_hostname_with_opt_in(monkeypatch):
    """Explicit local LLM opt-in preserves offline/dev hostname support."""

    def fail_resolution(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    assert (
        validate_custom_base_url("https://unresolved.example.invalid/v1")
        == "https://unresolved.example.invalid/v1"
    )


def test_validate_custom_base_url_allows_resolved_local_addresses_with_opt_in(
    monkeypatch,
):
    """Explicit local LLM opt-in bypasses DNS SSRF rejection for developer proxies."""

    def fail_if_resolved(*args, **kwargs):
        raise AssertionError("local opt-in should bypass DNS resolution")

    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    monkeypatch.setattr(socket, "getaddrinfo", fail_if_resolved)

    assert (
        validate_custom_base_url("https://127.0.0.1.nip.io/v1")
        == "https://127.0.0.1.nip.io/v1"
    )


def test_validate_custom_base_url_allows_local_addresses_with_opt_in(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")

    assert (
        validate_custom_base_url("http://localhost:8000/v1")
        == "http://localhost:8000/v1"
    )
