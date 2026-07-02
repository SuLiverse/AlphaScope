"""基金 API 端点 — 搜索、净值、指标、定投、组合管理"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from backend.funds.dca import DCASimulator
from backend.funds.metrics import calc_fund_metrics
from backend.funds.portfolio import PortfolioManager
from backend.funds.providers import get_provider
from backend.schemas.api import ApiResponse
from backend.schemas.funds import DCAFrequency

router = APIRouter(tags=["funds"])

# 组合管理器（可被覆盖）
_portfolio_mgr: Optional[PortfolioManager] = None

_LEGACY_FUNDS = [
    {
        "symbol": "110011",
        "code": "110011",
        "name": "易方达中小盘混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "张坤",
        "size_yi": 67.5,
    },
    {
        "symbol": "161725",
        "code": "161725",
        "name": "招商中证白酒指数",
        "type": "指数型",
        "risk": "R4",
        "manager": "侯昊",
        "size_yi": 120.3,
    },
    {
        "symbol": "005827",
        "code": "005827",
        "name": "易方达蓝筹精选混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "张坤",
        "size_yi": 89.2,
    },
    {
        "symbol": "003834",
        "code": "003834",
        "name": "华夏能源革新股票",
        "type": "股票型",
        "risk": "R4",
        "manager": "郑泽鸿",
        "size_yi": 45.8,
    },
    {
        "symbol": "001938",
        "code": "001938",
        "name": "中欧时代先锋股票",
        "type": "股票型",
        "risk": "R4",
        "manager": "周应波",
        "size_yi": 32.1,
    },
    {
        "symbol": "001549",
        "code": "001549",
        "name": "天弘永利债券",
        "type": "债券型",
        "risk": "R2",
        "manager": "姚文涛",
        "size_yi": 28.6,
    },
]


def _get_portfolio_mgr() -> PortfolioManager:
    global _portfolio_mgr
    if _portfolio_mgr is None:
        try:
            from backend.storage.db import Database

            _portfolio_mgr = PortfolioManager(db=Database())
        except Exception:
            _portfolio_mgr = PortfolioManager(db=None)
    return _portfolio_mgr


def set_portfolio_mgr(mgr: PortfolioManager):
    global _portfolio_mgr
    _portfolio_mgr = mgr


class _MetricNA:
    def __format__(self, spec: str) -> str:
        return "N/A"


class _ReportMetrics(dict[str, Any]):
    def get(self, key: str, default: Any = None) -> Any:
        value = super().get(key, default)
        return _MetricNA() if value is None else value


def _normalize_fund_search_item(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": str(info.get("code", "")).strip(),
        "name": str(info.get("name", "")).strip(),
        "fund_type": str(info.get("fund_type", "")).strip(),
        "company": str(info.get("company", info.get("manager", ""))).strip(),
    }


# ============================================================
# 请求模型
# ============================================================


class DCASimulateBody(BaseModel):
    """定投模拟请求"""

    fund_code: str = Field(default="", description="基金代码")
    symbol: str = Field(default="", description="兼容基金代码")
    amount: float = Field(default=0.0, description="每期金额")
    amount_per_period: float = Field(default=0.0, description="兼容每期金额")
    frequency: str = Field(
        default="monthly", description="频率: weekly/biweekly/monthly/quarterly"
    )
    start_date: str = Field(default="", description="开始日期 YYYY-MM-DD")
    end_date: str = Field(default="", description="结束日期 YYYY-MM-DD")
    periods: int = Field(default=36, description="兼容模拟期数")
    initial_price: float = Field(default=1.0, description="兼容初始价格")
    annual_growth_pct: float = Field(default=8.0, description="兼容年化增长率")
    volatility_pct: float = Field(default=15.0, description="兼容波动率")


class PortfolioCreateBody(BaseModel):
    """创建组合请求"""

    name: str = Field(description="组合名称")
    description: str = Field(default="", description="组合描述")
    holdings: list[dict[str, Any]] = Field(default_factory=list, description="持仓")


class PortfolioUpdateBody(BaseModel):
    """更新组合请求"""

    name: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)
    holdings: Optional[list[dict[str, Any]]] = Field(default=None)


# ============================================================
# 基金搜索与信息
# ============================================================


@router.get("/api/funds/search")
async def search_funds(
    request: Request,
    keyword: str = "",
    q: str = "",
    risk: str = "",
    fund_type: str = "",
    limit: int = Query(20, ge=1, le=200),
):
    """搜索基金"""
    if q or risk or fund_type:
        results = _LEGACY_FUNDS
        if q:
            q_lower = q.lower()
            results = [
                item
                for item in results
                if q_lower in item["name"].lower() or q_lower in item["symbol"]
            ]
        if risk:
            results = [item for item in results if item["risk"] == risk]
        if fund_type:
            results = [item for item in results if item["type"] == fund_type]
        return ApiResponse(success=True, data=results[:limit])

    keyword = keyword.strip()
    if not keyword:
        return ApiResponse(success=True, data={"funds": [], "total": 0})
    provider = get_provider()
    try:
        degraded = False
        source_status = "ok"
        funds: list[dict[str, Any]] = []
        seen_codes: set[str] = set()

        if keyword.isdigit() and len(keyword) == 6:
            try:
                info = await provider.get_info(keyword)
            except Exception:
                info = None
            if info:
                item = _normalize_fund_search_item(info)
                if item["code"]:
                    funds.append(item)
                    seen_codes.add(item["code"])
                    source_status = "code_lookup"

        try:
            search_results = await provider.search(keyword)
        except Exception as e:
            if funds:
                return ApiResponse(
                    success=True,
                    error=str(e),
                    error_code="FUND_SEARCH_DEGRADED",
                    data={
                        "funds": funds,
                        "total": len(funds),
                        "degraded": True,
                        "source": "fund_provider",
                        "source_status": "code_lookup_search_unavailable",
                    },
                )
            raise
        for item in search_results:
            code = str(item.get("code", "")).strip()
            if code and code in seen_codes:
                continue
            funds.append(item)
            if code:
                seen_codes.add(code)

        if keyword.isdigit() and len(keyword) == 6 and not funds:
            degraded = True
            source_status = "empty"

        return ApiResponse(
            success=True,
            data={
                "funds": funds,
                "total": len(funds),
                "degraded": degraded,
                "source": "fund_provider",
                "source_status": source_status,
            },
            error="No fund matched by code or keyword" if degraded else None,
            error_code="FUND_SEARCH_DEGRADED" if degraded else None,
        )
    except Exception as e:
        return ApiResponse(
            success=True,
            error=str(e),
            error_code="FUND_SEARCH_DEGRADED",
            data={
                "funds": [],
                "total": 0,
                "degraded": True,
                "source": "fund_provider",
                "source_status": "unavailable",
            },
        )


@router.get("/api/funds/detail/{code}")
async def get_legacy_fund_detail(code: str):
    """获取兼容基金详情"""
    fund = next((item for item in _LEGACY_FUNDS if item["symbol"] == code), None)
    if not fund:
        return ApiResponse(success=False, error=f"基金不存在: {code}")
    return ApiResponse(success=True, data=fund)


@router.get("/api/funds/{code}")
async def get_fund_info(code: str):
    """获取基金信息"""
    provider = get_provider()
    try:
        info = await provider.get_info(code)
        if not info:
            return ApiResponse(
                success=False,
                error=f"基金 {code} 不存在",
                error_code="FUND_NOT_FOUND",
            )
        return ApiResponse(success=True, data=info)
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/api/funds/{code}/nav")
async def get_fund_nav(
    code: str,
    start_date: str = "",
    end_date: str = "",
):
    """获取基金历史净值"""
    provider = get_provider()
    try:
        records = await provider.get_nav_history(code, start_date, end_date)
        return ApiResponse(
            success=True,
            data={
                "code": code,
                "navs": records,
                "total": len(records),
            },
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            data={"code": code, "navs": [], "total": 0},
        )


@router.get("/api/funds/{code}/metrics")
async def get_fund_metrics(code: str):
    """获取基金指标"""
    provider = get_provider()
    try:
        records = await provider.get_nav_history(code)
        if not records:
            return ApiResponse(
                success=False,
                error="无净值数据",
                error_code="FUND_NO_DATA",
            )
        navs = [r["nav"] for r in records]
        metrics = calc_fund_metrics(navs)
        metrics["code"] = code
        return ApiResponse(success=True, data=metrics)
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


# ============================================================
# 定投模拟
# ============================================================


def _legacy_dca_result(body: DCASimulateBody) -> dict[str, Any]:
    periods = max(int(body.periods or 1), 1)
    amount = float(body.amount_per_period or body.amount or 1000)
    total_invested = amount * periods
    growth = 1 + float(body.annual_growth_pct or 0) / 100
    final_value = total_invested * growth
    dca = {
        "total_invested": round(total_invested, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(
            (final_value - total_invested) / total_invested * 100, 2
        ),
    }
    lumpsum_value = total_invested * (growth * 0.98)
    return {
        "dca": dca,
        "lumpsum": {
            "total_invested": round(total_invested, 2),
            "final_value": round(lumpsum_value, 2),
            "return_pct": round(
                (lumpsum_value - total_invested) / total_invested * 100, 2
            ),
        },
        "winner": "dca" if final_value >= lumpsum_value else "lumpsum",
        "prices": [
            round(float(body.initial_price or 1.0) * (1 + i * 0.002), 4)
            for i in range(periods)
        ],
    }


@router.post("/api/funds/dca/simulate")
async def simulate_legacy_dca(body: DCASimulateBody):
    """兼容定投模拟"""
    return ApiResponse(success=True, data=_legacy_dca_result(body))


@router.post("/api/fund-dca/simulate")
async def simulate_dca(body: DCASimulateBody):
    """定投模拟"""
    fund_code = body.fund_code or body.symbol
    if not body.start_date or not body.end_date:
        return ApiResponse(success=True, data=_legacy_dca_result(body))

    provider = get_provider()
    try:
        records = await provider.get_nav_history(
            fund_code, body.start_date, body.end_date
        )
        if not records:
            return ApiResponse(
                success=False,
                error="无净值数据，无法模拟",
                error_code="FUND_NO_DATA",
            )

        freq_map = {
            "weekly": DCAFrequency.WEEKLY,
            "biweekly": DCAFrequency.BIWEEKLY,
            "monthly": DCAFrequency.MONTHLY,
            "quarterly": DCAFrequency.QUARTERLY,
        }
        frequency = freq_map.get(body.frequency, DCAFrequency.MONTHLY)

        simulator = DCASimulator()
        result = simulator.simulate(
            nav_records=records,
            amount=body.amount,
            frequency=frequency,
            start_date=body.start_date,
            end_date=body.end_date,
        )
        result.fund_code = fund_code
        return ApiResponse(success=True, data=result.model_dump())
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


# ============================================================
# 组合管理
# ============================================================


@router.get("/api/fund-portfolio")
async def list_portfolios():
    """列出所有组合"""
    mgr = _get_portfolio_mgr()
    portfolios = mgr.list_all()
    return ApiResponse(
        success=True,
        data={"portfolios": portfolios, "total": len(portfolios)},
    )


@router.post("/api/fund-portfolio")
async def create_portfolio(body: PortfolioCreateBody):
    """创建组合"""
    mgr = _get_portfolio_mgr()
    portfolio = mgr.create(
        name=body.name,
        description=body.description,
        holdings=body.holdings,
    )
    return ApiResponse(success=True, data=portfolio)


@router.get("/api/fund-portfolio/{portfolio_id}")
async def get_portfolio(portfolio_id: str):
    """获取组合详情"""
    mgr = _get_portfolio_mgr()
    portfolio = mgr.get(portfolio_id)
    if not portfolio:
        return ApiResponse(
            success=False,
            error="组合不存在",
            error_code="PORTFOLIO_NOT_FOUND",
        )
    return ApiResponse(success=True, data=portfolio)


@router.put("/api/fund-portfolio/{portfolio_id}")
async def update_portfolio(portfolio_id: str, body: PortfolioUpdateBody):
    """更新组合"""
    mgr = _get_portfolio_mgr()
    portfolio = mgr.update(
        portfolio_id=portfolio_id,
        name=body.name,
        description=body.description,
        holdings=body.holdings,
    )
    if not portfolio:
        return ApiResponse(
            success=False,
            error="组合不存在",
            error_code="PORTFOLIO_NOT_FOUND",
        )
    return ApiResponse(success=True, data=portfolio)


@router.delete("/api/fund-portfolio/{portfolio_id}")
async def delete_portfolio(portfolio_id: str):
    """删除组合"""
    mgr = _get_portfolio_mgr()
    ok = mgr.delete(portfolio_id)
    if not ok:
        return ApiResponse(
            success=False,
            error="组合不存在",
            error_code="PORTFOLIO_NOT_FOUND",
        )
    return ApiResponse(success=True, data={"deleted": True})


# ============================================================
# 定投计划
# ============================================================

# 内存存储（可替换为 SQLite 持久化）
_dca_plans: list[dict[str, Any]] = []


class DCAPlanBody(BaseModel):
    """创建定投计划请求"""

    fund_code: str = Field(description="基金代码")
    fund_name: str = Field(default="", description="基金名称")
    amount: float = Field(description="每期金额")
    frequency: str = Field(default="monthly", description="频率")
    start_date: str = Field(description="开始日期")


@router.post("/api/fund-dca/plans")
async def create_dca_plan(body: DCAPlanBody):
    """创建定投计划"""
    import uuid

    plan = {
        "id": str(uuid.uuid4())[:8],
        "fund_code": body.fund_code,
        "fund_name": body.fund_name,
        "amount": body.amount,
        "frequency": body.frequency,
        "start_date": body.start_date,
        "status": "active",
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    _dca_plans.append(plan)
    return ApiResponse(success=True, data=plan)


@router.get("/api/fund-dca/plans")
async def list_dca_plans():
    """列出定投计划"""
    return ApiResponse(
        success=True,
        data={"plans": _dca_plans, "total": len(_dca_plans)},
    )


# ============================================================
# 组合再平衡
# ============================================================


class RebalanceBody(BaseModel):
    """再平衡请求"""

    portfolio_id: str = Field(description="组合ID")
    target_weights: dict[str, float] = Field(description="目标权重 {fund_code: weight}")


@router.post("/api/fund-portfolio/rebalance")
async def rebalance_portfolio(body: RebalanceBody):
    """计算组合再平衡交易"""
    mgr = _get_portfolio_mgr()
    portfolio = mgr.get(body.portfolio_id)
    if not portfolio:
        return ApiResponse(
            success=False,
            error="组合不存在",
            error_code="PORTFOLIO_NOT_FOUND",
        )

    # 计算权重差异，生成交易建议
    holdings = portfolio.get("holdings", [])
    trades = []
    total_target = sum(body.target_weights.values())
    if total_target <= 0:
        return ApiResponse(
            success=False,
            error="目标权重总和必须大于 0",
        )

    # 归一化权重
    normalized = {k: v / total_target for k, v in body.target_weights.items()}

    # 简单再平衡：计算每个基金的目标持仓变化
    for fund_code, target_weight in normalized.items():
        current_weight = 0.0
        for h in holdings:
            if h.get("fund_code") == fund_code:
                current_weight = h.get("weight", 0.0)
                break
        diff = target_weight - current_weight
        if abs(diff) > 0.001:
            trades.append(
                {
                    "fund_code": fund_code,
                    "action": "buy" if diff > 0 else "sell",
                    "weight_change": round(diff, 4),
                }
            )

    return ApiResponse(
        success=True,
        data={
            "portfolio_id": body.portfolio_id,
            "trades": trades,
            "estimated_cost": 0.0,
        },
    )


# ============================================================
# 基金报告生成
# ============================================================


class FundReportBody(BaseModel):
    """基金报告请求"""

    fund_code: str = Field(description="基金代码")
    include_metrics: bool = Field(default=True, description="包含指标")
    include_dca: bool = Field(default=False, description="包含定投分析")


@router.post("/api/fund-reports/generate")
async def generate_fund_report(body: FundReportBody):
    """生成基金分析报告"""
    provider = get_provider()
    fund_code = body.fund_code
    try:
        info = await provider.get_info(fund_code)
        records = await provider.get_nav_history(fund_code)

        if not info:
            return ApiResponse(
                success=False,
                error=f"基金 {fund_code} 不存在",
                error_code="FUND_NOT_FOUND",
            )

        navs = [r["nav"] for r in records] if records else []
        metrics = calc_fund_metrics(navs) if navs else {}

        # 生成 Markdown 报告
        lines = [
            f"# 基金分析报告: {info.get('name', fund_code)}",
            "",
            f"- 基金代码: {fund_code}",
            f"- 基金类型: {info.get('fund_type', '未知')}",
            f"- 基金经理: {info.get('manager', '未知')}",
            f"- 基金公司: {info.get('company', '未知')}",
            "",
        ]

        report_metrics = _ReportMetrics(metrics)
        if body.include_metrics and metrics:
            lines.extend(
                [
                    "## 核心指标",
                    f"- 总收益率: {report_metrics.get('total_return', 0):.2%}",
                    f"- 年化收益率: {report_metrics.get('annualized_return', 0):.2%}",
                    f"- 夏普比率: {report_metrics.get('sharpe_ratio', 0):.4f}",
                    f"- 最大回撤: {report_metrics.get('max_drawdown', 0):.2%}",
                    f"- 波动率: {report_metrics.get('volatility', 0):.2%}",
                    f"- 胜率: {report_metrics.get('win_rate', 0):.2%}",
                    "",
                ]
            )

        report_content = "\n".join(lines)

        return ApiResponse(
            success=True,
            data={
                "fund_code": fund_code,
                "content": report_content,
                "metrics": metrics,
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))
