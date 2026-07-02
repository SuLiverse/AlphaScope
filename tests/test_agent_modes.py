"""Tests for Agent Mode System (v0.12)"""

import threading

# Ensure project root is on sys.path
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.agent_modes import (
    AnalysisMode,
    AgentModeEntry,
    AgentModeConfig,
    ModeResolver,
    get_mode_resolver,
    resolve_mode,
    get_mode_choices,
)


class TestAnalysisMode:
    """Test AnalysisMode enum"""

    def test_enum_values(self):
        assert AnalysisMode.STANDARD.value == "standard"
        assert AnalysisMode.DEEP.value == "deep"
        assert AnalysisMode.AUTO.value == "auto"

    def test_enum_members(self):
        assert len(AnalysisMode) == 3
        assert set(m.value for m in AnalysisMode) == {"standard", "deep", "auto"}

    def test_string_enum(self):
        # AnalysisMode inherits from str, so it can be compared to strings
        assert AnalysisMode.STANDARD == "standard"
        assert AnalysisMode.DEEP == "deep"
        assert AnalysisMode.AUTO == "auto"


class TestAgentModeEntry:
    """Test AgentModeEntry dataclass"""

    def test_defaults(self):
        entry = AgentModeEntry(key="test")
        assert entry.key == "test"
        assert entry.provider == "deepseek"
        assert entry.model == "deepseek-chat"
        assert entry.enabled is True

    def test_custom_values(self):
        entry = AgentModeEntry(
            key="fundamental",
            provider="claude",
            model="claude-sonnet-4-5",
            enabled=True,
        )
        assert entry.key == "fundamental"
        assert entry.provider == "claude"
        assert entry.model == "claude-sonnet-4-5"

    def test_disabled(self):
        entry = AgentModeEntry(key="retail", enabled=False)
        assert entry.enabled is False


class TestAgentModeConfig:
    """Test AgentModeConfig dataclass"""

    def _make_config(self, mode=AnalysisMode.DEEP, agents=None):
        if agents is None:
            agents = [
                AgentModeEntry(
                    key="fundamental", provider="claude", model="claude-sonnet-4-5"
                ),
                AgentModeEntry(key="technical", provider="gpt", model="gpt-5.2"),
                AgentModeEntry(
                    key="sentiment", provider="deepseek", model="deepseek-chat"
                ),
            ]
        return AgentModeConfig(
            mode=mode,
            name="Test Mode",
            description="Test description",
            agents=agents,
        )

    def test_defaults(self):
        config = AgentModeConfig(mode=AnalysisMode.STANDARD)
        assert config.mode == AnalysisMode.STANDARD
        assert config.enable_evidence is False
        assert config.enable_factors is False
        assert config.enable_critic is False
        assert config.enable_chairman is False
        assert config.max_tokens == 1536
        assert config.temperature == 0.3

    def test_enabled_agents(self):
        agents = [
            AgentModeEntry(key="a1", enabled=True),
            AgentModeEntry(key="a2", enabled=False),
            AgentModeEntry(key="a3", enabled=True),
        ]
        config = self._make_config(agents=agents)
        assert len(config.enabled_agents) == 2
        assert [a.key for a in config.enabled_agents] == ["a1", "a3"]

    def test_agent_keys(self):
        config = self._make_config()
        assert config.agent_keys == ["fundamental", "technical", "sentiment"]

    def test_get_agent_config(self):
        config = self._make_config()
        entry = config.get_agent_config("technical")
        assert entry is not None
        assert entry.provider == "gpt"
        assert entry.model == "gpt-5.2"

    def test_get_agent_config_missing(self):
        config = self._make_config()
        assert config.get_agent_config("nonexistent") is None

    def test_to_dict(self):
        config = self._make_config()
        d = config.to_dict()
        assert d["mode"] == "deep"
        assert d["name"] == "Test Mode"
        assert len(d["agents"]) == 3
        assert d["agents"][0]["key"] == "fundamental"
        assert "enable_evidence" in d
        assert "max_tokens" in d


