"""
Research Task Templates: 10 种研究任务模板。

职责：
- 预定义研究任务类型
- 每种模板包含系统提示、分析流程、输出格式
- 供 ChatOrchestrator 和 UI 调用
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field


@dataclass
class TaskTemplate:
    """研究任务模板"""

    id: str
    name: str
    description: str
    icon: str = "📋"
    mode: str = "deep"  # free/standard/deep/expert
    requires_stock: bool = True
    system_prompt: str = ""
    output_format: str = ""
    steps: List[str] = field(default_factory=list)


# ============== 10 种研究任务模板 ==============

TEMPLATES: Dict[str, TaskTemplate] = {
    "quick_diagnosis": TaskTemplate(
        id="quick_diagnosis",
        name="个股快速诊断",
        description="快速扫描个股基本面、技术面、资金面，给出买卖建议",
        icon="🔍",
        mode="standard",
        requires_stock=True,
        system_prompt="你是一位快速股票诊断专家。基于提供的数据，在3分钟内给出清晰的买入/卖出/观望建议。",
        output_format="明确结论 + 详细依据(3-5点,引用具体数据) + 风险提示(2-3点) + 置信度",
        steps=["拉取行情数据", "查看技术指标", "检查资金流向", "给出诊断结论"],
    ),
    "deep_research": TaskTemplate(
        id="deep_research",
        name="个股深度研究",
        description="全面深入分析个股，包含5 Agent + Critic + Chairman完整流程",
        icon="🔬",
        mode="deep",
        requires_stock=True,
        system_prompt="你是投资研究团队主席。协调5位分析师完成深度研究报告。",
        output_format="主席总结 + 各Agent观点 + 证据链 + 风险矩阵 + 操作建议",
        steps=[
            "基本面分析",
            "技术面分析",
            "舆情分析",
            "风控评估",
            "散户行为分析",
            "Critic审稿",
            "主席总结",
        ],
    ),
    "kline_analysis": TaskTemplate(
        id="kline_analysis",
        name="K线截图分析",
        description="上传K线图，AI识别形态并结合真实行情数据验证",
        icon="📊",
        mode="vision",
        requires_stock=False,
        system_prompt="你是一位K线形态识别专家。分析截图中的技术形态，结合真实行情数据给出判断。",
        output_format="图形识别 + 趋势判断 + 支撑压力位 + 量价分析 + 风险提示",
        steps=["图表类型检测", "K线形态识别", "真实行情交叉验证", "综合判断"],
    ),
    "financial_report": TaskTemplate(
        id="financial_report",
        name="财报解读",
        description="深度解读公司财务报表，评估盈利质量和估值水平",
        icon="📈",
        mode="deep",
        requires_stock=True,
        system_prompt="你是一位资深财务分析师。从盈利能力、成长性、财务健康度、估值水平四个维度解读财报。",
        output_format="财务评分(0-100) + 核心指标解读 + 同行对比 + 估值判断",
        steps=["盈利能力分析", "成长性分析", "资产负债分析", "现金流分析", "估值评估"],
    ),
    "research_summary": TaskTemplate(
        id="research_summary",
        name="研报摘要",
        description="汇总近期机构研报观点，提取共识和分歧",
        icon="📑",
        mode="standard",
        requires_stock=True,
        system_prompt="你是研报分析师。汇总多家机构研报观点，识别共识和分歧。",
        output_format="机构共识 + 主要分歧 + 目标价区间 + 评级分布",
        steps=["收集研报", "提取观点", "识别共识", "分析分歧"],
    ),
    "industry_scan": TaskTemplate(
        id="industry_scan",
        name="行业机会扫描",
        description="扫描特定行业的投资机会和风险",
        icon="🏭",
        mode="expert",
        requires_stock=False,
        system_prompt="你是行业研究专家。扫描目标行业的投资机会、竞争格局、政策影响。",
        output_format="行业景气度 + 竞争格局 + 政策影响 + 机会标的 + 风险提示",
        steps=["行业数据分析", "政策环境评估", "竞争格局分析", "投资机会识别"],
    ),
    "theme_tracking": TaskTemplate(
        id="theme_tracking",
        name="热点题材追踪",
        description="追踪当前市场热点题材和概念板块",
        icon="🔥",
        mode="standard",
        requires_stock=False,
        system_prompt="你是市场题材分析师。追踪当前热门概念板块，分析持续性和参与价值。",
        output_format="题材热度 + 核心标的 + 持续性评估 + 参与建议",
        steps=["热点识别", "题材分析", "标的筛选", "风险评估"],
    ),
    "capital_flow_monitor": TaskTemplate(
        id="capital_flow_monitor",
        name="资金流异动监控",
        description="监控主力资金和散户资金的异常流动",
        icon="💰",
        mode="standard",
        requires_stock=True,
        system_prompt="你是资金流向分析师。监控主力/散户资金异常流动，识别机构动向。",
        output_format="资金流向 + 异动信号 + 主力意图推断 + 后续观察点",
        steps=["主力资金分析", "散户资金分析", "异动识别", "意图推断"],
    ),
    "daily_brief": TaskTemplate(
        id="daily_brief",
        name="自选股每日简报",
        description="生成自选股的每日综合简报",
        icon="📰",
        mode="standard",
        requires_stock=True,
        system_prompt="你是每日市场简报编辑。为自选股生成简洁的每日综合简报。",
        output_format="行情概况 + 重要新闻 + 资金动向 + 技术信号 + 操作提示",
        steps=["行情汇总", "新闻筛选", "资金分析", "技术信号", "简报生成"],
    ),
    "expert_roundtable": TaskTemplate(
        id="expert_roundtable",
        name="专家团圆桌",
        description="多投资流派专家圆桌讨论，多角度分析",
        icon="🎓",
        mode="expert",
        requires_stock=True,
        system_prompt="你是专家团主持人。协调多位投资流派专家进行圆桌讨论。",
        output_format="各专家观点 + 投票汇总 + 核心分歧 + 综合建议",
        steps=["各专家独立分析", "观点汇总", "辩论/审查", "主席综合"],
    ),
}


def get_template(template_id: str) -> Optional[TaskTemplate]:
    """获取指定模板"""
    return TEMPLATES.get(template_id)


def list_templates() -> List[Dict[str, Any]]:
    """列出所有模板（供 UI 使用）"""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "icon": t.icon,
            "mode": t.mode,
            "requires_stock": t.requires_stock,
        }
        for t in TEMPLATES.values()
    ]


def get_template_prompt(
    template_id: str, stock_name: str = "", user_input: str = ""
) -> str:
    """生成基于模板的完整 prompt"""
    t = TEMPLATES.get(template_id)
    if not t:
        return user_input

    parts = []
    if t.system_prompt:
        parts.append(f"【任务】{t.system_prompt}")
    if stock_name:
        parts.append(f"【标的】{stock_name}")
    if t.output_format:
        parts.append(f"【输出格式】{t.output_format}")
    if t.steps:
        parts.append(f"【分析步骤】{' → '.join(t.steps)}")
    if user_input:
        parts.append(f"【用户补充】{user_input}")

    return "\n\n".join(parts)
