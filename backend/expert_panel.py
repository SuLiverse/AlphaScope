"""
专家圆桌服务层（v2.0 重构）

参考 workbuddy 专家团 manifest 格式，支持：
- 团队-成员层级（expertType: "team"）
- 角色区分（lead/member）
- promptFile 指向独立 Markdown 角色设定
- 多语言名称（zh/en）
- 细粒度 API Key（每个成员可单独配置）

依赖:
- config/experts.yaml (v2.0 teams 配置 + v1.0 兼容)
- config/providers.yaml (Provider 化架构)
- llm_agents.call_llm / VENDORS / FALLBACK_VENDOR_MODEL
- llm_agents._extract_json
"""

import enum
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_agents as _llm_agents  # noqa: E402

try:
    from backend.project_paths import CONFIG_DIR, PROJECT_ROOT  # noqa: E402
except ImportError:
    from project_paths import CONFIG_DIR, PROJECT_ROOT  # noqa: E402

# Streamlit 热重载时 sys.modules 里可能残留旧版 llm_agents(无 call_llm 别名)。
# 这里做运行时兜底,避免专家团组件因导入别名失败而不加载。
call_llm = getattr(_llm_agents, "call_llm", _llm_agents._call_with)
VENDORS = _llm_agents.VENDORS
FALLBACK_VENDOR_MODEL = _llm_agents.FALLBACK_VENDOR_MODEL
_extract_json = _llm_agents._extract_json

# v0.8: 统一 schema 校验,失败时退回恒等函数保持向后兼容
try:
    from backend.validators import validate_expert_output as _validate_expert_output  # type: ignore
except Exception:  # pragma: no cover

    def _validate_expert_output(data):  # type: ignore[no-redef]
        return data if isinstance(data, dict) else {}


# ============== 配置路径 ==============
EXPERTS_YAML_PATH = CONFIG_DIR / "experts.yaml"


# ============== v2.0 Dataclass ==============
@dataclass
class ExpertMemberConfig:
    """团队成员配置（workbuddy 风格）"""

    id: str = ""
    display_name: str = ""  # zh 名称
    display_name_en: str = ""  # en 名称
    profession: str = ""  # zh 职业
    profession_en: str = ""  # en 职业
    avatar: str = ""
    prompt_file: str = ""  # Markdown 角色设定文件路径
    role: str = "member"  # "lead" | "member"
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""  # 细粒度 API Key（可选）
    base_url: str = ""  # 细粒度 Base URL（可选）
    inherit_global_key: bool = True  # 是否继承统一 AI 设置
    enabled: bool = True  # 页面自定义：是否启用
    card_style: str = "default"  # 页面自定义：卡片样式
    focus_dims: List[str] = field(default_factory=list)
    stop_loss_style: str = "中等"
    system_prompt: str = ""  # 从 prompt_file 加载或内联


@dataclass
class ExpertTeamConfig:
    """团队配置（workbuddy 风格）"""

    id: str = ""
    display_name: str = ""
    display_name_en: str = ""
    description: str = ""
    avatar: str = ""
    prompt_file: str = ""
    output_schema: str = ""
    members: List[ExpertMemberConfig] = field(default_factory=list)


# ============== v1.0 兼容 Dataclass ==============
@dataclass
class ExpertConfig:
    key: str = ""
    name: str = ""
    style: str = ""
    icon: str = ""
    preferred_vendor: str = "deepseek"
    preferred_model: str = "deepseek-chat"
    system_prompt: str = ""
    focus_dims: List[str] = field(default_factory=list)
    stop_loss_style: str = "中等"


@dataclass
class ExpertOpinion:
    expert_key: str = ""
    expert_name: str = ""
    style: str = ""
    icon: str = ""
    view: str = ""
    # v0.8: evidence 升级为 [{type, claim, data_date}, ...];旧归档可能仍是 List[str],渲染层做兼容。
    evidence: List = field(default_factory=list)
    action: str = "观望"
    position: int = 0
    stop_loss: float = 0.0
    invalid_if: str = ""  # v0.8: 失效条件
    risks: List[str] = field(default_factory=list)  # v0.8: 主要风险
    vendor: str = ""
    model: str = ""
    fallback_used: bool = False
    ok: bool = True
    error_msg: str = ""
    role: str = "member"  # v2.0 新增:角色标识
    card_style: str = "default"  # v2.0 新增:前端卡片样式


# ============== 团队运行模式 ==============
class TeamRunMode(enum.Enum):
    """专家团运行模式（对应架构 5 种模式）"""

    QUICK_VOTE = "quick_vote"  # 1. 快速投票：并行调用，无辩论（默认/现有行为）
    ROUNDTABLE = "roundtable"  # 2. 圆桌讨论：专家互相阅读观点后修订
    DEVILS_ADVOCATE = "devils_advocate"  # 3. 魔鬼辩护：指定一位专家专门找漏洞
    CHAIRMAN_RULING = "chairman_ruling"  # 4. 主席裁决：主席综合所有观点做最终判断
    HUMAN_INTERVENTION = "human_intervention"  # 5. 人工介入：用户可指定特定专家回答