class TestModeResolver:
    """Test ModeResolver singleton and config loading"""

    def _reset_singleton(self):
        """Reset ModeResolver singleton for isolated tests"""
        ModeResolver._instance = None

    def teardown_method(self):
        self._reset_singleton()

    def test_singleton(self):
        r1 = ModeResolver()
        r2 = ModeResolver()
        assert r1 is r2

    def test_singleton_thread_safety(self):
        instances = []
        barrier = threading.Barrier(5)

        def create_resolver():
            barrier.wait(timeout=5)
            instances.append(ModeResolver())

        threads = [threading.Thread(target=create_resolver) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert all(inst is instances[0] for inst in instances)

    def test_resolve_standard(self):
        resolver = ModeResolver()
        config = resolver.resolve(AnalysisMode.STANDARD)
        assert config.mode == AnalysisMode.STANDARD
        assert len(config.agents) == 3
        assert config.enable_critic is False
        assert config.enable_chairman is False

    def test_resolve_deep(self):
        resolver = ModeResolver()
        config = resolver.resolve(AnalysisMode.DEEP)
        assert config.mode == AnalysisMode.DEEP
        assert len(config.agents) == 5
        assert config.enable_critic is True
        assert config.enable_chairman is True
        assert config.enable_evidence is True
        assert config.enable_factors is True

    def test_resolve_auto(self):
        resolver = ModeResolver()
        config = resolver.resolve(AnalysisMode.AUTO)
        assert config.mode == AnalysisMode.AUTO
        assert config.escalate_below == 30
        assert config.escalate_above == 70

    def test_resolve_caching(self):
        resolver = ModeResolver()
        c1 = resolver.resolve(AnalysisMode.DEEP)
        c2 = resolver.resolve(AnalysisMode.DEEP)
        assert c1 is c2

    def test_reload(self):
        resolver = ModeResolver()
        c1 = resolver.resolve(AnalysisMode.STANDARD)
        resolver.reload()
        c2 = resolver.resolve(AnalysisMode.STANDARD)
        assert c1 is not c2  # New instance after reload

    def test_list_modes(self):
        resolver = ModeResolver()
        modes = resolver.list_modes()
        assert len(modes) == 3
        values = [m["value"] for m in modes]
        assert "standard" in values
        assert "deep" in values
        assert "auto" in values
        for m in modes:
            assert "name" in m
            assert "description" in m

    def test_get_mode_names(self):
        resolver = ModeResolver()
        names = resolver.get_mode_names()
        assert "standard" in names
        assert "deep" in names
        assert "auto" in names
        assert names["standard"] == "标准模式"
        assert names["deep"] == "深入模式"

    def test_missing_config_file(self, tmp_path):
        """Should gracefully handle missing config file"""
        resolver = ModeResolver(config_path=str(tmp_path / "nonexistent.yaml"))
        # Should still work with defaults
        config = resolver.resolve(AnalysisMode.STANDARD)
        assert config.mode == AnalysisMode.STANDARD

    def test_invalid_config_file(self, tmp_path):
        """Should gracefully handle invalid YAML"""
        cfg = tmp_path / "bad.yaml"
        cfg.write_text("invalid: [yaml: {broken", encoding="utf-8")
        resolver = ModeResolver(config_path=str(cfg))
        config = resolver.resolve(AnalysisMode.STANDARD)
        assert config.mode == AnalysisMode.STANDARD


class TestModeResolverWithCustomConfig:
    """Test ModeResolver with custom YAML config"""

    def _reset_singleton(self):
        ModeResolver._instance = None

    def teardown_method(self):
        self._reset_singleton()

    def test_custom_agents(self, tmp_path):
        cfg = tmp_path / "models.yaml"
        cfg.write_text(
            """
version: "1.0"
modes:
  standard:
    name: "自定义标准"
    description: "Custom standard mode"
    agents:
      - key: fundamental
        provider: deepseek
        model: deepseek-chat
      - key: technical
        provider: deepseek
        model: deepseek-chat
    enable_critic: false
    max_tokens: 300
fallback:
  provider: deepseek
  model: deepseek-chat
""",
            encoding="utf-8",
        )
        resolver = ModeResolver(config_path=str(cfg))
        config = resolver.resolve(AnalysisMode.STANDARD)
        assert config.name == "自定义标准"
        assert len(config.agents) == 2
        assert config.max_tokens == 300


class TestConvenienceFunctions:
    """Test module-level convenience functions"""

    def _reset_singleton(self):
        ModeResolver._instance = None
        # Also reset module-level singleton
        import backend.agent_modes as mod

        mod._resolver_instance = None

    def teardown_method(self):
        self._reset_singleton()

    def test_get_mode_resolver(self):
        r = get_mode_resolver()
        assert isinstance(r, ModeResolver)

    def test_resolve_mode(self):
        config = resolve_mode(AnalysisMode.DEEP)
        assert isinstance(config, AgentModeConfig)
        assert config.mode == AnalysisMode.DEEP

    def test_get_mode_choices(self):
        choices = get_mode_choices()
        assert len(choices) == 3
        assert all("value" in c and "name" in c for c in choices)
