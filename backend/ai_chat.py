"""
AI 咨询服务层（v0.7 新增）

提供：
- ChatSession / ChatMessage dataclass
- new_session: 创建新会话（拼接首次 system prompt）
- build_system_prompt: 上下文注入（最新价/MA/资金面/最新归档摘要）
- send_message: 追加用户输入 → 截断历史 → 调 LLM → 追加助手回复
- truncate_history: 超过 30 轮自动截断（保留 system + 最近 30 轮）
- export_to_markdown: 导出整个会话为 Markdown 文本

LLM 调用统一走 llm_agents.call_llm；默认厂商通过 .env AI_CHAT_PROVIDER 配置。
"""

import os
import sys
import inspect
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from openai import OpenAI

# 复用 llm_agents 的客户端层
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_agents as _llm_agents  # noqa: E402

try:
    from backend.project_paths import ENV_FILE  # noqa: E402
except ImportError:
    from project_paths import ENV_FILE  # noqa: E402

# Streamlit 热重载时 sys.modules 里可能残留旧版 llm_agents（无 call_llm 别名）。
# 这里做运行时兜底，避免整个前端组件因导入别名失败而不加载。
call_llm = getattr(_llm_agents, "call_llm", _llm_agents._call_with)
VENDORS = _llm_agents.VENDORS
FALLBACK_VENDOR_MODEL = _llm_agents.FALLBACK_VENDOR_MODEL


def _call_llm_compat(payload: dict, api_key: Optional[str] = None) -> str:
    """Call llm_agents.call_llm while tolerating old hot-reload signatures explicitly."""
    params = inspect.signature(call_llm).parameters
    if "api_key" in params:
        return call_llm(**payload, api_key=api_key)
    return call_llm(**payload)


from dotenv import load_dotenv

load_dotenv(ENV_FILE)


# ============== 默认厂商/模型映射 ==============
# 每个厂商的 AI 咨询默认模型
PROVIDER_DEFAULT_MODEL = dict(_llm_agents.DEFAULT_PROVIDER_MODELS)

# 单会话最大轮数（超过自动截断）
MAX_ROUNDS = 30


# ============== Dataclass ==============
@dataclass
class ChatMessage:
    role: str = "user"  # system / user / assistant
    content: str = ""
    timestamp: str = ""

    @staticmethod
    def now(role: str, content: str) -> "ChatMessage":
        return ChatMessage(
            role=role,
            content=content,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )


@dataclass
class ChatSession:
    stock_symbol: str = ""
    stock_name: str = ""
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""  # 自定义 API Key（可选，覆盖 provider 默认配置）
    custom_base_url: str = ""  # 自定义 OpenAI-compatible Base URL（仅当前会话内存）
    custom_models: List[str] = field(default_factory=list)  # 当前会话拉取/添加的自定义模型
    messages: List[ChatMessage] = field(default_factory=list)
    context_snapshot: dict = field(default_factory=dict)  # 注入的上下文快照
    max_rounds: int = MAX_ROUNDS
    created_at: str = ""

    def append(self, role: str, content: str):
        self.messages.append(ChatMessage.now(role, content))

    def to_markdown(self) -> str:
        return export_to_markdown(self)


# ============== 上下文注入 ==============
def build_system_prompt(stock_symbol: str, stock_name: str, ctx: dict) -> str:
    """
    根据上下文构造 system prompt。
    ctx 字段可选：
      - close: float
      - day_change: float
      - ma5/ma20/ma60: float
      - period_change: float
      - fund_dir: str (主力方向描述)
      - latest_archive_excerpt: str (最近一份归档报告摘要，可空)
      - data_date: str
    """
    close = ctx.get("close", 0)
    day_change = ctx.get("day_change", 0)
    ma5 = ctx.get("ma5", "N/A")
    ma20 = ctx.get("ma20", "N/A")
    ma60 = ctx.get("ma60", "N/A")
    period_change = ctx.get("period_change", 0)
    fund_dir = ctx.get("fund_dir", "暂无主力资金数据")
    archive = ctx.get("latest_archive_excerpt", "")
    data_date = ctx.get("data_date") or datetime.now().strftime("%Y-%m-%d")

    archive_block = (
        f"【最近一份 Agent 深度研究摘要】\n{archive}\n"
        if archive
        else "【最近一份 Agent 深度研究摘要】\n暂无最新 Agent 报告,请基于价格/资金面回答。\n"
    )

    return f"""你是一位资深金融分析师,正在与用户讨论 A 股标的【{stock_name}({stock_symbol})】。

【实时行情快照(数据日期 {data_date})】
- 最新价: ¥{close:.2f}（当日 {day_change:+.2f}%）
- 区间涨跌: {period_change:+.2f}%
- MA5 / MA20 / MA60: {ma5} / {ma20} / {ma60}

【主力资金面】
{fund_dir}

{archive_block}

【回答要求】
1. 基于以上行情/资金/研究摘要数据回答问题,不要凭空猜测公司未在数据中的细节。
2. 简明扼要,中文回答,200-400 字为宜;复杂问题可分点。
3. 如果用户的问题与当前股票无关,礼貌引导回归。
4. 每次回答末尾必须附一行:`数据来自 akshare {data_date}`。
"""


