"""数据核验 Agent — 分析前的确定性数据完整性预检(v1.9.4, compass §7.3)。

动机
----
多 Agent 投研最大的暗坑是「数据缺失 → LLM 用先验/常识脑补 → 伪造出看似可信的
财务数字或资金流向」。本模块在 LLM Agent 跑之前做一道**确定性、纯规则、可单测**的
前置闸:逐维度检查 `stock_data` 是否齐全/新鲜/无明显异常, 把缺失维度显式打标
「维度缺失」, 并生成一段强约束提示注入市场简报——告诉下游 Agent:

    对缺失维度, 必须在结论里显式声明「该维度数据缺失」, 严禁编造, 并相应下调置信度。

设计哲学与 `backend/quant/risk/engine.py` 一致:
- 纯函数 / 确定性 / 不触发网络 / 失败不抛异常打断主流程。
- 只做研究层的「提示与约束」, 不替 Agent 下结论, 不阻断分析(price 缺失例外:
  无价格时分析无意义, 标 insufficient 供上层决定是否继续)。

用法::

    from backend.agents.data_verifier import verify_data

    v = verify_data(stock_data, evidence_pool=evidence_pool)
    brief += v.brief_warning()          # 注入简报, 约束下游不要编造
    result["data_verification"] = v.to_dict()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 维度状态
OK = "ok"  # 数据齐全可用
MISSING = "missing"  # 维度缺失 — 下游严禁编造
STALE = "stale"  # 数据过期 — 谨慎使用
ANOMALY = "anomaly"  # 数值异常 — 可能采集错误

# 整体结论
COMPLETE = "complete"  # 核心维度齐全且补充维度充分
PARTIAL = "partial"  # 部分维度缺失, 可降级分析
INSUFFICIENT = "insufficient"  # 核心(价格)缺失, 分析无意义

# 时效阈值(自然日): 日线数据超过该天数视为可能过期。
_STALE_DAYS = 7

# 维度中文名(展示用)
_DIM_LABEL = {
    "price": "行情价格",
    "technical": "技术指标",
    "fundamental": "基本面",
    "fund_flow": "资金流向",
    "news": "舆情/新闻",
    "evidence": "证据链",
}

# 核心维度: 缺失会显著降低分析价值
_CORE_DIMS = ("price", "technical")


def _is_present(value: Any) -> bool:
    """判断一个字段是否「有实际内容」(排除 None / 空串 / N/A / 占位)。"""
    if value is None:
        return False
    if isinstance(value, str):
        s = value.strip()
        return s not in ("", "N/A", "n/a", "暂无", "None", "-", "—", "nan")
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    return True


def _to_float(value: Any) -> Optional[float]:
    try:
        f = float(value)
        # NaN != NaN
        return f if f == f else None
    except (TypeError, ValueError):
        return None


@dataclass
class DimensionResult:
    """单个数据维度的核验结果。"""

    dimension: str
    status: str  # OK / MISSING / STALE / ANOMALY
    detail: str = ""

    @property
    def label(self) -> str:
        return _DIM_LABEL.get(self.dimension, self.dimension)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class DataVerification:
    """整体数据核验报告。"""

    overall: str  # COMPLETE / PARTIAL / INSUFFICIENT
    dimensions: List[DimensionResult] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)

    # ---- 派生视图 ----
    @property
    def missing(self) -> List[str]:
        return [d.label for d in self.dimensions if d.status == MISSING]

    @property
    def stale(self) -> List[str]:
        return [d.label for d in self.dimensions if d.status == STALE]

    @property
    def ok_dims(self) -> List[str]:
        return [d.label for d in self.dimensions if d.status == OK]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall": self.overall,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "missing": self.missing,
            "stale": self.stale,
            "ok": self.ok_dims,
            "anomalies": list(self.anomalies),
            "summary": self.headline(),
        }

    def headline(self) -> str:
        """一句话总结, 供前端 chip / 研报顶部使用。"""
        if self.overall == INSUFFICIENT:
            return "数据不足:缺少有效行情, 本次分析仅供参考"
        if self.overall == COMPLETE and not self.anomalies:
            return "数据完整性核验通过:核心维度齐全"
        parts: List[str] = []
        if self.missing:
            parts.append("缺失 " + "/".join(self.missing))
        if self.stale:
            parts.append("过期 " + "/".join(self.stale))
        if self.anomalies:
            parts.append(f"{len(self.anomalies)} 项数值异常")
        return "数据部分受限:" + ("; ".join(parts) if parts else "见明细")

    def brief_warning(self) -> str:
        """生成注入市场简报的强约束提示。

        只有存在缺失/过期/异常时才输出非空内容——数据齐全时返回空串, 不污染简报。
        这段文字是「反幻觉」的关键:明确告诉下游 Agent 哪些维度没有数据、不得编造。
        """
        problem_dims = [d for d in self.dimensions if d.status in (MISSING, STALE, ANOMALY)]
        if not problem_dims and not self.anomalies:
            return ""

        lines = ["", "【数据完整性核验 — 严禁对缺失维度编造数据】"]
        for d in self.dimensions:
            if d.status == OK:
                icon = "✅"
                note = "数据可用"
            elif d.status == MISSING:
                icon = "⛔"
                note = "数据缺失 — 结论中必须显式声明本维度无数据, 不得臆造"
            elif d.status == STALE:
                icon = "⚠️"
                note = "数据可能过期 — 使用时注明时效风险"
            else:  # ANOMALY
                icon = "❗"
                note = "数值异常 — 谨慎采信"
            extra = f"({d.detail})" if d.detail else ""
            lines.append(f"- {icon} {d.label}: {note}{extra}")

        if self.anomalies:
            lines.append("【数值异常明细】")
            for a in self.anomalies:
                lines.append(f"  - {a}")

        lines.append(
            "约束:仅基于上面标注「数据可用」的维度作出判断;对缺失维度, "
            "结论必须显式标注「该维度数据缺失」并相应下调置信度。"
        )
        return "\n".join(lines) + "\n"


# ============== 各维度检查 ==============


def _check_price(sd: Dict[str, Any], anomalies: List[str]) -> DimensionResult:
    close = _to_float(sd.get("close"))
    if close is None or close <= 0:
        return DimensionResult("price", MISSING, "最新价为空或 ≤0")
    # 数值异常: 区间最高<最低
    hi = _to_float(sd.get("period_high"))
    lo = _to_float(sd.get("period_low"))
    if hi is not None and lo is not None and hi > 0 and lo > 0 and hi < lo:
        anomalies.append(f"区间最高({hi}) < 区间最低({lo})")
        return DimensionResult("price", ANOMALY, "区间高低值倒挂")
    return DimensionResult("price", OK)


def _check_technical(sd: Dict[str, Any], anomalies: List[str]) -> DimensionResult:
    tech_keys = ("ma5", "ma20", "ma60", "macd", "rsi", "dif", "dea")
    present = [k for k in tech_keys if _is_present(sd.get(k))]
    if not present:
        return DimensionResult("technical", MISSING, "无任何均线/MACD/RSI 指标")
    # 数值异常: RSI 越界
    rsi = _to_float(sd.get("rsi"))
    if rsi is not None and (rsi < 0 or rsi > 100):
        anomalies.append(f"RSI={rsi} 超出 [0,100]")
        return DimensionResult("technical", ANOMALY, "RSI 越界")
    # 均线为负
    for mk in ("ma5", "ma20", "ma60"):
        mv = _to_float(sd.get(mk))
        if mv is not None and mv < 0:
            anomalies.append(f"{mk.upper()}={mv} 为负")
            return DimensionResult("technical", ANOMALY, f"{mk.upper()} 为负")
    return DimensionResult("technical", OK, f"含 {len(present)} 项指标")


def _check_fundamental(sd: Dict[str, Any]) -> DimensionResult:
    if _is_present(sd.get("fundamentals")):
        return DimensionResult("fundamental", OK)
    return DimensionResult("fundamental", MISSING, "无基本面摘要")


def _check_fund_flow(sd: Dict[str, Any]) -> DimensionResult:
    if _is_present(sd.get("stock_fund_brief")) or _is_present(sd.get("market_fund_brief")):
        return DimensionResult("fund_flow", OK)
    return DimensionResult("fund_flow", MISSING, "无主力/大盘资金流数据")


def _check_news(sd: Dict[str, Any]) -> DimensionResult:
    news_keys = (
        "related_news_brief",
        "industry_news_brief",
        "market_news_brief",
        "concepts_brief",
        "announcements_brief",
        "research_brief",
    )
    if any(_is_present(sd.get(k)) for k in news_keys):
        return DimensionResult("news", OK)
    return DimensionResult("news", MISSING, "无新闻/公告/研报")


def _check_evidence(evidence_pool: Optional[List[dict]]) -> Optional[DimensionResult]:
    if evidence_pool is None:
        return None  # 未提供证据池 → 不纳入维度(由 evidence_pool 机制单独追踪)
    if evidence_pool:
        return DimensionResult("evidence", OK, f"{len(evidence_pool)} 条证据")
    return DimensionResult("evidence", MISSING, "证据检索为空")


def _check_freshness(sd: Dict[str, Any]) -> Optional[str]:
    """若 stock_data 带日期字段, 检查是否过期。返回过期说明或 None。"""
    import datetime

    date_str = None
    for key in ("as_of", "data_date", "latest_date", "date", "trade_date"):
        v = sd.get(key)
        if _is_present(v):
            date_str = str(v).strip()[:10]
            break
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            d = datetime.datetime.strptime(date_str, fmt).date()
            age = (datetime.date.today() - d).days
            if age > _STALE_DAYS:
                return f"最新数据日期 {date_str}, 距今 {age} 天"
            return None
        except ValueError:
            continue
    return None


def verify_data(
    stock_data: Dict[str, Any],
    evidence_pool: Optional[List[dict]] = None,
) -> DataVerification:
    """对 stock_data 做确定性数据完整性核验。

    Args:
        stock_data: orchestrator 构建的标的数据快照。
        evidence_pool: 可选证据池;提供时纳入 evidence 维度。

    Returns:
        DataVerification(overall / dimensions / anomalies)。失败不抛异常。
    """
    try:
        sd = stock_data or {}
        anomalies: List[str] = []

        dims: List[DimensionResult] = [
            _check_price(sd, anomalies),
            _check_technical(sd, anomalies),
            _check_fundamental(sd),
            _check_fund_flow(sd),
            _check_news(sd),
        ]
        ev = _check_evidence(evidence_pool)
        if ev is not None:
            dims.append(ev)

        # 时效: 命中则把 price 维度(若 OK)降级为 STALE。
        stale_note = _check_freshness(sd)
        if stale_note:
            for d in dims:
                if d.dimension == "price" and d.status == OK:
                    d.status = STALE
                    d.detail = stale_note

        # ---- 整体判定 ----
        price_dim = next((d for d in dims if d.dimension == "price"), None)
        price_missing = price_dim is None or price_dim.status == MISSING
        if price_missing:
            overall = INSUFFICIENT
        else:
            core_ok = all(d.status in (OK, STALE) for d in dims if d.dimension in _CORE_DIMS)
            supp_ok = sum(1 for d in dims if d.dimension not in _CORE_DIMS and d.status == OK)
            if core_ok and supp_ok >= 2:
                overall = COMPLETE
            else:
                overall = PARTIAL

        return DataVerification(overall=overall, dimensions=dims, anomalies=anomalies)
    except Exception:  # noqa: BLE001 - 核验失败绝不阻断主分析流程
        # 安全降级: 返回一个不阻断、不误导的中性结果。
        return DataVerification(
            overall=PARTIAL,
            dimensions=[DimensionResult("price", OK, "核验跳过")],
            anomalies=[],
        )
