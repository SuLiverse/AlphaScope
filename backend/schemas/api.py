"""API 请求/响应模型 - FastAPI 后端统一 schema"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ============================================================
# 通用响应结构
# ============================================================


class ApiResponse(BaseModel, Generic[T]):
    """统一 API 响应包装"""

    success: bool = Field(description="请求是否成功")
    data: Optional[T] = Field(default=None, description="响应数据")
    error: Optional[str] = Field(default=None, description="错误信息")
    message: Optional[str] = Field(default=None, description="提示信息")
    error_code: Optional[str] = Field(default=None, description="错误码")
    trace_id: Optional[str] = Field(default=None, description="请求追踪ID")
    source: Optional[str] = Field(default=None, description="数据来源")
    tool_call_id: Optional[str] = Field(default=None, description="工具调用ID")
    evidence_ids: Optional[list[str]] = Field(default=None, description="关联证据ID列表")


class PaginatedData(BaseModel, Generic[T]):
    """分页数据"""

    items: list[T] = Field(description="数据列表")
    total: int = Field(description="总条数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")


# ============================================================
# 请求模型
# ============================================================


class ChatRequest(BaseModel):
    """聊天请求"""

    conversation_id: Optional[str] = Field(default=None, description="会话ID，为空则创建新会话")
    message: str = Field(description="用户消息", max_length=10000)
    mode: str = Field(default="free", description="模式: free/standard/deep/expert/vision")
    stock_symbol: Optional[str] = Field(default=None, description="股票代码")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    expert_team_id: Optional[str] = Field(default=None, description="专家团ID")
    provider: Optional[str] = Field(default=None, description="模型 Provider ID")
    model: Optional[str] = Field(default=None, description="模型 ID")
    context: Optional[dict[str, Any]] = Field(default=None, description="前端注入的行情、资金和界面上下文")


class AnalysisRequest(BaseModel):
    """分析请求"""

    stock_symbol: str = Field(description="股票代码")
    stock_name: str = Field(default="", description="股票名称")
    mode: str = Field(default="deep", description="分析模式: standard/deep/auto")
    agent_configs: Optional[list[dict[str, Any]]] = Field(default=None, description="Agent 配置覆盖")
    global_ai_settings: Optional[dict[str, Any]] = Field(default=None, description="全局 AI 设置")


class VisionRequest(BaseModel):
    """图片分析请求"""

    image_base64: str = Field(description="图片 base64 编码")
    mime_type: str = Field(default="image/png", description="图片 MIME 类型")
    user_context: str = Field(default="", description="用户上下文说明")
    vendor: str = Field(default="deepseek", description="视觉模型供应商")
    model: str = Field(default="deepseek-chat", description="视觉模型名称")
    ticker: str = Field(default="", description="用户提供的股票代码（可选，跳过识别追问）")


class ConversationCreate(BaseModel):
    """创建会话请求"""

    title: str = Field(default="新对话", description="会话标题")
    stock_symbol: Optional[str] = Field(default=None, description="股票代码")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    mode: str = Field(default="free", description="默认模式")


# ============================================================
# 响应数据模型
# ============================================================


class HealthData(BaseModel):
    """健康检查数据"""

    status: str = Field(description="服务状态")
    version: str = Field(description="版本号")
    timestamp: datetime = Field(default_factory=datetime.now, description="检查时间")


class ConversationData(BaseModel):
    """会话数据"""

    id: str = Field(description="会话ID")
    title: str = Field(description="会话标题")
    stock_symbol: Optional[str] = Field(default=None, description="股票代码")
    stock_name: Optional[str] = Field(default=None, description="股票名称")
    mode: str = Field(default="free", description="模式")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    updated_at: Optional[str] = Field(default=None, description="更新时间")
    message_count: int = Field(default=0, description="消息数")


class MessageData(BaseModel):
    """消息数据"""

    id: Optional[int] = Field(default=None, description="消息ID")
    role: str = Field(description="角色: user/assistant/system")
    content: str = Field(description="消息内容")
    timestamp: Optional[str] = Field(default=None, description="时间戳")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="元数据")


class ChatResultData(BaseModel):
    """聊天结果数据"""

    conversation_id: str = Field(description="会话ID")
    mode: str = Field(description="使用的模式")
    content: str = Field(description="回复内容")
    agents: Optional[list[dict[str, Any]]] = Field(default=None, description="Agent 分析结果")
    evidence: Optional[list[dict[str, Any]]] = Field(default=None, description="证据链")
    summary: Optional[str] = Field(default=None, description="摘要")
    compliance_note: Optional[str] = Field(default=None, description="合规声明")
    detected_intent: Optional[str] = Field(default=None, description="检测到的意图")
    auto_routed: bool = Field(default=False, description="是否自动路由")


class AnalysisResultData(BaseModel):
    """分析结果数据"""

    stock_symbol: str = Field(description="股票代码")
    stock_name: str = Field(default="", description="股票名称")
    mode: str = Field(description="分析模式")
    result: dict[str, Any] = Field(description="分析结果")
    task_id: Optional[str] = Field(default=None, description="任务ID（异步）")


class KlineAnalysisData(BaseModel):
    """K线分析结构化数据"""

    trend: str = Field(default="", description="趋势: bullish/bearish/sideways")
    support_levels: list[float] = Field(default_factory=list, description="支撑位")
    resistance_levels: list[float] = Field(default_factory=list, description="阻力位")
    patterns: list[str] = Field(default_factory=list, description="K线形态")
    summary: str = Field(default="", description="技术分析摘要")


class RealDataComparison(BaseModel):
    """真实行情交叉验证结果"""

    real_trend: str = Field(default="", description="真实趋势")
    trend_consistent: bool = Field(default=False, description="视觉趋势与真实趋势是否一致")
    latest_close: float = Field(default=0.0, description="最新收盘价")
    conflicts: list[str] = Field(default_factory=list, description="冲突点")


class VisionResultData(BaseModel):
    """视觉分析结果数据"""

    chart_type: Optional[str] = Field(default=None, description="识别的图表类型")
    ticker: Optional[str] = Field(default=None, description="识别的股票代码")
    analysis: str = Field(description="分析内容")
    needs_followup: bool = Field(default=False, description="是否需要追问")
    followup_question: Optional[str] = Field(default=None, description="追问内容")
    kline_analysis: Optional[KlineAnalysisData] = Field(default=None, description="K线分析结构化数据")
    real_data: Optional[RealDataComparison] = Field(default=None, description="真实行情交叉验证")


class AgentData(BaseModel):
    """Agent 配置数据"""

    name: str = Field(description="Agent 名称")
    role: str = Field(description="角色")
    model: str = Field(default="", description="使用的模型")
    description: str = Field(default="", description="描述")


class TeamData(BaseModel):
    """专家团数据"""

    id: str = Field(description="团队ID")
    name: str = Field(description="团队名称")
    description: str = Field(default="", description="描述")
    members: list[dict[str, Any]] = Field(default_factory=list, description="成员列表")


class ModelProviderData(BaseModel):
    """模型供应商数据"""

    id: str = Field(description="供应商ID")
    name: str = Field(description="供应商名称")
    base_url: str = Field(default="", description="API 基础URL")
    models: list[str] = Field(default_factory=list, description="可用模型列表")


class ReportData(BaseModel):
    """报告数据"""

    id: str = Field(description="报告ID")
    title: str = Field(description="报告标题")
    content: str = Field(description="报告内容（Markdown）")
    conversation_id: Optional[str] = Field(default=None, description="关联会话ID")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class TemplateData(BaseModel):
    """研究模板数据"""

    id: str = Field(description="模板ID")
    name: str = Field(description="模板名称")
    description: str = Field(default="", description="描述")
    prompt: str = Field(default="", description="模板提示词")
    category: str = Field(default="general", description="分类")


class CostData(BaseModel):
    """成本统计数据"""

    total_cost: float = Field(default=0.0, description="总成本")
    by_mode: dict[str, float] = Field(default_factory=dict, description="按模式分组")
    by_model: dict[str, float] = Field(default_factory=dict, description="按模型分组")
    request_count: int = Field(default=0, description="请求次数")


class BacktestStatsData(BaseModel):
    """回测统计数据"""

    total_signals: int = Field(default=0, description="总信号数")
    evaluated: int = Field(default=0, description="已评估数")
    accuracy: float = Field(default=0.0, description="准确率")
    by_mode: dict[str, Any] = Field(default_factory=dict, description="按模式分组")


class ModeData(BaseModel):
    """分析模式数据"""

    id: str = Field(description="模式ID")
    name: str = Field(description="模式名称")
    description: str = Field(default="", description="描述")
    agents: int = Field(default=1, description="Agent 数量")
    estimated_cost: str = Field(default="", description="预估成本")


class AuditLogData(BaseModel):
    """审计日志数据"""

    id: Optional[int] = Field(default=None, description="日志ID")
    action: str = Field(description="操作")
    target_type: str = Field(default="", description="目标类型")
    target_id: str = Field(default="", description="目标ID")
    metadata: Optional[dict[str, Any]] = Field(default=None, description="元数据")
    created_at: Optional[str] = Field(default=None, description="创建时间")


class SearchData(BaseModel):
    """搜索结果数据"""

    query: str = Field(description="搜索词")
    results: list[dict[str, Any]] = Field(default_factory=list, description="搜索结果")
    source: str = Field(default="", description="数据来源")


class FileUploadData(BaseModel):
    """文件上传结果数据"""

    filename: str = Field(description="文件名")
    size: int = Field(description="文件大小（字节）")
    path: str = Field(default="", description="保存路径")
    message: str = Field(default="上传成功", description="提示信息")


# ============================================================
# 量化回测 (v1.1.1)
# ============================================================


class StrategyData(BaseModel):
    """策略定义"""

    name: str = Field(description="策略名称")
    description: str = Field(default="", description="策略描述")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数")


class BacktestRunRequest(BaseModel):
    """回测运行请求"""

    strategy_name: str = Field(description="策略名称")
    symbol: str = Field(description="股票代码")
    days: int = Field(default=120, ge=10, le=1000, description="回测天数")
    initial_capital: float = Field(default=100000.0, gt=0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")
    benchmark_symbol: str = Field(default="", description="可选基准代码(如沪深300 sh000300), 用于超额/信息比率")


class TradeRecord(BaseModel):
    """交易记录"""

    symbol: str
    side: str
    shares: int
    price: float
    commission: float
    pnl: float
    timestamp: str


class PerformanceMetrics(BaseModel):
    """绩效指标"""

    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    initial_capital: float
    final_equity: float
    trading_days: int


class BacktestResultData(BaseModel):
    """回测结果"""

    strategy_name: str
    symbol: str
    params: dict[str, Any]
    equity_curve: list[float]
    dates: list[str]
    trades: list[dict[str, Any]]
    performance: dict[str, Any]
    risk_violations: list[dict[str, Any]]