# ============== Prompt 文件加载 ==============
def load_prompt_file(prompt_path: str) -> str:
    """加载 Markdown 角色设定文件"""
    if not prompt_path:
        return ""
    p = PROJECT_ROOT / prompt_path
    if not p.exists():
        # 尝试直接路径
        p = Path(prompt_path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


# ============== v2.0 配置加载 ==============
def load_experts_config_v2(yaml_path: Optional[Path] = None) -> List[ExpertTeamConfig]:
    """
    读取 experts.yaml v2.0 格式，返回 ExpertTeamConfig 列表。
    如果找不到 teams 配置，返回空列表（调用方应回退到 v1）。
    """
    p = yaml_path or EXPERTS_YAML_PATH
    if not p.exists():
        raise FileNotFoundError(f"experts.yaml 不存在: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))

    teams = []
    for team_raw in raw.get("teams", []):
        members = []
        for m_raw in team_raw.get("members", []):
            # 读取 promptFile
            prompt_file = m_raw.get("promptFile", "")
            system_prompt = load_prompt_file(prompt_file)

            # 多语言名称
            display_name = m_raw.get("displayName", {})
            profession = m_raw.get("profession", {})

            members.append(
                ExpertMemberConfig(
                    id=m_raw.get("id", ""),
                    display_name=display_name.get("zh", "")
                    if isinstance(display_name, dict)
                    else str(display_name),
                    display_name_en=display_name.get("en", "")
                    if isinstance(display_name, dict)
                    else "",
                    profession=profession.get("zh", "")
                    if isinstance(profession, dict)
                    else str(profession),
                    profession_en=profession.get("en", "")
                    if isinstance(profession, dict)
                    else "",
                    avatar=m_raw.get("avatar", ""),
                    prompt_file=prompt_file,
                    role=m_raw.get("role", "member"),
                    provider=m_raw.get("provider", "deepseek"),
                    model=m_raw.get("model", "deepseek-chat"),
                    api_key=m_raw.get("apiKey", ""),
                    base_url=m_raw.get("baseUrl", ""),
                    inherit_global_key=bool(m_raw.get("inheritGlobalKey", True)),
                    enabled=bool(m_raw.get("enabled", True)),
                    card_style=m_raw.get("cardStyle", "default"),
                    focus_dims=list(m_raw.get("focusDims", []) or []),
                    stop_loss_style=m_raw.get("stopLossStyle", "中等"),
                    system_prompt=system_prompt,
                )
            )

        team_display_name = team_raw.get("displayName", {})
        teams.append(
            ExpertTeamConfig(
                id=team_raw.get("id", ""),
                display_name=team_display_name.get("zh", "")
                if isinstance(team_display_name, dict)
                else str(team_display_name),
                display_name_en=team_display_name.get("en", "")
                if isinstance(team_display_name, dict)
                else "",
                description=team_raw.get("description", ""),
                avatar=team_raw.get("avatar", ""),
                prompt_file=team_raw.get("promptFile", ""),
                output_schema=team_raw.get("outputSchema", ""),
                members=members,
            )
        )

    return teams


# ============== v1.0 兼容配置加载 ==============
def load_experts_config(yaml_path: Optional[Path] = None) -> List[ExpertConfig]:
    """读取 experts.yaml v1.0 格式，返回 ExpertConfig 列表"""
    p = yaml_path or EXPERTS_YAML_PATH
    if not p.exists():
        raise FileNotFoundError(f"experts.yaml 不存在: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = []
    for item in raw.get("experts", []):
        out.append(
            ExpertConfig(
                key=item.get("key", ""),
                name=item.get("name", ""),
                style=item.get("style", ""),
                icon=item.get("icon", ""),
                preferred_vendor=item.get("preferred_vendor", "deepseek"),
                preferred_model=item.get("preferred_model", "deepseek-chat"),
                system_prompt=(item.get("system_prompt") or "").strip(),
                focus_dims=list(item.get("focus_dims", []) or []),
                stop_loss_style=item.get("stop_loss_style", "中等"),
            )
        )
    # 缓存 output_schema 全局
    global _OUTPUT_SCHEMA
    _OUTPUT_SCHEMA = (raw.get("output_schema") or "").strip()
    return out


_OUTPUT_SCHEMA = ""  # load_experts_config 时填充


# ============== 单专家调用 ==============
def _build_user_message(cfg, stock_brief: str, stock_name: str) -> str:
    """组装专家的 user message: 关注维度 + 市场简报 + 输出 schema"""
    schema_text = (
        _OUTPUT_SCHEMA
        or """必须严格按 JSON 返回:
{"view": "...", "evidence": ["...", "..."], "action": "买入|观望|减持|卖出", "position": 30, "stop_loss": 1500.0}"""
    )

    # v2.0 兼容
    focus_dims = getattr(cfg, "focus_dims", []) or getattr(cfg, "focusDims", [])
    style = getattr(cfg, "style", "") or getattr(cfg, "stop_loss_style", "中等")

    focus_line = "、".join(focus_dims) if focus_dims else "综合判断"
    stop_loss_style = getattr(cfg, "stop_loss_style", "中等")

    return f"""请基于以下 {stock_name} 的市场简报,从你的【{style}】视角出发分析。

【你的关注维度】{focus_line}
【你的止损风格】{stop_loss_style}

{stock_brief}

{schema_text}
"""


def _validate_opinion(data: dict, cfg) -> dict:
    """对 LLM 返回的 JSON 做合法性校验/兜底,统一委托给 validators.validate_expert_output。"""
    return _validate_expert_output(data)


def _resolve_expert_ai_config(cfg, global_ai_settings: Optional[dict] = None):
    global_ai_settings = global_ai_settings or {}
    preferred_vendor = getattr(cfg, "preferred_vendor", "") or getattr(
        cfg, "provider", "deepseek"
    )
    preferred_model = getattr(cfg, "preferred_model", "") or getattr(
        cfg, "model", "deepseek-chat"
    )
    api_key = getattr(cfg, "api_key", "") or ""
    base_url = getattr(cfg, "base_url", "") or ""
    if getattr(cfg, "inherit_global_key", True) and global_ai_settings.get(
        "use_unified_key", True
    ):
        preferred_vendor = global_ai_settings.get("provider") or preferred_vendor
        preferred_model = global_ai_settings.get("model") or preferred_model
        api_key = global_ai_settings.get("api_key", "") or api_key
        base_url = global_ai_settings.get("base_url", "") or base_url
    return preferred_vendor, preferred_model, api_key, base_url


def run_expert(
    cfg, stock_brief: str, stock_name: str, global_ai_settings: Optional[dict] = None
) -> ExpertOpinion:
    """
    单专家调用,含双层兜底。
    支持 v1.0 ExpertConfig 和 v2.0 ExpertMemberConfig。
    """
    user_msg = _build_user_message(cfg, stock_brief, stock_name)

    # 兼容 v1.0 和 v2.0 的属性访问
    system_prompt = getattr(cfg, "system_prompt", "") or load_prompt_file(
        getattr(cfg, "prompt_file", "")
    )
    preferred_vendor, preferred_model, api_key, base_url = _resolve_expert_ai_config(
        cfg, global_ai_settings
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    primary = (preferred_vendor, preferred_model)
    fallback = FALLBACK_VENDOR_MODEL
    last_err = ""

    for vd, md, bu, key_override in [
        (preferred_vendor, preferred_model, base_url, api_key or None),
        (fallback[0], fallback[1], "", None),
    ]:
        # 检查厂商配置是否完整；自定义 Base URL 时允许使用临时配置。
        cfg_v = VENDORS.get(vd) or {}
        if (
            not bu
            and (not cfg_v.get("api_key") or not cfg_v.get("base_url"))
            and not key_override
        ):
            last_err = f"{vd} 未配置完整"
            continue

        try:
            mtokens = 1500 if vd == "mimo" else 700
            # v2.0 支持细粒度 API Key
            text = call_llm(
                vendor=vd,
                model=md,
                messages=messages,
                json_mode=True,
                max_tokens=mtokens,
                temperature=0.4,
                api_key=key_override,
                base_url=bu or None,
            )
            data = _extract_json(text)
            if not data or not data.get("view"):
                # 同厂商再补一次
                text2 = call_llm(
                    vendor=vd,
                    model=md,
                    messages=messages
                    + [
                        {"role": "assistant", "content": text or ""},
                        {
                            "role": "user",
                            "content": "请只输出符合格式的 JSON 对象,不要任何前后说明。",
                        },
                    ],
                    json_mode=True,
                    max_tokens=mtokens,
                    temperature=0.2,
                    api_key=key_override,
                    base_url=bu or None,
                )
                data = _extract_json(text2)

            if not data or not data.get("view"):
                last_err = f"{vd} 未返回有效 JSON"
                continue

            valid = _validate_opinion(data, cfg)
            return ExpertOpinion(
                expert_key=getattr(cfg, "key", "") or getattr(cfg, "id", ""),
                expert_name=getattr(cfg, "name", "")
                or getattr(cfg, "display_name", ""),
                style=getattr(cfg, "style", "") or getattr(cfg, "profession", ""),
                icon=getattr(cfg, "icon", "") or getattr(cfg, "avatar", ""),
                view=valid["view"],
                evidence=valid["evidence"],
                action=valid["action"],
                position=valid["position"],
                stop_loss=valid["stop_loss"],
                invalid_if=valid.get("invalid_if", ""),
                risks=valid.get("risks", []),
                vendor=VENDORS[vd]["label"],
                model=md,
                fallback_used=(vd != primary[0]),
                ok=True,
                role=getattr(cfg, "role", "member"),
                card_style=getattr(cfg, "card_style", "default"),
            )
        except Exception as e:
            last_err = str(e)[:200]
            continue

    return ExpertOpinion(
        expert_key=getattr(cfg, "key", "") or getattr(cfg, "id", ""),
        expert_name=getattr(cfg, "name", "") or getattr(cfg, "display_name", ""),
        style=getattr(cfg, "style", "") or getattr(cfg, "profession", ""),
        icon=getattr(cfg, "icon", "") or getattr(cfg, "avatar", ""),
        view="(该专家暂不可用)",
        evidence=[],
        action="观望",
        position=0,
        stop_loss=0.0,
        vendor="?",
        model="?",
        fallback_used=True,
        ok=False,
        error_msg=last_err or "未知错误",
        role=getattr(cfg, "role", "member"),
    )


# ============== 团队并行调用 ==============
def load_default_team() -> ExpertTeamConfig:
    """读取默认专家团队；若 v2 配置不可用，则从 v1 experts 兼容生成。"""
    teams = load_experts_config_v2()
    if teams:
        return teams[0]
    experts = load_experts_config()
    return ExpertTeamConfig(
        id="default-team",
        display_name="默认专家团",
        avatar="🎓",
        members=[
            ExpertMemberConfig(
                id=e.key,
                display_name=e.name,
                profession=e.style,
                avatar=e.icon,
                role="member",
                provider=e.preferred_vendor,
                model=e.preferred_model,
                focus_dims=e.focus_dims,
                stop_loss_style=e.stop_loss_style,
                system_prompt=e.system_prompt,
            )
            for e in experts
        ],
    )


def team_to_editable_dict(team: ExpertTeamConfig) -> dict:
    """将 ExpertTeamConfig 转成 Streamlit session_state 友好的可编辑 dict。"""
    return {
        "id": team.id or "custom-team",
        "display_name": team.display_name or "自定义专家团",
        "avatar": team.avatar or "🎓",
        "description": team.description or "",
        "members": [
            {
                "id": m.id,
                "enabled": getattr(m, "enabled", True),
                "name": m.display_name,
                "profession": m.profession,
                "avatar": m.avatar or "🧠",
                "role": m.role or "member",
                "provider": m.provider or "deepseek",
                "model": m.model or "deepseek-chat",
                "base_url": getattr(m, "base_url", ""),
                "api_key": getattr(m, "api_key", ""),
                "inherit_global_key": getattr(m, "inherit_global_key", True),
                "focus_dims": ", ".join(m.focus_dims or []),
                "stop_loss_style": m.stop_loss_style or "中等",
                "system_prompt": m.system_prompt or load_prompt_file(m.prompt_file),
                "card_style": getattr(m, "card_style", "default"),
            }
            for m in team.members
        ],
    }


def editable_dict_to_team(data: dict) -> ExpertTeamConfig:
    """将页面编辑 dict 转回 ExpertTeamConfig，仅使用 enabled=True 的成员运行。"""
    members = []
    seen = set()
    for idx, raw in enumerate(data.get("members", []) or []):
        base_id = (raw.get("id") or f"expert_{idx + 1}").strip().replace(" ", "_")
        member_id = base_id
        suffix = 2
        while member_id in seen:
            member_id = f"{base_id}_{suffix}"
            suffix += 1
        seen.add(member_id)
        focus_raw = raw.get("focus_dims", "")
        if isinstance(focus_raw, str):
            focus_dims = [
                x.strip() for x in focus_raw.replace("，", ",").split(",") if x.strip()
            ]
        else:
            focus_dims = list(focus_raw or [])
        members.append(
            ExpertMemberConfig(
                id=member_id,
                display_name=raw.get("name", member_id),
                profession=raw.get("profession", "自定义专家"),
                avatar=raw.get("avatar", "🧠"),
                role=raw.get("role", "member"),
                provider=raw.get("provider", "deepseek"),
                model=raw.get("model", "deepseek-chat"),
                api_key=raw.get("api_key", ""),
                base_url=raw.get("base_url", ""),
                inherit_global_key=bool(raw.get("inherit_global_key", True)),
                enabled=bool(raw.get("enabled", True)),
                focus_dims=focus_dims,
                stop_loss_style=raw.get("stop_loss_style", "中等"),
                system_prompt=(raw.get("system_prompt") or "").strip(),
                card_style=raw.get("card_style", "default"),
            )
        )
    return ExpertTeamConfig(
        id=data.get("id", "custom-team"),
        display_name=data.get("display_name", "自定义专家团"),
        avatar=data.get("avatar", "🎓"),
        description=data.get("description", ""),
        members=members,
    )


# ============== 团队并行调用（v2 增强: 支持 5 种模式） ==============
def run_team_roundtable(
    team: ExpertTeamConfig,
    stock_brief: str,
    stock_name: str,
    global_ai_settings: Optional[dict] = None,
    run_mode: TeamRunMode = TeamRunMode.QUICK_VOTE,
    advocate_cfg: Optional[ExpertMemberConfig] = None,
) -> dict:
    """
    v2.0 团队调用统一入口，支持 5 种运行模式。

    参数:
        team:               专家团队配置
        stock_brief:        市场简报
        stock_name:         股票名称
        global_ai_settings: 全局 AI 配置（可选）
        run_mode:           运行模式，默认 QUICK_VOTE（兼容原有行为）
        advocate_cfg:       DEVILS_ADVOCATE / CHAIRMAN_RULING 模式下可指定
                            魔鬼辩护人/主席的专家配置（可选）

    返回: 根据 run_mode 不同，返回结构略有差异，但都包含 opinions/summary/elapsed 等基础字段。
    """
    if run_mode == TeamRunMode.ROUNDTABLE:
        return run_debate_round(team, stock_brief, stock_name, global_ai_settings)

    if run_mode == TeamRunMode.DEVILS_ADVOCATE:
        return run_devils_advocate(
            team, stock_brief, stock_name, global_ai_settings, advocate_cfg
        )

    if run_mode == TeamRunMode.CHAIRMAN_RULING:
        # 先做快速投票，再由主席裁决
        base_result = run_team_roundtable(
            team, stock_brief, stock_name, global_ai_settings, TeamRunMode.QUICK_VOTE
        )
        t0 = time.time()  # 重新计时（包含主席裁决）
        chairman_op = _run_chairman_ruling(
            team,
            base_result["opinions"],
            stock_brief,
            stock_name,
            global_ai_settings,
            advocate_cfg,  # 复用 advocate_cfg 作为 chairman_cfg
        )
        # 主席裁决结果追加到 opinions 中
        base_result["opinions"][chairman_op.expert_key] = chairman_op
        base_result["chairman_ruling"] = chairman_op
        base_result["run_mode"] = TeamRunMode.CHAIRMAN_RULING.value
        base_result["elapsed"] = round(base_result["elapsed"] + (time.time() - t0), 2)
        return base_result

    if run_mode == TeamRunMode.HUMAN_INTERVENTION:
        # 人工介入模式: 仅做快速投票，前端负责展示并允许用户追加提问
        result = run_team_roundtable(
            team, stock_brief, stock_name, global_ai_settings, TeamRunMode.QUICK_VOTE
        )
        result["run_mode"] = TeamRunMode.HUMAN_INTERVENTION.value
        result["awaiting_human_input"] = True
        return result

    # ---- 默认: QUICK_VOTE（完全兼容原有行为） ----
    t0 = time.time()
    if not team.members:
        return {
            "opinions": {},
            "summary": {},
            "elapsed": 0.0,
            "team_id": team.id,
            "team_name": team.display_name,
            "run_mode": TeamRunMode.QUICK_VOTE.value,
        }

    opinions: Dict[str, ExpertOpinion] = {}
    active_members = [m for m in team.members if getattr(m, "enabled", True)]
    if not active_members:
        return {
            "opinions": {},
            "summary": {},
            "elapsed": 0.0,
            "team_id": team.id,
            "team_name": team.display_name,
            "member_order": [],
            "run_mode": TeamRunMode.QUICK_VOTE.value,
        }

    with ThreadPoolExecutor(max_workers=len(active_members)) as ex:
        futs = {
            ex.submit(
                run_expert, member, stock_brief, stock_name, global_ai_settings
            ): member.id
            for member in active_members
        }
        for fut in as_completed(futs):
            try:
                op = fut.result(timeout=30)
            except Exception as e:
                ek = futs[fut]
                member_match = next((m for m in active_members if m.id == ek), None)
                op = ExpertOpinion(
                    expert_key=ek,
                    expert_name=member_match.display_name if member_match else ek,
                    style=member_match.profession if member_match else "",
                    icon=member_match.avatar if member_match else "",
                    view="(执行异常)",
                    action="观望",
                    ok=False,
                    error_msg=str(e)[:200],
                    role=member_match.role if member_match else "member",
                )
            opinions[op.expert_key] = op

    summary = summarize(opinions)
    return {
        "opinions": opinions,
        "summary": summary,
        "elapsed": round(time.time() - t0, 2),
        "team_id": team.id,
        "team_name": team.display_name,
        "member_order": [m.id for m in active_members],
        "run_mode": TeamRunMode.QUICK_VOTE.value,
    }


# ============== v1.0 兼容：5 路并行 ==============
def run_roundtable(
    stock_brief: str, stock_name: str, api_keys: Optional[Dict[str, str]] = None
) -> dict:
    """
    v1.0 兼容：5 专家并行调用。返回:
    {
        "opinions": {expert_key: ExpertOpinion, ...},
        "summary": {buy, hold, reduce, sell, avg_position, ...},
        "elapsed": float,
    }
    """
    t0 = time.time()
    experts = load_experts_config()
    if not experts:
        return {"opinions": {}, "summary": {}, "elapsed": 0.0}

    opinions: Dict[str, ExpertOpinion] = {}
    api_keys = api_keys or {}

    with ThreadPoolExecutor(max_workers=len(experts)) as ex:
        futs = {
            ex.submit(run_expert, cfg, stock_brief, stock_name): cfg.key
            for cfg in experts
        }
        for fut in as_completed(futs):
            try:
                op = fut.result(timeout=30)
            except Exception as e:
                ek = futs[fut]
                cfg_match = next((c for c in experts if c.key == ek), None)
                op = ExpertOpinion(
                    expert_key=ek,
                    expert_name=cfg_match.name if cfg_match else ek,
                    style=cfg_match.style if cfg_match else "",
                    icon=cfg_match.icon if cfg_match else "",
                    view="(执行异常)",
                    action="观望",
                    ok=False,
                    error_msg=str(e)[:200],
                )
            opinions[op.expert_key] = op

    summary = summarize(opinions)
    return {
        "opinions": opinions,
        "summary": summary,
        "elapsed": round(time.time() - t0, 2),
    }


# ============== 投票统计 ==============
def summarize(opinions: Dict[str, ExpertOpinion]) -> dict:
    """统计 buy/hold/reduce/sell + 平均仓位"""
    buy = hold = reduce_ = sell = 0
    total_pos = 0
    n_valid = 0
    for op in opinions.values():
        if not op.ok:
            continue
        n_valid += 1
        if op.action == "买入":
            buy += 1
        elif op.action == "观望":
            hold += 1
        elif op.action == "减持":
            reduce_ += 1
        elif op.action == "卖出":
            sell += 1
        total_pos += op.position

    avg_position = round(total_pos / n_valid, 1) if n_valid else 0.0
    return {
        "buy": buy,
        "hold": hold,
        "reduce": reduce_,
        "sell": sell,
        "avg_position": avg_position,
        "valid_count": n_valid,
        "total_count": len(opinions),
    }


# ============== 辩论辅助：构建意见摘要 ==============
def _build_opinions_summary(opinions: Dict[str, ExpertOpinion]) -> str:
    """将多位专家的意见打包为一段纯文本摘要，供辩论轮使用。"""
    lines = []
    for key, op in opinions.items():
        if not op.ok:
            continue
        lines.append(
            f"- {op.expert_name}({op.style}): "
            f'观点="{op.view}" | 操作={op.action} | 仓位={op.position}% | '
            f"止损=¥{op.stop_loss:.2f}"
        )
        if op.evidence:
            ev_texts = []
            for ev in op.evidence[:3]:
                if isinstance(ev, dict):
                    ev_texts.append(str(ev.get("claim", "")))
                else:
                    ev_texts.append(str(ev))
            if ev_texts:
                lines.append(f"  依据: {'; '.join(ev_texts)}")
        if op.risks:
            lines.append(f"  风险: {'; '.join(op.risks[:3])}")
    return "\n".join(lines) if lines else "(暂无有效意见)"


def _build_debate_user_message(
    cfg, stock_brief: str, stock_name: str, opinions_summary: str
) -> str:
    """为辩论轮构建 user message：附带其他专家意见摘要，要求该专家审阅后决定是否修订。"""
    focus_dims = getattr(cfg, "focus_dims", []) or []
    style = getattr(cfg, "style", "") or getattr(cfg, "stop_loss_style", "中等")
    focus_line = "、".join(focus_dims) if focus_dims else "综合判断"

    schema_text = (
        _OUTPUT_SCHEMA
        or """必须严格按 JSON 返回:
{"view": "...", "evidence": ["...", "..."], "action": "买入|观望|减持|卖出", "position": 30, "stop_loss": 1500.0}"""
    )

    return f"""以下是其他专家对 {stock_name} 的分析意见摘要：

{opinions_summary}

请认真阅读以上观点,结合你自己的【{style}】视角和关注维度【{focus_line}】,重新审视 {stock_name} 的投资价值。
- 如果你认为其他专家的观点有道理,可以修正自己的判断。
- 如果你坚持己见,请给出更有力的理由。
- 请特别关注是否存在与你判断相反的论据。

原始市场简报:
{stock_brief}

{schema_text}
"""


def _run_expert_debate_round(
    cfg,
    stock_brief: str,
    stock_name: str,
    opinions_summary: str,
    global_ai_settings: Optional[dict] = None,
) -> ExpertOpinion:
    """单专家辩论轮调用：在看到其他专家意见后重新给出判断。"""
    user_msg = _build_debate_user_message(
        cfg, stock_brief, stock_name, opinions_summary
    )
    system_prompt = getattr(cfg, "system_prompt", "") or load_prompt_file(
        getattr(cfg, "prompt_file", "")
    )
    preferred_vendor, preferred_model, api_key, base_url = _resolve_expert_ai_config(
        cfg, global_ai_settings
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    primary = (preferred_vendor, preferred_model)
    fallback = FALLBACK_VENDOR_MODEL
    last_err = ""

    for vd, md, bu, key_override in [
        (preferred_vendor, preferred_model, base_url, api_key or None),
        (fallback[0], fallback[1], "", None),
    ]:
        cfg_v = VENDORS.get(vd) or {}
        if (
            not bu
            and (not cfg_v.get("api_key") or not cfg_v.get("base_url"))
            and not key_override
        ):
            last_err = f"{vd} 未配置完整"
            continue

        try:
            mtokens = 1500 if vd == "mimo" else 700
            text = call_llm(
                vendor=vd,
                model=md,
                messages=messages,
                json_mode=True,
                max_tokens=mtokens,
                temperature=0.4,
                api_key=key_override,
                base_url=bu or None,
            )
            data = _extract_json(text)
            if not data or not data.get("view"):
                text2 = call_llm(
                    vendor=vd,
                    model=md,
                    messages=messages
                    + [
                        {"role": "assistant", "content": text or ""},
                        {
                            "role": "user",
                            "content": "请只输出符合格式的 JSON 对象,不要任何前后说明。",
                        },
                    ],
                    json_mode=True,
                    max_tokens=mtokens,
                    temperature=0.2,
                    api_key=key_override,
                    base_url=bu or None,
                )
                data = _extract_json(text2)

            if not data or not data.get("view"):
                last_err = f"{vd} 未返回有效 JSON"
                continue

            valid = _validate_opinion(data, cfg)
            return ExpertOpinion(
                expert_key=getattr(cfg, "key", "") or getattr(cfg, "id", ""),
                expert_name=getattr(cfg, "name", "")
                or getattr(cfg, "display_name", ""),
                style=getattr(cfg, "style", "") or getattr(cfg, "profession", ""),
                icon=getattr(cfg, "icon", "") or getattr(cfg, "avatar", ""),
                view=valid["view"],
                evidence=valid["evidence"],
                action=valid["action"],
                position=valid["position"],
                stop_loss=valid["stop_loss"],
                invalid_if=valid.get("invalid_if", ""),
                risks=valid.get("risks", []),
                vendor=VENDORS[vd]["label"],
                model=md,
                fallback_used=(vd != primary[0]),
                ok=True,
                role=getattr(cfg, "role", "member"),
                card_style=getattr(cfg, "card_style", "default"),
            )
        except Exception as e:
            last_err = str(e)[:200]
            continue

    return ExpertOpinion(
        expert_key=getattr(cfg, "key", "") or getattr(cfg, "id", ""),
        expert_name=getattr(cfg, "name", "") or getattr(cfg, "display_name", ""),
        style=getattr(cfg, "style", "") or getattr(cfg, "profession", ""),
        icon=getattr(cfg, "icon", "") or getattr(cfg, "avatar", ""),
        view="(该专家暂不可用)",
        evidence=[],
        action="观望",
        position=0,
        stop_loss=0.0,
        vendor="?",
        model="?",
        fallback_used=True,
        ok=False,
        error_msg=last_err or "未知错误",
        role=getattr(cfg, "role", "member"),
    )


# ============== 模式 2: 圆桌讨论（辩论） ==============
def run_debate_round(
    team: ExpertTeamConfig,
    stock_brief: str,
    stock_name: str,
    global_ai_settings: Optional[dict] = None,
) -> dict:
    """
    圆桌讨论模式:
      第一轮: 所有专家并行独立分析
      第二轮: 汇总第一轮意见,每位专家在看到他人观点后可修订自己的判断
    返回:
      {
        "round1_opinions": {key: ExpertOpinion, ...},   # 第一轮原始意见
        "round2_opinions": {key: ExpertOpinion, ...},   # 第二轮修订意见
        "opinions":        {key: ExpertOpinion, ...},   # 最终意见（= round2）
        "summary":         {...},
        "round1_summary":  {...},
        "elapsed":         float,
        "team_id":         str,
        "team_name":       str,
        "run_mode":        str,
      }
    """
    t0 = time.time()
    active_members = [m for m in team.members if getattr(m, "enabled", True)]
    if not active_members:
        return {
            "opinions": {},
            "round1_opinions": {},
            "round2_opinions": {},
            "summary": {},
            "round1_summary": {},
            "elapsed": 0.0,
            "team_id": team.id,
            "team_name": team.display_name,
            "member_order": [],
            "run_mode": TeamRunMode.ROUNDTABLE.value,
        }

    # ---- 第一轮: 并行独立分析 ----
    round1_opinions: Dict[str, ExpertOpinion] = {}
    with ThreadPoolExecutor(max_workers=len(active_members)) as ex:
        futs = {
            ex.submit(
                run_expert, member, stock_brief, stock_name, global_ai_settings
            ): member.id
            for member in active_members
        }
        for fut in as_completed(futs):
            try:
                op = fut.result(timeout=30)
            except Exception as e:
                ek = futs[fut]
                member_match = next((m for m in active_members if m.id == ek), None)
                op = ExpertOpinion(
                    expert_key=ek,
                    expert_name=member_match.display_name if member_match else ek,
                    style=member_match.profession if member_match else "",
                    icon=member_match.avatar if member_match else "",
                    view="(执行异常)",
                    action="观望",
                    ok=False,
                    error_msg=str(e)[:200],
                    role=member_match.role if member_match else "member",
                )
            round1_opinions[op.expert_key] = op

    round1_summary = summarize(round1_opinions)

    # ---- 构建意见摘要 ----
    opinions_summary = _build_opinions_summary(round1_opinions)

    # ---- 第二轮: 专家互相阅读后修订 ----
    round2_opinions: Dict[str, ExpertOpinion] = {}
    with ThreadPoolExecutor(max_workers=len(active_members)) as ex:
        futs = {
            ex.submit(
                _run_expert_debate_round,
                member,
                stock_brief,
                stock_name,
                opinions_summary,
                global_ai_settings,
            ): member.id
            for member in active_members
        }
        for fut in as_completed(futs):
            try:
                op = fut.result(timeout=30)
            except Exception as e:
                ek = futs[fut]
                member_match = next((m for m in active_members if m.id == ek), None)
                op = ExpertOpinion(
                    expert_key=ek,
                    expert_name=member_match.display_name if member_match else ek,
                    style=member_match.profession if member_match else "",
                    icon=member_match.avatar if member_match else "",
                    view="(辩论轮执行异常)",
                    action="观望",
                    ok=False,
                    error_msg=str(e)[:200],
                    role=member_match.role if member_match else "member",
                )
            round2_opinions[op.expert_key] = op

    summary = summarize(round2_opinions)

    return {
        "opinions": round2_opinions,
        "round1_opinions": round1_opinions,
        "round2_opinions": round2_opinions,
        "summary": summary,
        "round1_summary": round1_summary,
        "elapsed": round(time.time() - t0, 2),
        "team_id": team.id,
        "team_name": team.display_name,
        "member_order": [m.id for m in active_members],
        "run_mode": TeamRunMode.ROUNDTABLE.value,
    }


# ============== 模式 3: 魔鬼辩护 ==============
# 内置魔鬼辩护人角色设定
_DEVILS_ADVOCATE_SYSTEM_PROMPT = """你是一位专业的"魔鬼辩护人"(Devil's Advocate)。你的职责是：
1. 仔细审查其他分析师的观点和论据
2. 专门寻找他们分析中的漏洞、逻辑矛盾和被忽略的风险
3. 提出反对意见和反面论据
4. 你不需要给出自己的买卖建议，而是对现有分析进行批判性审查

请从以下角度审查：
- 论据是否可靠？数据来源是否可信？
- 逻辑推理是否有跳跃或矛盾？
- 是否忽略了重要的风险因素？
- 是否存在确认偏误（只看支持自己观点的证据）？
- 市场定价是否已经反映了这些预期？

请以 JSON 格式返回你的审查意见。"""


def run_devils_advocate(
    team: ExpertTeamConfig,
    stock_brief: str,
    stock_name: str,
    global_ai_settings: Optional[dict] = None,
    advocate_cfg: Optional[ExpertMemberConfig] = None,
) -> dict:
    """
    魔鬼辩护模式:
      第一轮: 所有专家并行独立分析
      第二轮: 指定一位魔鬼辩护人（使用 lead 成员或 advocate_cfg），对所有意见进行批判性审查
    返回:
      {
        "opinions":       {key: ExpertOpinion, ...},  # 原始意见
        "critique":       ExpertOpinion,              # 魔鬼辩护人的审查意见
        "summary":        {...},
        "elapsed":        float,
        "team_id":        str,
        "team_name":      str,
        "run_mode":       str,
      }
    """
    t0 = time.time()
    active_members = [m for m in team.members if getattr(m, "enabled", True)]
    if not active_members:
        return {
            "opinions": {},
            "critique": None,
            "summary": {},
            "elapsed": 0.0,
            "team_id": team.id,
            "team_name": team.display_name,
            "member_order": [],
            "run_mode": TeamRunMode.DEVILS_ADVOCATE.value,
        }

    # ---- 第一轮: 并行独立分析 ----
    opinions: Dict[str, ExpertOpinion] = {}
    with ThreadPoolExecutor(max_workers=len(active_members)) as ex:
        futs = {
            ex.submit(
                run_expert, member, stock_brief, stock_name, global_ai_settings
            ): member.id
            for member in active_members
        }
        for fut in as_completed(futs):
            try:
                op = fut.result(timeout=30)
            except Exception as e:
                ek = futs[fut]
                member_match = next((m for m in active_members if m.id == ek), None)
                op = ExpertOpinion(
                    expert_key=ek,
                    expert_name=member_match.display_name if member_match else ek,
                    style=member_match.profession if member_match else "",
                    icon=member_match.avatar if member_match else "",
                    view="(执行异常)",
                    action="观望",
                    ok=False,
                    error_msg=str(e)[:200],
                    role=member_match.role if member_match else "member",
                )
            opinions[op.expert_key] = op

    # ---- 构建意见摘要 ----
    opinions_summary = _build_opinions_summary(opinions)

    # ---- 第二轮: 魔鬼辩护人审查 ----
    # 确定魔鬼辩护人配置：优先使用 advocate_cfg，否则选 lead 成员，否则用第一个成员
    if advocate_cfg is None:
        lead_member = next((m for m in active_members if m.role == "lead"), None)
        advocate_cfg = lead_member or active_members[0]

    # 创建临时的魔鬼辩护人配置（覆盖 system_prompt）
    advocate_prompt = (
        _DEVILS_ADVOCATE_SYSTEM_PROMPT
        + f"\n\n你正在审查的专家团队对 {stock_name} 的分析意见如下：\n\n"
        + opinions_summary
    )

    adv_member = ExpertMemberConfig(
        id=f"devils_advocate_{advocate_cfg.id}",
        display_name=f"魔鬼辩护人({advocate_cfg.display_name})",
        display_name_en=f"Devil's Advocate ({advocate_cfg.display_name_en})",
        profession="批判性审查",
        profession_en="Critical Review",
        avatar="😈",
        prompt_file="",
        role="lead",
        provider=advocate_cfg.provider,
        model=advocate_cfg.model,
        api_key=advocate_cfg.api_key,
        base_url=advocate_cfg.base_url,
        inherit_global_key=advocate_cfg.inherit_global_key,
        enabled=True,
        system_prompt=advocate_prompt,
        focus_dims=[],
        stop_loss_style="严格",
    )

    # 魔鬼辩护人使用特殊的 user message
    critique_user_msg = f"""请对以上 {stock_name} 的专家分析意见进行批判性审查。

原始市场简报：
{stock_brief}

请以 JSON 格式返回审查意见：
{{"view": "你对整体分析的批判性审查意见", "evidence": ["发现的漏洞1", "发现的漏洞2"], "action": "买入|观望|减持|卖出", "position": 0, "stop_loss": 0.0, "risks": ["被忽略的风险1", "被忽略的风险2"]}}
注意：action/position/stop_loss 填写你认为在考虑了所有风险后更审慎的建议。"""

    try:
        system_prompt = adv_member.system_prompt
        preferred_vendor, preferred_model, api_key, base_url = (
            _resolve_expert_ai_config(adv_member, global_ai_settings)
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": critique_user_msg},
        ]

        primary = (preferred_vendor, preferred_model)
        fallback = FALLBACK_VENDOR_MODEL
        last_err = ""
        critique_op = None

        for vd, md, bu, key_override in [
            (preferred_vendor, preferred_model, base_url, api_key or None),
            (fallback[0], fallback[1], "", None),
        ]:
            cfg_v = VENDORS.get(vd) or {}
            if (
                not bu
                and (not cfg_v.get("api_key") or not cfg_v.get("base_url"))
                and not key_override
            ):
                last_err = f"{vd} 未配置完整"
                continue
            try:
                mtokens = 1500 if vd == "mimo" else 700
                text = call_llm(
                    vendor=vd,
                    model=md,
                    messages=messages,
                    json_mode=True,
                    max_tokens=mtokens,
                    temperature=0.5,
                    api_key=key_override,
                    base_url=bu or None,
                )
                data = _extract_json(text)
                if not data or not data.get("view"):
                    text2 = call_llm(
                        vendor=vd,
                        model=md,
                        messages=messages
                        + [
                            {"role": "assistant", "content": text or ""},
                            {
                                "role": "user",
                                "content": "请只输出符合格式的 JSON 对象,不要任何前后说明。",
                            },
                        ],
                        json_mode=True,
                        max_tokens=mtokens,
                        temperature=0.3,
                        api_key=key_override,
                        base_url=bu or None,
                    )
                    data = _extract_json(text2)

                if data and data.get("view"):
                    valid = _validate_opinion(data, adv_member)
                    critique_op = ExpertOpinion(
                        expert_key=adv_member.id,
                        expert_name=adv_member.display_name,
                        style="批判性审查",
                        icon=adv_member.avatar,
                        view=valid["view"],
                        evidence=valid["evidence"],
                        action=valid.get("action", "观望"),
                        position=valid.get("position", 0),
                        stop_loss=valid.get("stop_loss", 0.0),
                        invalid_if=valid.get("invalid_if", ""),
                        risks=valid.get("risks", []),
                        vendor=VENDORS[vd]["label"],
                        model=md,
                        fallback_used=(vd != primary[0]),
                        ok=True,
                        role="lead",
                        card_style="critique",
                    )
                    break
                last_err = f"{vd} 未返回有效 JSON"
            except Exception as e:
                last_err = str(e)[:200]
                continue

        if critique_op is None:
            critique_op = ExpertOpinion(
                expert_key=adv_member.id,
                expert_name=adv_member.display_name,
                style="批判性审查",
                icon=adv_member.avatar,
                view="(魔鬼辩护人暂不可用)",
                evidence=[],
                action="观望",
                position=0,
                stop_loss=0.0,
                vendor="?",
                model="?",
                fallback_used=True,
                ok=False,
                error_msg=last_err or "未知错误",
                role="lead",
            )
    except Exception as e:
        critique_op = ExpertOpinion(
            expert_key="devils_advocate",
            expert_name="魔鬼辩护人",
            style="批判性审查",
            icon="😈",
            view="(执行异常)",
            evidence=[],
            action="观望",
            ok=False,
            error_msg=str(e)[:200],
            role="lead",
        )

    summary = summarize(opinions)

    return {
        "opinions": opinions,
        "critique": critique_op,
        "summary": summary,
        "elapsed": round(time.time() - t0, 2),
        "team_id": team.id,
        "team_name": team.display_name,
        "member_order": [m.id for m in active_members],
        "run_mode": TeamRunMode.DEVILS_ADVOCATE.value,
    }


# ============== 模式 4: 主席裁决 ==============
_CHAIRMAN_SYSTEM_PROMPT = """你是一位投资分析会议的主席。你已经听取了所有专家的分析意见。
你的职责是：
1. 综合所有专家的观点，找出共识和分歧
2. 权衡不同观点的说服力
3. 给出一个经过深思熟虑的最终裁决
4. 明确指出哪些风险最值得关注

请以 JSON 格式返回你的裁决：
{"view": "你的综合裁决意见", "evidence": ["关键依据1", "关键依据2"], "action": "买入|观望|减持|卖出", "position": 30, "stop_loss": 1500.0, "risks": ["最重要的风险1", "最重要的风险2"]}
"""


def _run_chairman_ruling(
    team: ExpertTeamConfig,
    opinions: Dict[str, ExpertOpinion],
    stock_brief: str,
    stock_name: str,
    global_ai_settings: Optional[dict] = None,
    chairman_cfg: Optional[ExpertMemberConfig] = None,
) -> ExpertOpinion:
    """主席裁决：综合所有专家意见，给出最终判断。"""
    opinions_summary = _build_opinions_summary(opinions)

    # 确定主席配置
    if chairman_cfg is None:
        lead_member = next(
            (
                m
                for m in team.members
                if m.role == "lead" and getattr(m, "enabled", True)
            ),
            None,
        )
        chairman_cfg = lead_member or (team.members[0] if team.members else None)
    if chairman_cfg is None:
        return ExpertOpinion(
            expert_key="chairman",
            expert_name="主席",
            view="(无可用主席)",
            action="观望",
            ok=False,
            role="lead",
        )

    chairman_prompt = _CHAIRMAN_SYSTEM_PROMPT + (
        f"\n\n以下是各位专家对 {stock_name} 的分析意见：\n\n" + opinions_summary
    )

    chairman_member = ExpertMemberConfig(
        id=f"chairman_{chairman_cfg.id}",
        display_name=f"主席裁决({chairman_cfg.display_name})",
        display_name_en=f"Chairman Ruling ({chairman_cfg.display_name_en})",
        profession="综合裁决",
        profession_en="Chairman Ruling",
        avatar="👔",
        prompt_file="",
        role="lead",
        provider=chairman_cfg.provider,
        model=chairman_cfg.model,
        api_key=chairman_cfg.api_key,
        base_url=chairman_cfg.base_url,
        inherit_global_key=chairman_cfg.inherit_global_key,
        enabled=True,
        system_prompt=chairman_prompt,
        focus_dims=[],
        stop_loss_style="稳健",
    )

    user_msg = f"""请综合以上所有专家意见，对 {stock_name} 做出最终裁决。

原始市场简报：
{stock_brief}

请特别注意：
- 如果专家之间存在重大分歧，请说明你倾向哪一方以及原因
- 如果专家意见一致，请确认并补充你认为还需要关注的方面
- 给出一个具体的、可操作的最终建议

{{"view": "你的综合裁决", "evidence": ["关键依据"], "action": "买入|观望|减持|卖出", "position": 30, "stop_loss": 1500.0, "risks": ["风险"]}}"""

    preferred_vendor, preferred_model, api_key, base_url = _resolve_expert_ai_config(
        chairman_member, global_ai_settings
    )
    messages = [
        {"role": "system", "content": chairman_prompt},
        {"role": "user", "content": user_msg},
    ]

    primary = (preferred_vendor, preferred_model)
    fallback = FALLBACK_VENDOR_MODEL
    last_err = ""

    for vd, md, bu, key_override in [
        (preferred_vendor, preferred_model, base_url, api_key or None),
        (fallback[0], fallback[1], "", None),
    ]:
        cfg_v = VENDORS.get(vd) or {}
        if (
            not bu
            and (not cfg_v.get("api_key") or not cfg_v.get("base_url"))
            and not key_override
        ):
            last_err = f"{vd} 未配置完整"
            continue
        try:
            mtokens = 1500 if vd == "mimo" else 700
            text = call_llm(
                vendor=vd,
                model=md,
                messages=messages,
                json_mode=True,
                max_tokens=mtokens,
                temperature=0.3,
                api_key=key_override,
                base_url=bu or None,
            )
            data = _extract_json(text)
            if not data or not data.get("view"):
                text2 = call_llm(
                    vendor=vd,
                    model=md,
                    messages=messages
                    + [
                        {"role": "assistant", "content": text or ""},
                        {
                            "role": "user",
                            "content": "请只输出符合格式的 JSON 对象,不要任何前后说明。",
                        },
                    ],
                    json_mode=True,
                    max_tokens=mtokens,
                    temperature=0.2,
                    api_key=key_override,
                    base_url=bu or None,
                )
                data = _extract_json(text2)

            if data and data.get("view"):
                valid = _validate_opinion(data, chairman_member)
                return ExpertOpinion(
                    expert_key=chairman_member.id,
                    expert_name=chairman_member.display_name,
                    style="综合裁决",
                    icon=chairman_member.avatar,
                    view=valid["view"],
                    evidence=valid["evidence"],
                    action=valid.get("action", "观望"),
                    position=valid.get("position", 0),
                    stop_loss=valid.get("stop_loss", 0.0),
                    invalid_if=valid.get("invalid_if", ""),
                    risks=valid.get("risks", []),
                    vendor=VENDORS[vd]["label"],
                    model=md,
                    fallback_used=(vd != primary[0]),
                    ok=True,
                    role="lead",
                    card_style="chairman",
                )
            last_err = f"{vd} 未返回有效 JSON"
        except Exception as e:
            last_err = str(e)[:200]
            continue

    return ExpertOpinion(
        expert_key=chairman_member.id,
        expert_name=chairman_member.display_name,
        style="综合裁决",
        icon=chairman_member.avatar,
        view="(主席裁决暂不可用)",
        evidence=[],
        action="观望",
        position=0,
        stop_loss=0.0,
        vendor="?",
        model="?",
        fallback_used=True,
        ok=False,
        error_msg=last_err or "未知错误",
        role="lead",
    )


# ============== 辩论变化摘要 ==============
def summarize_debate(
    round1_opinions: Dict[str, ExpertOpinion],
    round2_opinions: Dict[str, ExpertOpinion],
) -> dict:
    """
    对比辩论前后专家意见的变化，返回变化摘要。
    返回:
      {
        "changes": [
          {
            "expert_key":   str,
            "expert_name":  str,
            "action_before": str,
            "action_after":  str,
            "action_changed": bool,
            "position_before": float,
            "position_after":  float,
            "position_delta":  float,
            "view_before":   str,
            "view_after":    str,
            "view_changed":  bool,
          },
          ...
        ],
        "action_change_count": int,  # 改变操作建议的专家数
        "position_avg_before": float,
        "position_avg_after":  float,
        "position_avg_delta":  float,
        "summary_before": {...},
        "summary_after":  {...},
      }
    """
    changes = []
    action_change_count = 0
    total_pos_before = 0.0
    total_pos_after = 0.0
    n_valid = 0

    for key in round1_opinions:
        op1 = round1_opinions.get(key)
        op2 = round2_opinions.get(key)
        if not op1 or not op2:
            continue

        action_changed = op1.action != op2.action
        view_changed = op1.view.strip() != op2.view.strip()
        position_delta = op2.position - op1.position

        if op1.ok:
            n_valid += 1
            total_pos_before += op1.position
            total_pos_after += op2.position

        if action_changed:
            action_change_count += 1

        changes.append(
            {
                "expert_key": key,
                "expert_name": op1.expert_name,
                "action_before": op1.action,
                "action_after": op2.action,
                "action_changed": action_changed,
                "position_before": op1.position,
                "position_after": op2.position,
                "position_delta": round(position_delta, 1),
                "view_before": op1.view,
                "view_after": op2.view,
                "view_changed": view_changed,
            }
        )

    pos_avg_before = round(total_pos_before / n_valid, 1) if n_valid else 0.0
    pos_avg_after = round(total_pos_after / n_valid, 1) if n_valid else 0.0

    return {
        "changes": changes,
        "action_change_count": action_change_count,
        "position_avg_before": pos_avg_before,
        "position_avg_after": pos_avg_after,
        "position_avg_delta": round(pos_avg_after - pos_avg_before, 1),
        "summary_before": summarize(round1_opinions),
        "summary_after": summarize(round2_opinions),
    }


# ============== 统一入口: run_team_roundtable (v2 增强) ==============
# 以下保留原有 run_team_roundtable 签名并向外兼容，
# 同时新增 run_mode 参数支持 5 种模式调度。


# ============== Markdown 导出 ==============
def export_md(
    opinions: Dict[str, ExpertOpinion],
    summary: dict,
    stock_name: str,
    symbol: str,
    team_name: str = "",
) -> str:
    """三段式纪要"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")
    team_tag = f" · {team_name}" if team_name else ""

    lines = [
        f"# {stock_name}({symbol}) 专家圆桌纪要",
        "",
        f"> 召开时间: {now}  ",
        f"> 工作台: 研策中枢 AlphaScope v2.0{team_tag} · 专家圆桌",
        "",
        "## 投票汇总",
        "",
        f"- **{summary.get('buy', 0)} 买 / {summary.get('hold', 0)} 观 / "
        f"{summary.get('reduce', 0)} 减 / {summary.get('sell', 0)} 卖**",
        f"- 平均建议仓位: **{summary.get('avg_position', 0):.1f}%**",
        f"- 有效专家: {summary.get('valid_count', 0)}/{summary.get('total_count', 0)}",
        "",
        "## 各专家观点",
        "",
    ]

    # 固定顺序展示（兼容 v1.0）
    order = ["buffett", "lynch", "chanlun", "macro", "risk_officer"]
    # 如果有不在固定列表中的 key，也展示出来
    remaining = [k for k in opinions.keys() if k not in order]

    for key in order + remaining:
        op = opinions.get(key)
        if not op:
            continue
        fb_tag = " ⚠️ *降级模型*" if op.fallback_used else ""
        ok_tag = "" if op.ok else " ❌ *该专家本次不可用*"
        role_tag = f" [{op.role}]" if op.role != "member" else ""
        lines += [
            f"### {op.icon} {op.expert_name}({op.style}){role_tag}{ok_tag}",
            "",
            f"> 模型: **{op.vendor}** / `{op.model}`{fb_tag}",
            "",
            f"**核心观点**: {op.view}",
            "",
            "**关键依据**:",
        ]
        if op.evidence:
            for ev in op.evidence:
                if isinstance(ev, dict):
                    parts = [str(ev.get("claim") or "").strip()]
                    etype = ev.get("type")
                    if etype and etype != "other":
                        parts.append(f"[{etype}]")
                    date = ev.get("data_date")
                    if date:
                        parts.append(f"({date})")
                    text = " ".join(p for p in parts if p)
                else:
                    text = str(ev).strip()
                if text:
                    lines.append(f"- {text}")
        else:
            lines.append("- (无)")
        lines += [
            "",
            f"**操作建议**: {op.action} | **建议仓位**: {op.position}% | "
            f"**止损位**: ¥{op.stop_loss:.2f}",
        ]
        if getattr(op, "invalid_if", ""):
            lines += ["", f"**失效条件**: {op.invalid_if}"]
        if getattr(op, "risks", None):
            lines += ["", "**主要风险**:"]
            for r in op.risks:
                lines.append(f"- {r}")
        lines += [
            "",
            "---",
            "",
        ]

    lines += [
        "",
        f"*由研策中枢 AlphaScope v2.0 专家圆桌模块自动生成,数据来自 akshare {today}*",
    ]
    return "\n".join(lines)


# ============== 命令行自测 ==============
def _build_quick_brief(symbol: str, stock_name: str) -> str:
    """命令行测试用:从 akshare 拉一个简短行情简报"""
    import akshare as ak
    import pandas as pd
    from fund_flow import (
        fetch_individual_fund_flow,
        summarize_fund_flow,
        build_fund_flow_brief_for_llm,
    )

    lines = [f"【标的】{stock_name}({symbol})"]
    try:
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - pd.Timedelta(days=180)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily", start_date=start, end_date=end, adjust="qfq"
        )
        if df is not None and not df.empty:
            df.columns = [
                "date",
                "code",
                "open",
                "close",
                "high",
                "low",
                "volume",
                "amount",
                "amplitude",
                "pct_chg",
                "change",
                "turnover",
            ][: len(df.columns)]
            last = df.iloc[-1]
            first = df.iloc[0]
            period_chg = (last["close"] / first["close"] - 1) * 100
            lines += [
                "\n【价格信息】",
                f"- 最新价: ¥{last['close']:.2f} (当日 {last.get('pct_chg', 0):+.2f}%)",
                f"- 区间涨跌: {period_chg:+.2f}% (近 {len(df)} 个交易日)",
                f"- 区间最高/最低: ¥{df['high'].max():.2f} / ¥{df['low'].min():.2f}",
                f"- 成交均量: {df['volume'].mean():,.0f}手",
            ]
    except Exception as e:
        lines.append(f"(行情拉取失败: {e})")

    try:
        df_fund = fetch_individual_fund_flow(symbol, days=30)
        if df_fund is not None:
            s = summarize_fund_flow(df_fund, recent_days=5)
            lines.append("\n" + build_fund_flow_brief_for_llm(s, kind=stock_name))
    except Exception:
        pass

    return "\n".join(lines)


if __name__ == "__main__":
    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    name_map = {"600519": "贵州茅台", "300059": "东方财富", "000858": "五粮液"}
    name = name_map.get(code, code)

    print("=" * 70)
    print(f"专家圆桌测试: {name}({code})")
    print("=" * 70)

    # 先测试 v2.0 配置
    print("\n[0] 加载 v2.0 teams 配置...")
    teams = load_experts_config_v2()
    if teams:
        print(f"    ✓ 加载 {len(teams)} 个团队:")
        for t in teams:
            print(f"      团队: {t.display_name} ({len(t.members)} 位成员)")
            for m in t.members:
                role_tag = " [LEAD]" if m.role == "lead" else ""
                print(
                    f"        {m.avatar} {m.display_name}{role_tag} → {m.provider}/{m.model}"
                )
    else:
        print("    ! 未找到 v2.0 teams 配置，将使用 v1.0 兼容模式")

    print("\n[1] 加载 v1.0 experts 配置...")
    experts = load_experts_config()
    print(f"    ✓ {len(experts)} 位专家:")
    for e in experts:
        print(f"      {e.icon} {e.name:<10} → {e.preferred_vendor}/{e.preferred_model}")

    print("\n[2] 构造市场简报...")
    brief = _build_quick_brief(code, name)
    print(f"    ✓ 简报 {len(brief)} 字符")

    # 如果有 v2.0 团队配置，测试团队模式
    if teams:
        print(f"\n[3] v2.0 团队并行调用(团队: {teams[0].display_name})...")
        result = run_team_roundtable(teams[0], brief, name)
        print(f"    ✓ 完成,耗时 {result['elapsed']}s")
    else:
        print("\n[3] v1.0 5 专家并行调用(预计 8-15 秒)...")
        result = run_roundtable(brief, name)
        print(f"    ✓ 完成,耗时 {result['elapsed']}s")

    print("\n[4] 各专家观点:")
    order = ["buffett", "lynch", "chanlun", "macro", "risk_officer"]
    for key in order:
        op = result["opinions"].get(key)
        if not op:
            continue
        flag = "OK" if op.ok else "FAIL"
        fb = " (降级)" if op.fallback_used else ""
        role_tag = f" [{op.role}]" if getattr(op, "role", "member") != "member" else ""
        print(
            f"\n  {op.icon} {op.expert_name}{role_tag} [{op.vendor}/{op.model}]{fb} {flag}"
        )
        if op.ok:
            print(f"    view: {op.view[:80]}")
            print(
                f"    action: {op.action} | position: {op.position}% | stop: ¥{op.stop_loss:.2f}"
            )
            if op.evidence:
                ev0 = op.evidence[0]
                ev_str = str(ev0)[:60] if isinstance(ev0, dict) else ev0[:60]
                print(f"    evidence: {ev_str}...")
        else:
            print(f"    error: {op.error_msg[:100]}")

    s = result["summary"]
    print(
        f"\n[5] 投票汇总: {s.get('buy', 0)}买/{s.get('hold', 0)}观/"
        f"{s.get('reduce', 0)}减/{s.get('sell', 0)}卖"
    )
    print(f"    平均仓位: {s.get('avg_position', 0):.1f}%")
    print(f"    有效专家: {s.get('valid_count', 0)}/{s.get('total_count', 0)}")

    print("\n[6] Markdown 导出预览:")
    team_name = result.get("team_name", "")
    md = export_md(result["opinions"], s, name, code, team_name)
    print(f"    ✓ {len(md)} 字符")
    print(md[:500] + "...")
