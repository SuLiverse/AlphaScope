"""合规与风险提示层

为投资分析输出添加风险提示、免责声明和脱敏处理。
v0.67: 扩展禁用词、风险级别免责声明、高风险输出标记。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

INVESTMENT_DISCLAIMER = """
---
**风险提示**: 以上分析仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。
AI 分析基于历史数据和模型推断，可能存在偏差。请结合自身情况独立判断。
数据来源: 公开市场数据，分析日期: {date}
"""

# 评级专属免责: 评级徽章/评分输出处强制附带, 明确「确定性度量 ≠ 投资建议」。
RATING_DISCLAIMER = "评级由多 Agent 投票与置信度确定性计算得出，仅为研究辅助，不构成投资建议。"

# 风险级别免责声明
_RISK_DISCLAIMERS = {
    "low": """
---
**风险提示**: 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。
数据来源: 公开市场数据，分析日期: {date}
""",
    "medium": """
---
**风险提示**: 以上分析仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。
AI 分析基于历史数据和模型推断，可能存在偏差。请结合自身情况独立判断。
数据来源: 公开市场数据，分析日期: {date}
""",
    "high": """
---
**⚠️ 高风险提示**: 以上分析涉及高风险判断，仅供参考，不构成任何投资建议。
AI 模型对极端行情的判断可能存在较大偏差。强烈建议结合多维度信息独立判断。
投资有风险，入市需谨慎。请勿将本分析作为唯一决策依据。
数据来源: 公开市场数据，分析日期: {date}
""",
    "critical": """