# ============== 会话管理 ==============
def new_session(
    stock_symbol: str,
    stock_name: str,
    ctx: Optional[dict] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> ChatSession:
    """创建新会话:首条 system message 已拼接好,可直接调 send_message"""
    ctx = ctx or {}
    provider, default_model = _llm_agents.get_configured_provider(provider)
    model = model or default_model

    sys_prompt = build_system_prompt(stock_symbol, stock_name, ctx)
    session = ChatSession(
        stock_symbol=stock_symbol,
        stock_name=stock_name,
        provider=provider,
        model=model,
        api_key=api_key or "",
        context_snapshot=dict(ctx),
        max_rounds=MAX_ROUNDS,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    session.append("system", sys_prompt)
    return session


def truncate_history(session: ChatSession) -> ChatSession:
    """超过 max_rounds 轮(一轮=user+assistant=2 条)时,保留 system + 最近 max_rounds 轮"""
    sys_msgs = [m for m in session.messages if m.role == "system"]
    chat_msgs = [m for m in session.messages if m.role != "system"]
    max_chat_msgs = session.max_rounds * 2  # 一轮 = 2 条
    if len(chat_msgs) > max_chat_msgs:
        chat_msgs = chat_msgs[-max_chat_msgs:]
    session.messages = sys_msgs + chat_msgs
    return session


def _build_payload(session: ChatSession) -> List[dict]:
    """转成 OpenAI 风格 messages"""
    return [{"role": m.role, "content": m.content} for m in session.messages]


def normalize_base_url(base_url: str) -> str:
    """规范化 OpenAI-compatible Base URL：允许用户填根域名或 /v1。"""
    return _llm_agents.validate_custom_base_url(base_url)


def _create_custom_client(base_url: str, api_key: str) -> OpenAI:
    """创建临时 OpenAI-compatible 客户端，不缓存、不落盘，避免 Key 串用。"""
    base_url = normalize_base_url(base_url)
    if not base_url:
        raise RuntimeError("请先填写自定义 API Base URL")
    if not (api_key or "").strip():
        raise RuntimeError("请先填写自定义 API Key")
    return OpenAI(api_key=api_key.strip(), base_url=base_url, timeout=60.0)


def fetch_model_list(base_url: str, api_key: str) -> List[str]:
    """从 OpenAI-compatible /models 接口拉取模型 ID 列表。"""
    client = _create_custom_client(base_url, api_key)
    models = client.models.list()
    ids = sorted({getattr(m, "id", "") for m in getattr(models, "data", []) if getattr(m, "id", "")})
    return ids


def call_llm_custom(
    base_url: str,
    api_key: str,
    model: str,
    messages: list,
    max_tokens: int = 2048,
    temperature: float = 0.4,
) -> str:
    """调用用户自定义 OpenAI-compatible 模型。"""
    if not (model or "").strip():
        raise RuntimeError("请先选择或填写自定义模型名称")
    client = _create_custom_client(base_url, api_key)
    resp = client.chat.completions.create(
        model=model.strip(),
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def send_message(session: ChatSession, user_msg: str) -> ChatSession:
    """append user → truncate → call_llm → append assistant"""
    if not user_msg or not user_msg.strip():
        return session

    session.append("user", user_msg.strip())
    session = truncate_history(session)

    # 自定义厂商优先：用户填写 base_url + key 后，直接走临时 OpenAI-compatible 客户端。
    if getattr(session, "custom_base_url", ""):
        try:
            reply = call_llm_custom(
                base_url=getattr(session, "custom_base_url", ""),
                api_key=getattr(session, "api_key", ""),
                model=session.model,
                messages=_build_payload(session),
                max_tokens=2048,
                temperature=0.4,
            )
        except Exception as e:
            reply = f"⚠️ 自定义模型调用失败: {str(e)[:200]}"
        session.append("assistant", reply or "⚠️ 自定义模型未返回内容")
        return session

    # 双层兜底:主厂商失败 → DeepSeek
    primary = (session.provider, session.model)
    fallback = _llm_agents.get_configured_provider()
    last_err = None
    reply = None
    candidates = [primary]
    if fallback != primary:
        candidates.append(fallback)
    for vd, md in candidates:
        try:
            payload = dict(
                vendor=vd,
                model=md,
                messages=_build_payload(session),
                json_mode=False,
                max_tokens=2048,
                temperature=0.4,
            )
            # Streamlit 热重载时 call_llm 可能仍指向旧函数签名，不接受 api_key。
            # 用签名检查兼容旧函数，避免 TypeError 字符串匹配掩盖真实错误。
            key_override = (getattr(session, "api_key", "") or None) if (vd, md) == primary else None
            reply = _call_llm_compat(payload, api_key=key_override)
            if reply and reply.strip():
                if (vd, md) != primary:
                    reply = f"_(主厂商 {primary[0]} 不可用,已切换到 {vd}/{md})_\n\n" + reply
                break
        except Exception as e:
            last_err = str(e)[:200]
            continue

    if not reply:
        reply = f"⚠️ 模型调用失败: {last_err or '所有厂商都不可用'}"

    session.append("assistant", reply)
    return session


# ============== 导出 ==============
def export_to_markdown(session: ChatSession) -> str:
    """生成可读 Markdown 文本"""
    lines = [
        f"# AI 咨询会话 - {session.stock_name}({session.stock_symbol})",
        "",
        f"> 创建时间: {session.created_at}  ",
        f"> 模型: {session.provider} / `{session.model}`  ",
        f"> 总轮次: {sum(1 for m in session.messages if m.role == 'user')}",
        "",
        "---",
        "",
    ]

    # 上下文快照
    if session.context_snapshot:
        lines += ["## 上下文快照", "", "```"]
        for k, v in session.context_snapshot.items():
            lines.append(f"{k}: {v}")
        lines += ["```", ""]

    lines += ["## 对话记录", ""]

    for m in session.messages:
        if m.role == "system":
            continue
        if m.role == "user":
            lines += [f"### 🙋 用户  `{m.timestamp}`", "", m.content, ""]
        elif m.role == "assistant":
            lines += [
                f"### 🤖 助手 ({session.provider})  `{m.timestamp}`",
                "",
                m.content,
                "",
            ]
        lines.append("---")
        lines.append("")

    lines += [
        f"*由研策中枢 AlphaScope AI 咨询模块自动生成,模型 {session.provider}/{session.model}*",
    ]
    return "\n".join(lines)


# ============== 命令行自测 ==============
if __name__ == "__main__":
    print("=" * 70)
    print("AI 咨询模块自测")
    print("=" * 70)

    # 模拟 ctx
    ctx = {
        "close": 1680.50,
        "day_change": 1.25,
        "period_change": 8.6,
        "ma5": "1665.30",
        "ma20": "1640.20",
        "ma60": "1620.10",
        "fund_dir": "近 5 日主力净流入 12.3 亿,超大单流入,游资跟风,散户净流出",
        "latest_archive_excerpt": "5 Agent 投票 4 买 1 观,主席总结:估值合理,基本面稳健,建议持有",
    }

    # 1. new_session
    sess = new_session("600519", "贵州茅台", ctx)
    assert any(m.role == "system" for m in sess.messages), "首条应有 system"
    print(f"[1] new_session OK | provider={sess.provider} | model={sess.model}")
    print(f"    System prompt 前 200 字: {sess.messages[0].content[:200]}...")

    # 2. truncate_history
    print("\n[2] 模拟 35 轮对话后截断...")
    for i in range(35):
        sess.append("user", f"模拟问题 {i + 1}")
        sess.append("assistant", f"模拟回复 {i + 1}")
    before = len(sess.messages)
    truncate_history(sess)
    after = len(sess.messages)
    chat_msgs = [m for m in sess.messages if m.role != "system"]
    print(f"    截断前 {before} 条,截断后 {after} 条 (chat={len(chat_msgs)})")
    assert len(chat_msgs) == sess.max_rounds * 2, f"应保留 {sess.max_rounds * 2} 条 chat msg"
    print("    ✓ 截断逻辑正确")

    # 3. export_to_markdown
    print("\n[3] export_to_markdown...")
    md = export_to_markdown(sess)
    assert "AI 咨询会话" in md and "贵州茅台" in md
    print(f"    ✓ 导出 {len(md)} 字符 Markdown")

    # 4. 真实调用 send_message(可选,需要 API)
    print("\n[4] 真实 send_message 调用(可能耗时 5-15 秒)...")
    fresh = new_session("600519", "贵州茅台", ctx)
    try:
        fresh = send_message(fresh, "现在估值贵不贵?用一句话回答。")
        last = fresh.messages[-1]
        if last.role == "assistant":
            print(f"    ✓ 模型回复({len(last.content)} 字):")
            print(f"    {last.content[:200]}...")
        else:
            print(f"    ⚠️ 最后一条不是 assistant: {last.role}")
    except Exception as e:
        print(f"    ⚠️ 真实调用失败(网络/Key 问题,不影响逻辑测试): {e}")

    print("\n" + "=" * 70)
    print("ai_chat 自测完成 ✓")
