"""M4 · 投资人 persona 扩充 — experts.yaml schema 校验。"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
EXPERTS_YAML = REPO / "config" / "experts.yaml"


def _load() -> dict:
    return yaml.safe_load(EXPERTS_YAML.read_text(encoding="utf-8"))


class TestExpertsYaml:
    def test_parses(self):
        assert isinstance(_load(), dict)

    def test_experts_required_fields(self):
        experts = _load().get("experts") or []
        assert len(experts) >= 59
        for e in experts:
            assert e.get("key"), f"expert 缺 key: {e}"
            assert e.get("name"), f"{e.get('key')} 缺 name"
            assert e.get("system_prompt"), f"{e.get('key')} 缺 system_prompt"
            assert e.get("preferred_model"), f"{e.get('key')} 缺 preferred_model"

    def test_no_duplicate_keys(self):
        keys = [e["key"] for e in (_load().get("experts") or [])]
        assert len(keys) == len(set(keys)), "experts 存在重复 key"

    def test_new_personas_present(self):
        keys = {e["key"] for e in (_load().get("experts") or [])}
        for k in [
            "duan",
            "fengliu",
            "zhangkun",
            "dengxiaofeng",
            "dalio",
            "munger",
            "graham",
            "soros",
        ]:
            assert k in keys, f"缺少新增 persona: {k}"

    def test_focus_dims_are_lists(self):
        for e in _load().get("experts") or []:
            fd = e.get("focus_dims")
            if fd is not None:
                assert isinstance(fd, list)

    def test_teams_intact(self):
        teams = _load().get("teams") or []
        sp = [t for t in teams if t.get("id") == "stock-partner"]
        assert sp, "stock-partner 团队丢失"
        assert len(sp[0].get("members") or []) >= 5

    def test_output_schema_preserved(self):
        assert _load().get("output_schema")


class TestExpertPanelConsumes:
    def test_expert_panel_imports(self):
        import backend.expert_panel  # noqa: F401

    def test_expert_configs_load(self):
        """expert_panel 的配置加载器应能读入扩充后的 experts.yaml 而不报错。"""
        import backend.expert_panel as ep

        loader = None
        for name in (
            "load_expert_configs",
            "load_experts",
            "_load_experts",
            "load_team_configs",
        ):
            if hasattr(ep, name):
                loader = getattr(ep, name)
                break
        if loader is None:
            import pytest

            pytest.skip("未发现公开的 experts 加载函数")
        result = loader()
        assert result is not None


def test_v2_member_prompt_files_all_load_nonempty():
    """所有 v2 team member 的 promptFile 必须存在且非空(防止路径写错/文件缺失回归)。

    回归: 上轮 5 个 member(sentiment/fund_flow/devil/compliance/summarizer)的 promptFile
    指向不存在文件, load_prompt_file 静默返回空 → 空白人设。此测试锁住。
    """
    from backend.expert_panel import load_prompt_file

    data = _load()
    teams = data.get("teams") or []
    assert teams, "应至少有一个 v2 team"
    for team in teams:
        members = team.get("members") or []
        for m in members:
            pf = m.get("promptFile")
            if not pf:
                continue
            content = load_prompt_file(pf)
            assert content, f"member {m.get('id')} 的 promptFile {pf} 加载为空(文件缺失?)"
            assert len(content) > 50, f"member {m.get('id')} 的 prompt {pf} 内容过短(疑似 stub)"