---
**🚨 极高风险警告**: 以上分析涉及极高风险操作，仅供参考，不构成任何投资建议。
AI 模型的极端判断可能与实际情况存在重大偏差。本分析不应作为投资决策的依据。
任何投资决策请咨询持牌专业人士。投资有风险，入市需谨慎。
数据来源: 公开市场数据，分析日期: {date}
""",
}

# 市场特定补充
_MARKET_NOTES = {
    "HK": "\n港股市场无涨跌幅限制，风险高于A股，请充分了解港股交易规则。",
    "US": "\n美股市场交易规则与A股不同，请注意时差、汇率及做空机制等风险。",
    "CN": "",
}

# 需要免责声明的分析模式
_DISCLAIMER_MODES = {"standard", "deep", "expert"}

# 金融禁用词 — 分 5 类，30+ 词
# 1. 承诺收益类
_PROMISE_WORDS = [
    "必涨",
    "稳赚",
    "无风险",
    "保证收益",
    "一定涨",
    "包赚",
    "稳赚不赔",
    "零风险",
    "保本保息",
    "躺赚",
    "暴富",
]
# 2. 内幕信息类
_INSIDER_WORDS = [
    "内幕消息",
    "庄家操盘",
    "主力拉升",
    "机构抱团必涨",
    "操盘计划",
    "涨停密码",
    "必涨代码",
]
# 3. 市场操纵类
_MANIPULATION_WORDS = [
    "割韭菜",
    "割散户",
    "洗盘结束必涨",
    "打压吸筹",
    "主力建仓",
    "底部放量必涨",
]
# 4. 极端仓位类
_POSITION_WORDS = [
    "满仓",
    "全仓买入",
    "all in",
    "梭哈",
    "借钱炒股",
    "贷款炒股",
    "融资满仓",
]
# 5. 非法荐股类
_RECOMMEND_WORDS = [
    "确定买入",
    "立即买入",
    "马上买入",
    "闭眼买入",
    "无脑买入",
    "老师带单",
    "跟单操作",
]

# 合并所有禁用词
FORBIDDEN_WORDS = _PROMISE_WORDS + _INSIDER_WORDS + _MANIPULATION_WORDS + _POSITION_WORDS + _RECOMMEND_WORDS

# 禁用词正则模式
_FORBIDDEN_PATTERNS = [
    re.compile(r"保[证证][\d]+[%％]以上收益"),
    re.compile(r"年化[\d]+[%％]以上.*保[证证]"),
    re.compile(r"[一1]周[翻番赚].*[倍翻番]"),
    re.compile(r"不[会赔亏].*只[会赚涨]"),
]

# 替代表达
REPLACEMENTS = {
    "必涨": "倾向上涨",
    "稳赚": "有盈利潜力",
    "无风险": "风险较低",
    "保证收益": "预期收益",
    "满仓": "适当仓位",
    "确定买入": "考虑买入",
    "一定涨": "可能上涨",
    "包赚": "有获利空间",
    "稳赚不赔": "有盈利潜力",
    "零风险": "风险较低",
    "保本保息": "预期收益",
    "躺赚": "有盈利空间",
    "暴富": "有增长潜力",
    "内幕消息": "市场传闻",
    "庄家操盘": "资金动向",
    "主力拉升": "资金流入",
    "割韭菜": "市场波动",
    "梭哈": "重仓",
    "全仓买入": "适当仓位",
    "闭眼买入": "考虑买入",
    "立即买入": "考虑买入",
    "马上买入": "考虑买入",
    "无脑买入": "考虑买入",
}

# API key 模式（用于脱敏）
_API_KEY_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),  # OpenAI-style
    re.compile(r"(AKIA[A-Z0-9]{16})"),  # AWS-style
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})", re.IGNORECASE),
]


def needs_disclaimer(mode: str) -> bool:
    """判断分析模式是否需要免责声明"""
    return mode in _DISCLAIMER_MODES


def wrap_with_disclaimer(content: str, mode: str, risk_level: str = "medium", market: str = "CN") -> str:
    """追加免责声明（幂等，不重复追加）"""
    if not needs_disclaimer(mode):
        return content
    if "风险提示" in content[-300:] or "风险警告" in content[-300:]:
        return content
    return content + get_disclaimer(risk_level, market)


def sanitize_output(content: str) -> str:
    """移除输出中可能泄露的 API key"""
    result = content
    for pattern in _API_KEY_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def check_forbidden_words(content: str) -> tuple[str, list[str]]:
    """检查并替换金融禁用词（文字 + 正则）。

    Returns:
        (替换后的内容, 检测到的禁用词列表)
    """
    found = []
    result = content

    # 文字匹配
    for word in FORBIDDEN_WORDS:
        if word in result:
            found.append(word)
            replacement = REPLACEMENTS.get(word, "****")
            result = result.replace(word, replacement)
            logger.warning("合规: 检测到禁用词 '%s'，已替换为 '%s'", word, replacement)

    # 正则模式匹配
    for pattern in _FORBIDDEN_PATTERNS:
        matches = pattern.findall(result)
        for m in matches:
            found.append(m)
            result = result.replace(m, "[不合规表述已移除]")
            logger.warning("合规: 检测到不合规表述 '%s'", m)

    return result, found


def get_disclaimer(risk_level: str = "medium", market: str = "CN") -> str:
    """获取风险级别对应的免责声明。"""
    template = _RISK_DISCLAIMERS.get(risk_level, _RISK_DISCLAIMERS["medium"])
    disclaimer = template.format(date=datetime.now().strftime("%Y-%m-%d"))
    market_note = _MARKET_NOTES.get(market, "")
    if market_note:
        disclaimer += market_note
    return disclaimer


def check_high_risk(output: dict) -> dict:
    """检测高风险输出，标记需要二次确认。

    高风险条件：
    - 信心度 >= 85 且信号为买入/卖出
    - 使用了极端仓位建议
    - 包含禁用词

    Returns:
        原始 output + high_risk / risk_warnings 字段
    """
    if not isinstance(output, dict):
        return output

    warnings = []
    risk_level = "medium"

    # 检查信心度 + 极端信号
    conf = output.get("confidence", 50)
    signal = output.get("signal", output.get("action", ""))
    try:
        conf = float(conf)
    except (ValueError, TypeError):
        conf = 50

    if conf >= 85 and signal in ("买入", "卖出", "buy", "sell"):
        warnings.append(f"高信心({conf:.0f}%)+极端信号({signal})，建议二次确认")
        risk_level = "high"

    if conf >= 95:
        warnings.append("信心度极高(≥95%)，AI 判断可能存在过度自信")
        risk_level = "critical"

    # 检查禁用词
    content = str(output.get("reason", "")) + str(output.get("view", ""))
    _, found = check_forbidden_words(content)
    if found:
        warnings.append(f"输出包含 {len(found)} 个不合规表述，已自动替换")
        risk_level = "high"

    output["high_risk"] = risk_level in ("high", "critical")
    output["risk_level"] = risk_level
    output["risk_warnings"] = warnings

    return output


def validate_analysis_output(data: dict) -> dict:
    """校验分析输出结构，确保包含必要的风险字段"""
    if not isinstance(data, dict):
        return data

    # 确保 signal 字段标准化
    signal = data.get("signal", data.get("action", ""))
    signal_map = {
        "买入": "buy",
        "卖出": "sell",
        "观望": "hold",
        "减持": "reduce",
        "增持": "increase",
        "buy": "buy",
        "sell": "sell",
        "hold": "hold",
        "reduce": "reduce",
    }
    if signal:
        data["signal"] = signal_map.get(signal, signal)

    # 确保 confidence 在合理范围
    conf = data.get("confidence", 50)
    try:
        conf = float(conf)
    except (ValueError, TypeError):
        conf = 50
    data["confidence"] = max(0, min(100, conf))

    # 确保 risks 是列表
    risks = data.get("risks", [])
    if isinstance(risks, str):
        data["risks"] = [risks]
    elif not isinstance(risks, list):
        data["risks"] = []

    # 确保 evidence 是列表
    evidence = data.get("evidence", [])
    if isinstance(evidence, str):
        data["evidence"] = [{"claim": evidence}]
    elif not isinstance(evidence, list):
        data["evidence"] = []

    return data
