"""多空辩论裁决合成器测试 (v1.9.14)。

覆盖:阵营划分、反方质询四来源(看空 Agent / 风控否决 / 数据缺失 / Critic 分歧)、
裁决标签、共识度计算、失败安全(脏输入不抛)、研报小节渲染。全部离线、确定性。
"""

from __future__ import annotations

from backend.agents.debate import (
    DEGRADED,
    OK,
    format_debate_section,
    synthesize_debate,
)


def _agent(signal: str, conf: float, name: str = "", reason: str = "理由", eids=None):
    return {
        "signal": signal,
        "confidence": conf,
        "reason": reason,
        "name": name or signal,
        "evidence_ids": eids or [],
        "ok": True,
    }


class TestCamps:
    def test_all_bull_is_consensus(self):
        agents = {
            "fund": _agent("买入", 85, "基本面"),
            "tech": _agent("买入", 80, "技术面"),
        }
        r = synthesize_debate(agents)
        assert r.status == OK
        assert r.consensus in ("看多共识", "偏看多")
        assert r.n_bull == 2 and r.n_bear == 0
        assert len(r.bull_points) == 2
        assert r.consensus_score >= 50  # 一边倒

    def test_bull_vs_bear_is_divergence(self):
        agents = {
            "fund": _agent("买入", 80, "基本面"),
            "tech": _agent("卖出", 70, "技术面"),
        }
        r = synthesize_debate(agents)
        assert r.consensus in ("多空分歧", "高度分歧")
        assert r.n_bull == 1 and r.n_bear == 1
        assert any(p.kind == "agent" for p in r.bull_points)
        assert any(p.kind == "agent" for p in r.bear_points)

    def test_all_hold_is_neutral(self):
        agents = {"a": _agent("观望", 50), "b": _agent("观望", 40)}
        r = synthesize_debate(agents)
        assert r.consensus == "中性观望"
        assert r.n_neutral == 2

    def test_low_conviction_bull_adds_bear_challenge(self):
        agents = {"fund": _agent("买入", 35, "基本面")}  # 看多但信心<50
        r = synthesize_debate(agents)
        assert any(p.kind == "low_conviction" for p in r.bear_points)


class TestBearSources:
    def test_risk_veto_dominates(self):
        agents = {"fund": _agent("买入", 90, "基本面")}
        rg = {"vetoed": True, "veto_reasons": ["命中黑名单", "集中度超限"]}
        r = synthesize_debate(agents, risk_gate=rg)
        assert r.consensus == "风控否决"
        assert any(p.kind == "risk_veto" for p in r.bear_points)
        assert "风控" in r.ruling

    def test_data_gaps_become_bear_points(self):
        agents = {"fund": _agent("买入", 70)}
        dv = {"missing": ["资金流"], "anomalies": ["换手率"], "stale": ["公告"]}
        r = synthesize_debate(agents, data_verification=dv)
        kinds = [p.kind for p in r.bear_points]
        assert kinds.count("data_gap") == 3

    def test_critic_high_divergence_adds_bear(self):
        agents = {"fund": _agent("买入", 70)}
        critic = {"divergence": {"level": "高", "summary": "技术面与基本面背离"}}
        r = synthesize_debate(agents, critic=critic)
        assert r.divergence_level == "高"
        assert any(p.kind == "critic_divergence" for p in r.bear_points)

    def test_critic_low_divergence_not_added(self):
        agents = {"fund": _agent("买入", 70)}
        critic = {"divergence": {"level": "低", "summary": "基本一致"}}
        r = synthesize_debate(agents, critic=critic)
        assert not any(p.kind == "critic_divergence" for p in r.bear_points)


class TestSecondRound:
    def test_second_round_adds_cross_examine(self):
        agents = {
            "fund": _agent("买入", 85, "基本面"),
            "tech": _agent("买入", 40, "技术面"),
        }
        base = synthesize_debate(agents)
        r2 = synthesize_debate(agents, second_round=True)
        assert r2.status == OK
        kinds = [p.kind for p in r2.bear_points]
        assert "cross_examine" in kinds
        assert len(r2.bear_points) >= len(base.bear_points)

    def test_second_round_default_off(self):
        agents = {"fund": _agent("买入", 80, "基本面")}
        r = synthesize_debate(agents)
        assert not any(p.kind == "cross_examine" for p in r.bear_points + r.bull_points)

    def test_second_round_recalculates_consensus_after_challenge(self):
        agents = {"fund": _agent("买入", 5, "低置信多头")}
        r = synthesize_debate(agents, second_round=True)

        assert r.bear_strength > r.bull_strength
        assert r.consensus == "偏看空"
        assert r.consensus_score > 0

    def test_low_confidence_bear_is_challenged_by_bull_side(self):
        agents = {"tech": _agent("卖出", 20, "低置信空头")}
        r = synthesize_debate(agents, second_round=True)

        assert any(p.source == "tech" and p.side == "bull" for p in r.bull_points)


class TestFailSafe:
    def test_empty_agents_never_raises(self):
        r = synthesize_debate({})
        assert r.status == OK
        assert r.consensus in ("未知", "中性观望")

    def test_none_agents(self):
        r = synthesize_debate(None)
        assert r.status == OK

    def test_garbage_values_skipped(self):
        r = synthesize_debate({"x": "not a dict", "y": 123, "z": None})
        assert r.status == OK
        assert r.n_bull == 0 and r.n_bear == 0

    def test_non_numeric_confidence_safe(self):
        agents = {"a": {"signal": "买入", "confidence": "high", "reason": "x", "name": "A"}}
        r = synthesize_debate(agents)  # 不抛
        assert r.status == OK
        assert r.n_bull == 1


class TestRulingAndShape:
    def test_to_dict_shape(self):
        agents = {"fund": _agent("买入", 80), "tech": _agent("卖出", 60)}
        d = synthesize_debate(agents).to_dict()
        for key in (
            "status",
            "consensus",
            "consensus_score",
            "divergence_level",
            "bull_strength",
            "bear_strength",
            "n_bull",
            "n_bear",
            "n_neutral",
            "bull_points",
            "bear_points",
            "ruling",
            "disclaimer",
        ):
            assert key in d
        assert d["disclaimer"]
        assert isinstance(d["bull_points"], list)

    def test_format_section_contains_ruling_and_disclaimer(self):
        agents = {
            "fund": _agent("买入", 80, "基本面"),
            "tech": _agent("卖出", 70, "技术面"),
        }
        r = synthesize_debate(agents)
        section = format_debate_section(r)
        assert "多空辩论与裁决" in section
        assert "裁决" in section
        assert "不构成任何买卖指令" in section

    def test_format_section_empty_for_degraded(self):
        # 直接构造一个 degraded 报告
        from backend.agents.debate import _degraded

        assert format_debate_section(_degraded("x")) == ""
        assert _degraded("x").status == DEGRADED

    def test_strongest_point_first(self):
        agents = {
            "weak": _agent("买入", 55, "弱多"),
            "strong": _agent("买入", 92, "强多"),
        }
        r = synthesize_debate(agents)
        assert r.bull_points[0].confidence == 92  # 最强排前
