"""AI 对话编排器

路由用户请求到适当的分析管道：
- FREE: ai_chat.send_message (简单问答)
- STANDARD: llm_agents.run_agents_with_mode(STANDARD) (3 Agent)
- DEEP: llm_agents.run_agents_with_mode(DEEP) (5 Agent + Critic + Chairman)
- EXPERT: expert_panel.run_team_roundtable (专家团圆桌)
- VISION: 图表/截图分析 (预留)

编排器内置 NLU Intent Router，通过关键词匹配自动检测用户意图，
在用户未明确选择模式时自动推荐最合适的分析模式。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .compliance import check_forbidden_words, wrap_with_disclaimer
from .conversation_store import ConversationStore
from .report_generator import generate_report


def _default_llm_identity(preferred: Optional[str] = None) -> tuple[str, str]:
    try:
        from backend.models.provider_gateway import get_configured_provider

        return get_configured_provider(preferred)
    except Exception:
        return preferred or "deepseek", "deepseek-chat"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AnalysisMode(Enum):
    FREE = "free"
    STANDARD = "standard"
    DEEP = "deep"
    EXPERT = "expert"
    VISION = "vision"


# 模式标签映射
MODE_LABELS = {
    AnalysisMode.FREE: "自由问答",
    AnalysisMode.STANDARD: "标准分析",
    AnalysisMode.DEEP: "深度分析",
    AnalysisMode.EXPERT: "专家团圆桌",
    AnalysisMode.VISION: "图表分析",
}


# ---------------------------------------------------------------------------
# NLU Intent Router - 基于关键词的意图检测（零 LLM 成本）
# ---------------------------------------------------------------------------


class IntentType(Enum):
    """用户意图类型"""

    STOCK_ANALYSIS = "stock_analysis"  # 股票分析（基本面、估值等）
    GENERAL_QUESTION = "general_question"  # 通用问答
    KLINE_ANALYSIS = "kline_analysis"  # K线/技术面分析
    NEWS_QUERY = "news_query"  # 新闻/公告查询
    COMPARISON = "comparison"  # 多股票对比
    PORTFOLIO_REVIEW = "portfolio_review"  # 持仓/组合分析


# 意图关键词表（按优先级排列，先匹配先命中）
_INTENT_KEYWORDS: Dict[IntentType, List[str]] = {
    IntentType.KLINE_ANALYSIS: [
        "K线",
        "k线",
        "K线图",
        "走势图",
        "技术面",
        "技术分析",
        "均线",
        "MACD",
        "macd",
        "KDJ",
        "kdj",
        "RSI",
        "rsi",
        "布林",
        "支撑位",
        "压力位",
        "突破",
        "金叉",
        "死叉",
        "成交量",
        "量价",
        "分时",
        "蜡烛图",
        "趋势线",
        "波浪",
        "头肩",
        "双底",
        "双顶",
        "底部放量",
        "缩量",
    ],
    IntentType.COMPARISON: [
        "对比",
        "比较",
        "vs",
        "VS",
        "哪个好",
        "哪个强",
        "选哪个",
        "优劣",
        "谁更好",
        "哪个更",
        "还是",
        "相比",
        "比一比",
        "哪个值得",
    ],
    IntentType.NEWS_QUERY: [
        "新闻",
        "公告",
        "最新消息",
        "近期消息",
        "快讯",
        "媒体报道",
        "舆情",
        "利好",
        "利空",
        "消息面",
        "最新动态",
        "最新进展",
        "事件",
    ],
    IntentType.PORTFOLIO_REVIEW: [
        "持仓",
        "组合",
        "仓位",
        "调仓",
        "资产配置",
        "我的股票",
        "自选股",
        "持仓分析",
        "组合分析",
        "风险敞口",
        "分散",
        "集中度",
    ],
    IntentType.STOCK_ANALYSIS: [
        "分析",
        "估值",
        "基本面",
        "财报",
        "业绩",
        "市盈率",
        "PE",
        "pe",
        "市净率",
        "PB",
        "pb",
        "ROE",
        "roe",
        "营收",
        "净利润",
        "毛利率",
        "买入",
        "卖出",
        "目标价",
        "评级",
        "研报",
        "怎么样",
        "值得买",
        "能不能买",
        "怎么看",
        "前景",
        "走势",
        "涨跌",
        "推荐",
    ],
}

# 股票代码模式：6位纯数字（沪深），或 sh/sz/bj + 6位
_STOCK_CODE_PATTERN = re.compile(r"(?:sh|sz|bj|SH|SZ|BJ)?\d{6}(?:\.SH|\.SZ|\.BJ)?")

# 常见股票名称（按需扩展）
_STOCK_NAMES: List[str] = [
    "贵州茅台",
    "中国平安",
    "招商银行",
    "宁德时代",
    "比亚迪",
    "隆基绿能",
    "五粮液",
    "美的集团",
    "格力电器",
    "中信证券",
    "恒瑞医药",
    "海天味业",
    "迈瑞医疗",
    "东方财富",
    "长江电力",
    "工商银行",
    "建设银行",
    "农业银行",
    "中国银行",
    "交通银行",
    "中国中免",
    "药明康德",
    "阳光电源",
    "万华化学",
    "紫金矿业",
    "三一重工",
    "海螺水泥",
    "中国神华",
    "中国石油",
    "中国石化",
    "腾讯",
    "阿里巴巴",
    "美团",
    "京东",
    "拼多多",
]


def detect_intent(user_input: str, stock_data: Optional[Dict[str, Any]] = None) -> IntentType:
    """检测用户意图（基于关键词匹配，零 LLM 成本）。

    Args:
        user_input: 用户输入文本
        stock_data: 当前股票上下文（可选，用于辅助判断）

    Returns:
        IntentType 枚举值
    """
    if not user_input or not user_input.strip():
        return IntentType.GENERAL_QUESTION

    text = user_input.strip()

    # 1. 检查是否涉及多股票（对比意图优先，因为对比通常包含其他关键词）
    has_comparison = any(kw in text for kw in _INTENT_KEYWORDS[IntentType.COMPARISON])
    stock_mentions = _count_stock_mentions(text)
    if has_comparison and stock_mentions >= 2:
        return IntentType.COMPARISON

    # 2. 按意图关键词表逐项匹配
    # 优先级：KLINE > COMPARISON(单关键词) > NEWS > PORTFOLIO > STOCK_ANALYSIS
    for intent_type in [
        IntentType.KLINE_ANALYSIS,
        IntentType.COMPARISON,
        IntentType.NEWS_QUERY,
        IntentType.PORTFOLIO_REVIEW,
        IntentType.STOCK_ANALYSIS,
    ]:
        keywords = _INTENT_KEYWORDS[intent_type]
        for kw in keywords:
            if kw in text:
                logger.debug("意图检测: 关键词 '%s' -> %s", kw, intent_type.value)
                return intent_type

    # 3. 如果提到了股票代码或名称，但没有匹配到具体意图，默认为股票分析
    if stock_mentions > 0:
        return IntentType.STOCK_ANALYSIS

    # 4. 如果当前已有股票上下文，用户可能在追问
    if stock_data:
        return IntentType.STOCK_ANALYSIS

    # 5. 回退到通用问答
    return IntentType.GENERAL_QUESTION


def _count_stock_mentions(text: str) -> int:
    """统计文本中提到的股票数量（代码 + 名称去重）。"""
    mentions: set = set()

    # 匹配股票代码
    for m in _STOCK_CODE_PATTERN.finditer(text):
        mentions.add(m.group())

    # 匹配股票名称
    for name in _STOCK_NAMES:
        if name in text:
            mentions.add(name)

    return len(mentions)


def suggest_mode(intent: IntentType, stock_data: Optional[Dict[str, Any]] = None) -> AnalysisMode:
    """根据意图推荐最合适的分析模式。

    Args:
        intent: 检测到的用户意图
        stock_data: 当前股票上下文

    Returns:
        推荐的 AnalysisMode
    """
    _INTENT_TO_MODE: Dict[IntentType, AnalysisMode] = {
        IntentType.STOCK_ANALYSIS: AnalysisMode.STANDARD,
        IntentType.KLINE_ANALYSIS: AnalysisMode.DEEP,
        IntentType.COMPARISON: AnalysisMode.DEEP,
        IntentType.NEWS_QUERY: AnalysisMode.STANDARD,
        IntentType.PORTFOLIO_REVIEW: AnalysisMode.EXPERT,
        IntentType.GENERAL_QUESTION: AnalysisMode.FREE,
    }
    return _INTENT_TO_MODE.get(intent, AnalysisMode.FREE)


def _import_ai_chat():
    """延迟导入 ai_chat 模块"""
    try:
        from backend.ai_chat import new_session, send_message
    except ImportError:
        from ai_chat import new_session, send_message

    return new_session, send_message


def _import_llm_agents():
    """延迟导入 llm_agents 模块"""
    try:
        from backend.agent_modes import AnalysisMode as AgentAnalysisMode
        from backend.llm_agents import build_market_brief, run_agents_with_mode
    except ImportError:
        from agent_modes import AnalysisMode as AgentAnalysisMode
        from llm_agents import build_market_brief, run_agents_with_mode

    return run_agents_with_mode, build_market_brief, AgentAnalysisMode


def _import_expert_panel():
    """延迟导入 expert_panel 模块"""
    try:
        from backend.expert_panel import (
            ExpertTeamConfig,
            load_default_team,
            load_experts_config_v2,
            run_team_roundtable,
        )
    except ImportError:
        from expert_panel import (
            ExpertTeamConfig,
            load_default_team,
            load_experts_config_v2,
            run_team_roundtable,
        )

    return (
        run_team_roundtable,
        load_experts_config_v2,
        load_default_team,
        ExpertTeamConfig,
    )


class ChatOrchestrator:
    """路由用户查询到适当的分析管道。

    包装现有模块，管理对话生命周期。
    """

    def __init__(self, store: Optional[ConversationStore] = None):
        self._store = store or ConversationStore()
        self._chat_sessions = {}  # conversation_id -> ChatSession (for FREE mode)

    def new_conversation(
        self,
        stock_symbol: str = "",
        stock_name: str = "",
        mode: AnalysisMode = AnalysisMode.FREE,
        provider: str = "",
        model: str = "",
        title: str = "",
    ) -> str:
        """创建新对话，返回 ID"""
        provider, default_model = _default_llm_identity(provider)
        model = model or default_model
        if not title:
            mode_label = MODE_LABELS.get(mode, mode.value)
            if stock_symbol:
                title = f"{stock_name}({stock_symbol}) - {mode_label}"
            else:
                title = f"{mode_label} - {datetime.now().strftime('%m-%d %H:%M')}"
        return self._store.create_conversation(
            title=title,
            stock_symbol=stock_symbol,
            stock_name=stock_name,
            mode=mode.value,
            provider=provider,
            model=model,
        )

    def send_message(
        self,
        conversation_id: str,
        user_input: str,
        stock_data: Optional[Dict[str, Any]] = None,
        expert_team_id: Optional[str] = None,
        global_ai_settings: Optional[dict] = None,
        mode_override: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        image_base64: Optional[str] = None,
        image_mime_type: str = "image/png",
    ) -> dict:
        """处理用户消息，返回响应。

        路由逻辑：
        1. 检测用户意图 (detect_intent)
        2. 如果用户未显式指定模式，使用 suggest_mode 推荐
        3. 路由到对应的处理函数

        Args:
            conversation_id: 对话 ID
            user_input: 用户输入
            stock_data: 股票数据字典 (来自 dashboard 的 stock_data)
            expert_team_id: 专家团 ID (仅 EXPERT 模式)
            global_ai_settings: 全局 AI 设置
            mode_override: 外部显式指定的模式（跳过意图推荐）

        Returns:
            {
                "mode": str,
                "content": str,
                "agents": dict,       # standard/deep/expert
                "evidence": list,     # evidence chain
                "summary": dict,      # voting summary
                "compliance_note": str,
                "detected_intent": str,  # 检测到的意图
                "auto_routed": bool,     # 是否为自动路由
            }
        """
        # 存储用户消息
        self._store.add_message(conversation_id, "user", user_input)

        # 获取对话信息
        conv = self._store.get_conversation(conversation_id)
        if not conv:
            return {"mode": "error", "content": "对话不存在"}

        if provider or model:
            resolved_provider = provider or conv.get("provider") or ""
            resolved_provider, default_model = _default_llm_identity(resolved_provider)
            resolved_model = model or conv.get("model") or default_model
            self._store.update_model(conversation_id, resolved_provider, resolved_model)
            conv = {**conv, "provider": resolved_provider, "model": resolved_model}

        # --- NLU 意图检测 ---
        intent = detect_intent(user_input, stock_data)
        suggested_mode = suggest_mode(intent, stock_data)
        logger.info(
            "意图路由: input='%s' -> intent=%s, suggested_mode=%s",
            user_input[:50],
            intent.value,
            suggested_mode.value,
        )

        # 确定最终使用的模式
        auto_routed = False
        if mode_override:
            # 外部显式指定模式
            try:
                mode = AnalysisMode(mode_override)
            except ValueError:
                mode = suggested_mode
                auto_routed = True
        else:
            # 使用对话创建时指定的模式
            mode_str = conv.get("mode", "free")
            try:
                mode = AnalysisMode(mode_str)
            except ValueError:
                mode = AnalysisMode.FREE

            # 如果对话模式为 FREE（默认），且意图建议更具体的模式，则自动升级
            if mode == AnalysisMode.FREE and suggested_mode != AnalysisMode.FREE:
                # 只在有股票上下文时自动升级（FREE 模式下无股票时保持 FREE）
                if stock_data or suggested_mode in (AnalysisMode.FREE,):
                    mode = suggested_mode
                    auto_routed = True
                    logger.info("自动路由: FREE -> %s (intent=%s)", mode.value, intent.value)

        mode_str = mode.value

        # 路由到对应的处理函数
        try:
            if mode == AnalysisMode.FREE:
                result = self._handle_free_mode(conversation_id, user_input, stock_data, conv)
            elif mode in (AnalysisMode.STANDARD, AnalysisMode.DEEP):
                result = self._handle_agent_mode(conversation_id, user_input, stock_data, mode, conv)
            elif mode == AnalysisMode.EXPERT:
                result = self._handle_expert_mode(conversation_id, user_input, stock_data, expert_team_id, conv)
            elif mode == AnalysisMode.VISION:
                result = self._handle_vision_mode(user_input, stock_data, image_base64, image_mime_type)
            else:
                result = {"mode": mode_str, "content": "不支持的分析模式"}
        except Exception as e:
            logger.error("分析失败: %s", e, exc_info=True)
            result = {
                "mode": mode_str,
                "content": f"分析过程中出现错误: {str(e)[:300]}",
                "error": True,
            }

        # 合规检查：禁用词替换 + 风险提示
        content = result.get("content", "")
        content, forbidden = check_forbidden_words(content)
        if forbidden:
            result["forbidden_words_found"] = forbidden
        result["compliance_note"] = wrap_with_disclaimer("", mode_str)
        result["content"] = wrap_with_disclaimer(content, mode_str)

        # 注入意图元数据
        result["detected_intent"] = intent.value
        result["auto_routed"] = auto_routed

        # 存储助手回复
        self._store.add_message(
            conversation_id,
            "assistant",
            result["content"],
            metadata={
                "mode": mode_str,
                "agents": result.get("agents", {}),
                "evidence": result.get("evidence", []),
                "summary": result.get("summary", {}),
                "detected_intent": intent.value,
                "auto_routed": auto_routed,
            },
        )

        return result

    def _handle_free_mode(
        self,
        conversation_id: str,
        user_input: str,
        stock_data: Optional[dict],
        conv: dict,
    ) -> dict:
        """自由问答模式 - 委托给 ai_chat.send_message"""
        new_session, send_message = _import_ai_chat()

        # 构建上下文
        ctx = {}
        if stock_data:
            ctx = {
                "close": stock_data.get("close", 0),
                "day_change": stock_data.get("day_change", 0),
                "period_change": stock_data.get("period_change", 0),
                "ma5": stock_data.get("ma5", "N/A"),
                "ma20": stock_data.get("ma20", "N/A"),
                "ma60": stock_data.get("ma60", "N/A"),
                "fund_dir": stock_data.get("fund_dir", "暂无主力资金数据"),
                "data_date": stock_data.get("data_date", ""),
            }

        # 获取或创建 chat session
        if conversation_id not in self._chat_sessions:
            provider = conv.get("provider") or ""
            provider, default_model = _default_llm_identity(provider)
            model = conv.get("model") or default_model
            session = new_session(
                stock_symbol=conv.get("stock_symbol", ""),
                stock_name=conv.get("stock_name", ""),
                ctx=ctx,
                provider=provider,
                model=model,
            )
            stored_messages = self._store.get_messages(conversation_id)
            if (
                stored_messages
                and stored_messages[-1].get("role") == "user"
                and (stored_messages[-1].get("content") or "").strip() == user_input.strip()
            ):
                stored_messages = stored_messages[:-1]
            for message in stored_messages:
                role = message.get("role")
                content = message.get("content")
                if role in {"user", "assistant"} and content:
                    session.append(role, content)
            self._chat_sessions[conversation_id] = session
        else:
            session = self._chat_sessions[conversation_id]
            if conv.get("provider"):
                session.provider = conv.get("provider") or session.provider
            if conv.get("model"):
                session.model = conv.get("model") or session.model

        session = send_message(session, user_input)
        self._chat_sessions[conversation_id] = session

        # 取最后一条助手消息
        reply = ""
        for msg in reversed(session.messages):
            if msg.role == "assistant":
                reply = msg.content
                break

        return {
            "mode": "free",
            "content": reply,
            "provider": session.provider,
            "model": session.model,
        }

    def _handle_agent_mode(
        self,
        conversation_id: str,
        user_input: str,
        stock_data: Optional[dict],
        mode: AnalysisMode,
        conv: dict,
    ) -> dict:
        """Agent 分析模式 - 委托给 llm_agents.run_agents_with_mode"""
        if not stock_data:
            return {
                "mode": mode.value,
                "content": "请先选择一只股票后再进行分析。可以在左侧输入股票代码。",
            }

        run_agents_with_mode, build_market_brief, AgentAnalysisMode = _import_llm_agents()

        # 注入用户问题到 stock_data
        enhanced_data = dict(stock_data)
        if user_input:
            enhanced_data["user_question"] = user_input
            # 在 related_news_brief 前加入用户关注点
            existing_news = enhanced_data.get("related_news_brief", "")
            user_focus = f"【用户特别关注】\n{user_input}\n"
            if existing_news:
                enhanced_data["related_news_brief"] = user_focus + "\n" + existing_news
            else:
                enhanced_data["related_news_brief"] = user_focus

        # 确定 Agent 模式
        agent_mode = AgentAnalysisMode.STANDARD if mode == AnalysisMode.STANDARD else AgentAnalysisMode.DEEP

        # 运行分析
        result = run_agents_with_mode(enhanced_data, mode=agent_mode, global_ai_settings=None)

        # 格式化输出
        agents = result.get("agents", {})
        summary = result.get("summary", {})
        chairman = result.get("chairman", "")

        content_parts = []
        if chairman:
            content_parts.append(f"## 主席总结\n\n{chairman}")

        # 投票汇总
        buy = summary.get("buy", 0)
        sell = summary.get("sell", 0)
        hold = summary.get("hold", 0)
        content_parts.append(f"\n**投票**: 买入 {buy} / 观望 {hold} / 卖出 {sell}")

        # 各 Agent 观点摘要
        content_parts.append("\n## 各 Agent 观点\n")
        for agent_key, agent_result in agents.items():
            signal = agent_result.get("signal", "hold")
            confidence = agent_result.get("confidence", 0)
            reason = agent_result.get("reason", agent_result.get("summary", ""))[:150]
            content_parts.append(f"- **{agent_key}**: {signal} (置信度 {confidence}%) - {reason}")

        # 证据链
        evidence = []
        for agent_result in agents.values():
            ev_list = agent_result.get("evidence", [])
            if isinstance(ev_list, list):
                evidence.extend(ev_list)

        return {
            "mode": mode.value,
            "content": "\n".join(content_parts),
            "agents": agents,
            "evidence": evidence,
            "summary": summary,
        }

    def _handle_vision_mode(
        self,
        user_input: str,
        stock_data: Optional[dict],
        image_base64: Optional[str],
        image_mime_type: str,
    ) -> dict:
        """图表分析模式：上传图片 → 识别 → 反查行情 → 分析"""
        from backend.vision.vision_agent import analyze_image

        # 如果没有图片数据，返回提示
        if not image_base64:
            return {
                "mode": "vision",
                "content": "请上传一张K线图或股票截图，我将为您进行图表分析。",
                "needs_more_info": True,
                "missing_info": ["image"],
            }

        # 如果用户提供了 ticker 信息，注入到 user_context
        user_context = user_input or ""
        if stock_data and stock_data.get("symbol"):
            user_context += f"\n股票代码: {stock_data['symbol']}"
            if stock_data.get("name"):
                user_context += f" ({stock_data['name']})"

        result = analyze_image(
            image_base64=image_base64,
            mime_type=image_mime_type,
            user_context=user_context,
        )

        # 构建响应
        content_parts = []
        if result.summary:
            content_parts.append(result.summary)
        if result.disclaimer:
            content_parts.append(f"\n{result.disclaimer}")

        response = {
            "mode": "vision",
            "content": "\n".join(content_parts) if content_parts else "无法分析此图片。",
            "needs_more_info": result.needs_more_info,
            "missing_info": result.missing_info or [],
        }

        # 附加结构化数据
        if result.detection:
            response["chart_type"] = result.detection.chart_type
            response["ticker"] = result.detection.ticker
        if result.kline_analysis:
            response["kline_analysis"] = {
                "trend": result.kline_analysis.trend,
                "support_levels": result.kline_analysis.support_levels,
                "resistance_levels": result.kline_analysis.resistance_levels,
                "patterns": result.kline_analysis.patterns,
                "summary": result.kline_analysis.summary,
            }
        if result.real_data and result.real_data.data_available:
            response["real_data"] = {
                "real_trend": result.real_data.real_trend,
                "trend_consistent": result.real_data.trend_consistent,
                "latest_close": result.real_data.latest_close,
                "conflicts": result.real_data.conflicts,
            }

        return response

    def _handle_expert_mode(
        self,
        conversation_id: str,
        user_input: str,
        stock_data: Optional[dict],
        expert_team_id: Optional[str],
        conv: dict,
    ) -> dict:
        """专家团模式 - 委托给 expert_panel.run_team_roundtable"""
        if not stock_data:
            return {
                "mode": "expert",
                "content": "请先选择一只股票后再进行专家团分析。可以在左侧输入股票代码。",
            }

        (
            run_team_roundtable,
            load_experts_config_v2,
            load_default_team,
            ExpertTeamConfig,
        ) = _import_expert_panel()

        # 加载专家团
        teams = load_experts_config_v2()
        team = None
        if expert_team_id:
            for t in teams:
                if t.id == expert_team_id:
                    team = t
                    break
        if team is None:
            team = teams[0] if teams else load_default_team()

        # 构建 stock_brief
        _, build_market_brief, _ = _import_llm_agents()

        enhanced_data = dict(stock_data)
        if user_input:
            enhanced_data["user_question"] = user_input

        stock_brief = build_market_brief(enhanced_data)
        if user_input:
            stock_brief = f"【用户特别关注】\n{user_input}\n\n{stock_brief}"

        stock_name = stock_data.get("name", conv.get("stock_name", ""))

        # 运行专家团
        result = run_team_roundtable(team, stock_brief, stock_name, None)

        # 格式化输出
        opinions = result.get("opinions", {})
        summary = result.get("summary", {})

        content_parts = [f"## {team.display_name} 分析结果\n"]

        # 专家观点
        for expert_key, opinion in opinions.items():
            action = getattr(opinion, "action", "观望")
            position = getattr(opinion, "position", 0)
            view = getattr(opinion, "view", "")[:200]
            confidence = getattr(opinion, "confidence", 0)
            expert_name = getattr(opinion, "expert_name", expert_key)

            content_parts.append(f"### {expert_name}")
            content_parts.append(f"- **操作建议**: {action} | 仓位: {position}% | 置信度: {confidence}%")
            content_parts.append(f"- **观点**: {view}")
            content_parts.append("")

        # 汇总
        buy = summary.get("buy", 0)
        hold = summary.get("hold", 0)
        reduce = summary.get("reduce", 0)
        sell = summary.get("sell", 0)
        avg_pos = summary.get("avg_position", 0)
        content_parts.append(f"**投票汇总**: 买入 {buy} / 观望 {hold} / 减持 {reduce} / 卖出 {sell}")
        content_parts.append(f"**平均建议仓位**: {avg_pos:.0f}%")

        # 收集证据
        evidence = []
        for opinion in opinions.values():
            ev_list = getattr(opinion, "evidence", [])
            if isinstance(ev_list, list):
                evidence.extend(ev_list)

        return {
            "mode": "expert",
            "content": "\n".join(content_parts),
            "opinions": {
                k: {
                    "expert_name": getattr(v, "expert_name", k),
                    "action": getattr(v, "action", ""),
                    "position": getattr(v, "position", 0),
                    "confidence": getattr(v, "confidence", 0),
                    "view": getattr(v, "view", ""),
                    "stop_loss": getattr(v, "stop_loss", ""),
                    "invalid_if": getattr(v, "invalid_if", ""),
                }
                for k, v in opinions.items()
            },
            "evidence": evidence,
            "summary": summary,
            "team_name": team.display_name,
        }

    def load_conversation(self, conversation_id: str) -> dict:
        """加载完整对话用于显示"""
        conv = self._store.get_conversation(conversation_id)
        if not conv:
            return {}
        messages = self._store.get_messages(conversation_id)
        return {"conversation": conv, "messages": messages}

    def list_conversations(self, stock_symbol: Optional[str] = None, limit: int = 50) -> List[dict]:
        """列出最近对话"""
        return self._store.list_conversations(stock_symbol=stock_symbol, limit=limit)

    def delete_conversation(self, conversation_id: str) -> None:
        """删除对话"""
        self._chat_sessions.pop(conversation_id, None)
        self._store.delete_conversation(conversation_id)

    def export_conversation(self, conversation_id: str) -> str:
        """导出对话为 Markdown 报告"""
        data = self.load_conversation(conversation_id)
        if not data:
            return "对话不存在"
        return generate_report(data["conversation"], data["messages"])

    def get_available_teams(self) -> List[dict]:
        """获取可用的专家团列表"""
        try:
            _, load_experts_config_v2, _, _ = _import_expert_panel()
            teams = load_experts_config_v2()
            return [
                {
                    "id": t.id,
                    "name": t.display_name,
                    "name_en": t.display_name_en,
                    "description": t.description,
                    "member_count": len(t.members),
                }
                for t in teams
            ]
        except Exception as e:
            logger.warning("加载专家团列表失败: %s", e)
            return []
