"""
Agent Analysis Mode System (v0.12)

Three-tier mode system for balancing cost vs quality:
- STANDARD: 3 agents, cheap models, no evidence/factors/critic
- DEEP: 5 agents + critic + chairman, expensive models, full features
- AUTO: Quick pre-screen, escalate to DEEP if confidence ambiguous (30-70)

Usage:
    from backend.agent_modes import get_mode_resolver, AnalysisMode
    resolver = get_mode_resolver()
    config = resolver.resolve(AnalysisMode.DEEP)
"""

import logging
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

import yaml

try:
    from backend.project_paths import CONFIG_DIR
except ImportError:
    from project_paths import CONFIG_DIR

logger = logging.getLogger(__name__)


class AnalysisMode(str, Enum):
    """Analysis mode enumeration"""

    STANDARD = "standard"
    DEEP = "deep"
    AUTO = "auto"


@dataclass
class AgentModeEntry:
    """Single agent configuration within a mode"""

    key: str
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    enabled: bool = True


@dataclass
class AgentModeConfig:
    """Resolved configuration for a specific analysis mode"""

    mode: AnalysisMode
    name: str = ""
    description: str = ""
    agents: List[AgentModeEntry] = field(default_factory=list)
    enable_evidence: bool = False
    enable_factors: bool = False
    enable_critic: bool = False
    enable_chairman: bool = False
    critic_provider: str = "claude"
    critic_model: str = "claude-opus-4-7"
    chairman_provider: str = "claude"
    chairman_model: str = "claude-opus-4-7"
    max_tokens: int = 1536
    temperature: float = 0.3
    threshold_mode: str = "majority"
    # Auto mode specific
    pre_screen_provider: str = "deepseek"
    pre_screen_model: str = "deepseek-chat"
    pre_screen_max_tokens: int = 1024
    pre_screen_temperature: float = 0.3
    escalate_below: int = 30
    escalate_above: int = 70
    escalate_mode: str = "deep"
    # Fallback
    fallback_provider: str = "deepseek"
    fallback_model: str = "deepseek-chat"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for JSON/YAML output"""
        return {
            "mode": self.mode.value,
            "name": self.name,
            "description": self.description,
            "agents": [
                {
                    "key": a.key,
                    "provider": a.provider,
                    "model": a.model,
                    "enabled": a.enabled,
                }
                for a in self.agents
            ],
            "enable_evidence": self.enable_evidence,
            "enable_factors": self.enable_factors,
            "enable_critic": self.enable_critic,
            "enable_chairman": self.enable_chairman,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "threshold_mode": self.threshold_mode,
        }

    @property
    def enabled_agents(self) -> List[AgentModeEntry]:
        """Return only enabled agents"""
        return [a for a in self.agents if a.enabled]

    @property
    def agent_keys(self) -> List[str]:
        """Return list of enabled agent keys"""
        return [a.key for a in self.agents if a.enabled]

    def get_agent_config(self, key: str) -> Optional[AgentModeEntry]:
        """Get config for a specific agent by key"""
        for a in self.agents:
            if a.key == key:
                return a
        return None


class ModeResolver:
    """
    Singleton that loads mode configuration from config/models.yaml
    and resolves AnalysisMode to AgentModeConfig.

    Thread-safe: uses double-checked locking.
    """

    _instance: Optional["ModeResolver"] = None
    _lock = threading.Lock()

    def __new__(cls, config_path: Optional[str] = None) -> "ModeResolver":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(self, config_path: Optional[str] = None) -> None:
        if self._initialized:
            return
        self._config_path = (
            Path(config_path) if config_path else CONFIG_DIR / "models.yaml"
        )
        self._raw_config: Dict[str, Any] = {}
        self._mode_cache: Dict[AnalysisMode, AgentModeConfig] = {}
        self._load_config()
        self._initialized = True

    def _load_config(self) -> None:
        """Load configuration from YAML file"""
        if not self._config_path.exists():
            logger.info(
                "[ModeResolver] Config not found: %s, using defaults", self._config_path
            )
            return
        try:
            self._raw_config = (
                yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
            )
            logger.info("[ModeResolver] Loaded config from %s", self._config_path)
        except Exception as e:
            logger.warning("[ModeResolver] Failed to load config: %s", e)

    def reload(self) -> None:
        """Reload configuration (e.g., after config file update)"""
        self._raw_config = {}
        self._mode_cache.clear()
        self._load_config()

    def resolve(self, mode: AnalysisMode) -> AgentModeConfig:
        """
        Resolve an AnalysisMode to a fully populated AgentModeConfig.

        Returns cached config if already resolved.
        """
        if mode in self._mode_cache:
            return self._mode_cache[mode]

        config = self._build_config(mode)
        self._mode_cache[mode] = config
        return config

    def _build_config(self, mode: AnalysisMode) -> AgentModeConfig:
        """Build AgentModeConfig from raw YAML config"""
        modes_section = self._raw_config.get("modes", {})
        fallback = self._raw_config.get("fallback", {})

        if mode == AnalysisMode.STANDARD:
            return self._build_standard(modes_section.get("standard", {}), fallback)
        elif mode == AnalysisMode.DEEP:
            return self._build_deep(modes_section.get("deep", {}), fallback)
        elif mode == AnalysisMode.AUTO:
            return self._build_auto(modes_section.get("auto", {}), fallback)
        else:
            raise ValueError(f"Unknown mode: {mode}")

    def _build_standard(self, raw: Dict, fallback: Dict) -> AgentModeConfig:
        """Build standard mode config"""
        agents = self._parse_agents(raw.get("agents", []))
        return AgentModeConfig(
            mode=AnalysisMode.STANDARD,
            name=raw.get("name", "标准模式"),
            description=raw.get("description", "快速分析，3个核心Agent，低成本模型"),
            agents=agents,
            enable_evidence=raw.get("enable_evidence", False),
            enable_factors=raw.get("enable_factors", False),
            enable_critic=raw.get("enable_critic", False),
            enable_chairman=raw.get("enable_chairman", False),
            max_tokens=raw.get("max_tokens", 1536),
            temperature=raw.get("temperature", 0.3),
            threshold_mode=raw.get("threshold_mode", "majority"),
            fallback_provider=fallback.get("provider", "deepseek"),
            fallback_model=fallback.get("model", "deepseek-chat"),
        )

    def _build_deep(self, raw: Dict, fallback: Dict) -> AgentModeConfig:
        """Build deep mode config"""
        agents = self._parse_agents(raw.get("agents", []))
        critic = raw.get("critic", {})
        chairman = raw.get("chairman", {})
        return AgentModeConfig(
            mode=AnalysisMode.DEEP,
            name=raw.get("name", "深入模式"),
            description=raw.get(
                "description", "全面分析，5个Agent+主席+Critic，高性能模型"
            ),
            agents=agents,
            enable_evidence=raw.get("enable_evidence", True),
            enable_factors=raw.get("enable_factors", True),
            enable_critic=raw.get("enable_critic", True),
            enable_chairman=raw.get("enable_chairman", True),
            critic_provider=critic.get("provider", "claude"),
            critic_model=critic.get("model", "claude-opus-4-7"),
            chairman_provider=chairman.get("provider", "claude"),
            chairman_model=chairman.get("model", "claude-opus-4-7"),
            max_tokens=raw.get("max_tokens", 2048),
            temperature=raw.get("temperature", 0.3),
            threshold_mode=raw.get("threshold_mode", "strict"),
            fallback_provider=fallback.get("provider", "deepseek"),
            fallback_model=fallback.get("model", "deepseek-chat"),
        )

    def _build_auto(self, raw: Dict, fallback: Dict) -> AgentModeConfig:
        """Build auto mode config (pre-screen + conditional deep escalation)"""
        pre_screen = raw.get("pre_screen", {})
        deep_raw = raw.get("deep", {})
        deep_agents = self._parse_agents(deep_raw.get("agents", []))
        deep_critic = deep_raw.get("critic", {})
        deep_chairman = deep_raw.get("chairman", {})

        return AgentModeConfig(
            mode=AnalysisMode.AUTO,
            name=raw.get("name", "自动模式"),
            description=raw.get("description", "先预筛，信号不明确时自动升级"),
            agents=deep_agents,  # Full agent list for escalation
            enable_evidence=deep_raw.get("enable_evidence", True),
            enable_factors=deep_raw.get("enable_factors", True),
            enable_critic=deep_raw.get("enable_critic", True),
            enable_chairman=deep_raw.get("enable_chairman", True),
            critic_provider=deep_critic.get("provider", "claude"),
            critic_model=deep_critic.get("model", "claude-opus-4-7"),
            chairman_provider=deep_chairman.get("provider", "claude"),
            chairman_model=deep_chairman.get("model", "claude-opus-4-7"),
            max_tokens=deep_raw.get("max_tokens", 2048),
            temperature=deep_raw.get("temperature", 0.3),
            threshold_mode=deep_raw.get("threshold_mode", "strict"),
            # Auto-specific
            pre_screen_provider=pre_screen.get("provider", "deepseek"),
            pre_screen_model=pre_screen.get("model", "deepseek-chat"),
            pre_screen_max_tokens=pre_screen.get("max_tokens", 1024),
            pre_screen_temperature=pre_screen.get("temperature", 0.3),
            escalate_below=raw.get("escalate_below", 30),
            escalate_above=raw.get("escalate_above", 70),
            escalate_mode=raw.get("escalate_mode", "deep"),
            fallback_provider=fallback.get("provider", "deepseek"),
            fallback_model=fallback.get("model", "deepseek-chat"),
        )

    def _parse_agents(self, agents_raw: List[Dict]) -> List[AgentModeEntry]:
        """Parse agent list from YAML config"""
        return [
            AgentModeEntry(
                key=a.get("key", "unknown"),
                provider=a.get("provider", "deepseek"),
                model=a.get("model", "deepseek-chat"),
                enabled=a.get("enabled", True),
            )
            for a in agents_raw
            if a.get("key")
        ]

    def get_mode_names(self) -> Dict[str, str]:
        """Return {mode_value: display_name} for all available modes"""
        return {
            AnalysisMode.STANDARD.value: self.resolve(AnalysisMode.STANDARD).name,
            AnalysisMode.DEEP.value: self.resolve(AnalysisMode.DEEP).name,
            AnalysisMode.AUTO.value: self.resolve(AnalysisMode.AUTO).name,
        }

    def list_modes(self) -> List[Dict[str, str]]:
        """Return list of modes with value, name, description for UI"""
        result = []
        for mode in AnalysisMode:
            config = self.resolve(mode)
            result.append(
                {
                    "value": mode.value,
                    "name": config.name,
                    "description": config.description,
                }
            )
        return result


# ============== Module-level singleton ==============
_resolver_instance: Optional[ModeResolver] = None
_resolver_lock = threading.Lock()


def get_mode_resolver(config_path: Optional[str] = None) -> ModeResolver:
    """Get or create the global ModeResolver singleton"""
    global _resolver_instance
    if _resolver_instance is None:
        with _resolver_lock:
            if _resolver_instance is None:
                _resolver_instance = ModeResolver(config_path)
    return _resolver_instance


def resolve_mode(mode: AnalysisMode) -> AgentModeConfig:
    """Convenience function: resolve a mode using the global resolver"""
    return get_mode_resolver().resolve(mode)


def get_mode_choices() -> List[Dict[str, str]]:
    """Convenience function: get all mode choices for UI"""
    return get_mode_resolver().list_modes()


if __name__ == "__main__":
    # Quick test
    resolver = get_mode_resolver()
    print("Available modes:")
    for mode_info in resolver.list_modes():
        print(
            f"  {mode_info['value']}: {mode_info['name']} - {mode_info['description']}"
        )

    for mode in AnalysisMode:
        config = resolver.resolve(mode)
        print(f"\n{config.name} ({config.mode.value}):")
        print(f"  Agents: {config.agent_keys}")
        print(f"  Evidence: {config.enable_evidence}, Factors: {config.enable_factors}")
        print(f"  Critic: {config.enable_critic}, Chairman: {config.enable_chairman}")
        print(f"  Max tokens: {config.max_tokens}, Temperature: {config.temperature}")
