"""
Agent / 专家 LLM 输出 schema 校验与规范化(纯函数,无外部依赖)。

设计取舍:
- 不引入 pydantic,保持依赖最小化;
- 校验函数始终返回"已规范化的 dict"而不是抛异常,避免破坏现有 fallback 链路;
- 越界值夹断而非丢弃,缺失字段使用安全默认;
- 非法 evidence 条目过滤,保留合法部分。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


# ---------------- 通用工具 ----------------


def _clip(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    """把数值夹在 [lo, hi] 内,非法值返回 default。容忍 "75%" / " 30 " 这类字符串。"""
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip()
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:  # NaN
        return default
    return max(lo, min(hi, v))


def _safe_str(value: Any, max_len: int = 500, default: str = "") -> str:
    """转换为字符串并裁剪长度。"""
    if value is None:
        return default
    try:
        s = str(value).strip()
    except Exception:
        return default
    return s[:max_len] if s else default


def _safe_str_list(value: Any, max_items: int = 8, max_len: int = 200) -> List[str]:
    """把任意输入规范化为字符串列表。dict / 标量也尽量提取出可读文字。"""
    if not value:
        return []
    items: Iterable
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, str):
        # 允许模型返回换行分隔的多条
        parts = [p.strip(" -·•\t") for p in value.splitlines() if p.strip()]
        items = parts if parts else [value]
    else:
        items = [value]

    out: List[str] = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("claim") or item.get("text") or item.get("content") or ""
        else:
            text = item
        s = _safe_str(text, max_len=max_len)
        if s:
            out.append(s)
        if len(out) >= max_items:
            break
    return out


# ---------------- 公共枚举 ----------------

AGENT_SIGNALS = ("买入", "卖出", "观望")
EXPERT_ACTIONS = ("买入", "卖出", "观望", "减持")

# 证据类型白名单(模型乱写时统一收敛到 "other")
EVIDENCE_TYPES = {
    "fund_flow",  # 资金流向
    "technical",  # 量价/指标
    "fundamental",  # 财报/估值
    "news",  # 新闻/公告
    "research",  # 研报/评级
    "macro",  # 宏观/行业
    "sentiment",  # 情绪/换手
    "shareholder",  # 股东/持仓变动
    "other",
}


def _normalize_evidence(value: Any, max_items: int = 6) -> List[Dict[str, str]]:
    """规范化证据链,只保留 type/claim/data_date 三个字段。

    模型可能直接给字符串列表(例如 ["主力近5日净流入2.3亿", ...])或多行字符串
    (例如 "1. MA20 上行\\n2. 成交量放大"),都尝试容错。
    """
    if not value:
        return []
    if isinstance(value, dict):
        value = [value]
    elif isinstance(value, str):
        # 单条字符串或多行字符串,切成 list 走统一路径
        parts = [p.strip(" -·•\t") for p in value.splitlines() if p.strip()]
        value = parts if parts else [value]
    if not isinstance(value, (list, tuple)):
        return []

    out: List[Dict[str, str]] = []
    for raw in value:
        if isinstance(raw, dict):
            etype = _safe_str(raw.get("type"), max_len=24).lower()
            claim = _safe_str(
                raw.get("claim") or raw.get("text") or raw.get("content"), max_len=400
            )
            data_date = _safe_str(raw.get("data_date") or raw.get("date"), max_len=16)
        else:
            etype = ""
            claim = _safe_str(raw, max_len=400)
            data_date = ""
        if not claim:
            continue
        if etype not in EVIDENCE_TYPES:
            etype = "other"
        out.append({"type": etype, "claim": claim, "data_date": data_date})
        if len(out) >= max_items:
            break
    return out


# ---------------- Agent 输出 ----------------


def validate_agent_output(data: Any) -> Dict[str, Any]:
    """规范化 5 Agent / 自定义 Agent 的 JSON 输出。

    - 强制字段: signal / confidence / reason
    - 可选字段: evidence / invalid_if / risks
    - 越界值夹断、非法值降级到安全默认,永远不抛异常
    """
    if not isinstance(data, dict):
        data = {}

    signal = _safe_str(data.get("signal"), max_len=8)
    if signal not in AGENT_SIGNALS:
        # 兼容 "建议买入" / "Buy" / "看多" 等说法
        for s in AGENT_SIGNALS:
            if s in signal:
                signal = s
                break
        else:
            lowered = signal.lower()
            if any(k in lowered for k in ("buy", "long", "bull", "看多", "增持")):
                signal = "买入"
            elif any(k in lowered for k in ("sell", "short", "bear", "看空", "减持")):
                signal = "卖出"
            else:
                signal = "观望"

    confidence = int(_clip(data.get("confidence"), 0, 100, default=50))
    reason = _safe_str(data.get("reason"), max_len=4000, default="无明确观点")

    evidence = _normalize_evidence(data.get("evidence"), max_items=8)
    invalid_if = _safe_str(data.get("invalid_if"), max_len=400)
    risks = _safe_str_list(data.get("risks"), max_items=5, max_len=300)

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence,
        "invalid_if": invalid_if,
        "risks": risks,
    }


# ---------------- 专家输出 ----------------


def validate_expert_output(data: Any) -> Dict[str, Any]:
    """规范化专家圆桌 JSON 输出。

    - 强制字段: view / action / position / stop_loss
    - 可选字段: evidence(原 evidence 字段) / invalid_if / risks
    - 兼容现有专家 prompt:evidence 若是字符串列表,会被 ``_normalize_evidence`` 兜底转换。
    """
    if not isinstance(data, dict):
        data = {}

    view = _safe_str(data.get("view"), max_len=4000, default="无明确观点")

    action = _safe_str(data.get("action"), max_len=8)
    if action not in EXPERT_ACTIONS:
        for a in EXPERT_ACTIONS:
            if a in action:
                action = a
                break
        else:
            action = "观望"

    position = int(_clip(data.get("position"), 0, 100, default=0))

    try:
        stop_loss_raw = data.get("stop_loss")
        stop_loss = float(stop_loss_raw) if stop_loss_raw not in (None, "") else 0.0
        if stop_loss != stop_loss or stop_loss < 0:  # NaN / 负数
            stop_loss = 0.0
    except (TypeError, ValueError):
        stop_loss = 0.0

    evidence = _normalize_evidence(data.get("evidence"), max_items=8)
    invalid_if = _safe_str(data.get("invalid_if"), max_len=400)
    risks = _safe_str_list(data.get("risks"), max_items=5, max_len=300)

    return {
        "view": view,
        "action": action,
        "position": position,
        "stop_loss": stop_loss,
        "evidence": evidence,
        "invalid_if": invalid_if,
        "risks": risks,
    }


# ---------------- Prompt Injection Protection (v0.12) ----------------

import re as _re

# Stock code whitelist: 6-digit A-share codes
_STOCK_CODE_PATTERN = _re.compile(r"^[036]\d{5}$")

# Characters that might indicate prompt injection attempts
_INJECTION_PATTERNS = [
    _re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"),
    _re.compile(r"(?i)ignore\s+(all\s+)?above"),
    _re.compile(r"(?i)you\s+are\s+now\s+"),
    _re.compile(r"(?i)new\s+instructions?\s*:"),
    _re.compile(r"(?i)system\s*prompt\s*:"),
    _re.compile(r"(?i)\[INST\]|\[/INST\]"),
    _re.compile(r"(?i)<\|im_start\|>|<\|im_end\|>"),
    _re.compile(r"(?i)jailbreak"),
    _re.compile(r"(?i)DAN\s*mode"),
]


def validate_stock_code(code: str) -> str:
    """
    Validate and sanitize a stock code.

    Args:
        code: Raw stock code input

    Returns:
        Cleaned 6-digit code, or empty string if invalid
    """
    if not code:
        return ""
    cleaned = str(code).strip().replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    # Remove any non-digit characters
    cleaned = _re.sub(r"\D", "", cleaned)
    if _STOCK_CODE_PATTERN.match(cleaned):
        return cleaned
    return ""


def sanitize_prompt_input(text: str, max_len: int = 500) -> str:
    """
    Sanitize user input before inserting into LLM prompts.

    Removes potential prompt injection patterns and limits length.

    Args:
        text: Raw user input
        max_len: Maximum allowed length

    Returns:
        Sanitized text safe for prompt insertion
    """
    if not text:
        return ""
    cleaned = str(text).strip()[:max_len]

    # Remove zero-width characters (can be used to hide injection)
    cleaned = _re.sub(r"[​-‏ - ⁠-⁩﻿]", "", cleaned)

    # Remove common injection patterns
    for pattern in _INJECTION_PATTERNS:
        cleaned = pattern.sub("[FILTERED]", cleaned)

    return cleaned


def sanitize_stock_data_for_prompt(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize stock data dict before using in LLM prompts.

    Validates stock code and sanitizes text fields.
    """
    sanitized = dict(stock_data)

    # Validate stock code
    if "symbol" in sanitized:
        clean_code = validate_stock_code(sanitized["symbol"])
        if clean_code:
            sanitized["symbol"] = clean_code

    # Sanitize text fields that might be user-provided
    text_fields = [
        "name",
        "fundamentals",
        "related_news_brief",
        "announcements_brief",
        "industry_news_brief",
        "concepts_brief",
        "market_news_brief",
        "research_brief",
    ]
    for field in text_fields:
        if field in sanitized and isinstance(sanitized[field], str):
            sanitized[field] = sanitize_prompt_input(sanitized[field], max_len=2000)

    return sanitized


if __name__ == "__main__":
    # 自测
    samples = [
        {
            "signal": "买入",
            "confidence": 200,
            "reason": "x",
            "evidence": [{"type": "fund_flow", "claim": "主力净流入"}],
        },
        {"signal": "long", "confidence": -5, "reason": ""},
        {"signal": None, "evidence": "1. MA20 上行\n2. 成交量放大"},
    ]
    for s in samples:
        print(validate_agent_output(s))

    print("---")
    print(
        validate_expert_output(
            {
                "view": "短期超买",
                "action": "建议减持",
                "position": "30%",
                "stop_loss": "1500.5",
                "evidence": ["RSI > 80", {"type": "technical", "claim": "周线高位"}],
                "invalid_if": "放量突破压力位",
            }
        )
    )
