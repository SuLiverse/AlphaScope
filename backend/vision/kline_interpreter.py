"""
K-Line Interpreter: K线图解读与结构化分析。

职责：
- 从视觉模型获取K线图的详细解读
- 提取支撑位、压力位、趋势判断
- 结合真实行情数据交叉验证
"""

from dataclasses import dataclass, field

from backend.models.provider_gateway import _call_with, _extract_json


@dataclass
class KlineAnalysis:
    """K线图分析结果"""

    trend: str = ""  # 上升/下降/震荡
    support_levels: list = field(default_factory=list)
    resistance_levels: list = field(default_factory=list)
    patterns: list = field(default_factory=list)  # 识别到的形态
    indicators: dict = field(default_factory=dict)  # 可见指标
    volume_analysis: str = ""
    summary: str = ""
    confidence: float = 0.0
    raw_response: str = ""


def interpret_kline(
    image_base64: str,
    mime_type: str = "image/png",
    context: str = "",
    vendor: str = "deepseek",
    model: str = "deepseek-chat",
) -> KlineAnalysis:
    """
    解读K线图，提取技术分析信息。

    Args:
        image_base64: 图片 base64
        mime_type: MIME 类型
        context: 额外上下文（如标的代码、周期等）
        vendor: LLM 供应商
        model: 模型名称

    Returns:
        KlineAnalysis 结构化分析结果
    """
    context_note = f"\n已知信息：{context}" if context else ""

    messages = [
        {
            "role": "system",
            "content": "你是一位顶级技术分析师，精通K线形态识别、支撑压力位判断、趋势分析。",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
                },
                {
                    "type": "text",
                    "text": f"""请详细分析这张K线图，用 JSON 返回：
{{
  "trend": "上升/下降/震荡",
  "support_levels": ["支撑位1", "支撑位2"],
  "resistance_levels": ["压力位1", "压力位2"],
  "patterns": ["识别到的形态1", "形态2"],
  "indicators": {{"ma": "描述", "macd": "描述", "rsi": "描述", "volume": "描述"}},
  "volume_analysis": "成交量分析",
  "summary": "300字以上综合判断(趋势结构、关键支撑压力、量价配合、风险与操作提示)",
  "confidence": 0.0-1.0
}}
{context_note}

注意：这是初步图形观察，需要结合真实行情数据验证。只返回 JSON。""",
                },
            ],
        },
    ]

    try:
        text = _call_with(vendor, model, messages, max_tokens=1536, temperature=0.2)
        data = _extract_json(text)
        return KlineAnalysis(
            trend=data.get("trend", ""),
            support_levels=data.get("support_levels", []),
            resistance_levels=data.get("resistance_levels", []),
            patterns=data.get("patterns", []),
            indicators=data.get("indicators", {}),
            volume_analysis=data.get("volume_analysis", ""),
            summary=data.get("summary", ""),
            confidence=float(data.get("confidence", 0)),
            raw_response=text,
        )
    except Exception as e:
        return KlineAnalysis(
            summary=f"K线解读失败: {e}",
            raw_response=str(e),
        )
