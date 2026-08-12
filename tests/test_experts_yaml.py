"""M4 · 投资人 persona 扩充 — experts.yaml schema 校验。"""

from __future__ import annotations

import os
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


def test_v1_persona_system_prompts_nonempty_not_stub():
    """所有 v1 expert persona 的 system_prompt 必须非空且 >100 字符(防 stub/空回退)。

    上轮升级了 39+ persona 的真实交易体系提示词。此测试锁住, 防止未来回归到占位/空。
    """
    data = _load()
    experts = data.get("experts") or []
    assert experts, "v1 experts 列表不应为空"
    short = []
    empty = []
    for e in experts:
        key = e.get("key", "?")
        prompt = (e.get("system_prompt") or "").strip()
        if not prompt:
            empty.append(key)
        elif len(prompt) < 100:
            short.append((key, len(prompt)))
    assert not empty, f"persona system_prompt 为空: {empty}"
    assert not short, f"persona system_prompt 过短(疑似 stub): {short}"


_MINIMAL_V2_YAML = """teams:
  - id: test-team
    displayName:
      zh: 测试团队
      en: Test Team
    members:
      - id: test-member
        displayName:
          zh: 测试成员
          en: Test Member
"""


def _bump_mtime(path: Path) -> None:
    """显式递增 mtime，规避 FAT/低粒度文件系统下 mtime 不变的问题。"""
    st = path.stat()
    os.utime(path, (st.st_atime + 2.0, st.st_mtime + 2.0))


class TestExpertsConfigMemoization:
    """Plan 012: experts.yaml 与 prompt 文件按 (path, mtime) 记忆化。"""

    @staticmethod
    def _spy_read_text(monkeypatch):
        orig = Path.read_text
        reads: list = []

        def spy(self, *args, **kwargs):
            reads.append(str(self))
            return orig(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", spy)
        return reads

    def test_a_config_memoized_single_disk_read(self, tmp_path, monkeypatch):
        from backend import expert_panel as ep

        yaml_path = tmp_path / "experts.yaml"
        yaml_path.write_text(_MINIMAL_V2_YAML, encoding="utf-8")
        reads = self._spy_read_text(monkeypatch)
        ep.reload_experts_config()
        try:
            ep.load_experts_config_v2(yaml_path)
            ep.load_experts_config_v2(yaml_path)
        finally:
            ep.reload_experts_config()
        assert reads.count(str(yaml_path)) == 1

    def test_b_change_invalidates_cache(self, tmp_path, monkeypatch):
        from backend import expert_panel as ep

        yaml_path = tmp_path / "experts.yaml"
        yaml_path.write_text(_MINIMAL_V2_YAML, encoding="utf-8")
        reads = self._spy_read_text(monkeypatch)
        ep.reload_experts_config()
        try:
            teams1 = ep.load_experts_config_v2(yaml_path)
            assert teams1[0].id == "test-team"
            yaml_path.write_text(
                _MINIMAL_V2_YAML.replace("test-team\n", "test-team-v2\n"),
                encoding="utf-8",
            )
            _bump_mtime(yaml_path)
            teams2 = ep.load_experts_config_v2(yaml_path)
        finally:
            ep.reload_experts_config()
        assert teams2[0].id == "test-team-v2"
        assert reads.count(str(yaml_path)) == 2

    def test_c_prompt_file_independent_invalidation(self, tmp_path, monkeypatch):
        from backend import expert_panel as ep

        prompt_path = tmp_path / "member.md"
        prompt_path.write_text("v1 角色设定", encoding="utf-8")
        ep.reload_experts_config()
        try:
            assert ep.load_prompt_file(str(prompt_path)) == "v1 角色设定"
            prompt_path.write_text("v2 角色设定(已更新)", encoding="utf-8")
            _bump_mtime(prompt_path)
            assert ep.load_prompt_file(str(prompt_path)) == "v2 角色设定(已更新)"
        finally:
            ep.reload_experts_config()

    def test_d_reload_experts_config_forces_reread(self, tmp_path, monkeypatch):
        from backend import expert_panel as ep

        yaml_path = tmp_path / "experts.yaml"
        yaml_path.write_text(_MINIMAL_V2_YAML, encoding="utf-8")
        reads = self._spy_read_text(monkeypatch)
        ep.reload_experts_config()
        try:
            ep.load_experts_config_v2(yaml_path)
            ep.reload_experts_config()
            ep.load_experts_config_v2(yaml_path)
        finally:
            ep.reload_experts_config()
        assert reads.count(str(yaml_path)) == 2
