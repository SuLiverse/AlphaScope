"""
基本面数据层（v0.7 新增）

功能：
- 财务摘要（近 4 期：营收/净利/毛利率/ROE/资产负债率 + 同比）
- 股东结构（十大股东 / 流通股东 / 机构持仓变动）
- 同业对比（行业内总市值前 8 + 本股，最多 9 行）
- 24 小时本地文件缓存（cache/fundamentals/{symbol}.json）
- 所有 akshare 调用经 _safe() 包装，单接口失败不影响整体
"""

import warnings

warnings.filterwarnings("ignore")

import json
import time
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import akshare as ak
import pandas as pd

try:
    from backend.project_paths import CACHE_DIR
except ImportError:
    from project_paths import CACHE_DIR


# ============== 路径与常量 ==============
CACHE_ROOT = CACHE_DIR / "fundamentals"
CACHE_TTL_SECONDS = 86400  # 24 小时


# ============== Dataclass 定义 ==============
@dataclass
class FinancialPeriod:
    """单期财务核心指标"""

    period: str = ""
    revenue_yi: float = 0.0  # 营业收入(亿元)
    net_profit_yi: float = 0.0  # 归母净利润(亿元)
    gross_margin_pct: float = 0.0  # 毛利率(%)
    roe_pct: float = 0.0  # ROE(%)
    debt_ratio_pct: float = 0.0  # 资产负债率(%)
    yoy_revenue: float = 0.0  # 营收同比增速(%)
    yoy_net_profit: float = 0.0  # 净利同比增速(%)


@dataclass
class ShareholderRow:
    """股东行（用于十大股东 / 流通股东 / 机构变动）"""

    rank: int = 0
    name: str = ""
    shares_yi: float = 0.0  # 持股数(亿股)
    ratio_pct: float = 0.0  # 持股比例(%)
    change_type: str = ""  # 变动方向：增持/减持/不变/新进/退出


@dataclass
class PeerRow:
    """同业对比行"""

    symbol: str = ""
    name: str = ""
    total_mcap_yi: float = 0.0  # 总市值(亿元)
    pe: float = 0.0
    pb: float = 0.0
    roe_pct: float = 0.0
    yoy_revenue_pct: float = 0.0
    yoy_net_profit_pct: float = 0.0
    is_self: bool = False


@dataclass
class FundamentalsData:
    """单股基本面整合容器"""

    symbol: str = ""
    stock_name: str = ""
    data_date: str = ""
    financials: List[FinancialPeriod] = field(default_factory=list)
    top_holders: List[ShareholderRow] = field(default_factory=list)
    circulate_holders: List[ShareholderRow] = field(default_factory=list)
    inst_changes: List[ShareholderRow] = field(default_factory=list)
    industry_name: str = ""
    peers: List[PeerRow] = field(default_factory=list)
    has_error: bool = False
    error_msg: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ============== 工具函数 ==============
from backend.utils import safe_call as _safe


def _to_float(v, default: float = 0.0) -> float:
    """安全转 float，处理 NaN / None / 百分号字符串"""
    if v is None:
        return default
    if isinstance(v, (int, float)):
        try:
            if pd.isna(v):
                return default
        except Exception:
            pass
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in ("--", "-", "N/A", "nan", "None"):
        return default
    # 处理百分号
    s = s.rstrip("%")
    try:
        return float(s)
    except Exception:
        return default


def _to_yi(v) -> float:
    """元 → 亿元"""
    return _to_float(v) / 1e8


# ============== 缓存层 ==============
def _ensure_cache_dir():
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _cache_path(symbol: str) -> Path:
    return CACHE_ROOT / f"{symbol}.json"


def _read_cache(symbol: str) -> Optional[dict]:
    """读取缓存，过期返回 None"""
    p = _cache_path(symbol)
    if not p.exists():
        return None
    try:
        if (time.time() - p.stat().st_mtime) > CACHE_TTL_SECONDS:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(symbol: str, data: dict):
    _ensure_cache_dir()
    try:
        _cache_path(symbol).write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


def _from_cache_dict(d: dict) -> FundamentalsData:
    """从缓存 dict 重建 FundamentalsData"""
    data = FundamentalsData(
        symbol=d.get("symbol", ""),
        stock_name=d.get("stock_name", ""),
        data_date=d.get("data_date", ""),
        industry_name=d.get("industry_name", ""),
        has_error=d.get("has_error", False),
        error_msg=d.get("error_msg", ""),
    )
    for f in d.get("financials", []) or []:
        data.financials.append(FinancialPeriod(**f))
    for f in d.get("top_holders", []) or []:
        data.top_holders.append(ShareholderRow(**f))
    for f in d.get("circulate_holders", []) or []:
        data.circulate_holders.append(ShareholderRow(**f))
    for f in d.get("inst_changes", []) or []:
        data.inst_changes.append(ShareholderRow(**f))
    for f in d.get("peers", []) or []:
        data.peers.append(PeerRow(**f))
    return data


# ============== 财务摘要 ==============
def fetch_financial_summary(symbol: str, periods: int = 4) -> List[FinancialPeriod]:
    """近 N 期财报核心指标（年报/季报合并）。失败返回 []"""
    df = _safe(ak.stock_financial_abstract, symbol=symbol)
    if df is None or len(df) == 0:
        return []

    df = df.copy()
    # akshare stock_financial_abstract 返回：
    # 列：选项(常见值) / 指标(指标名) / 多列日期(20240930 / 20240630 ...)
    # 我们按"指标"行筛选关键指标 → 取最近 N 列日期
    if "指标" not in df.columns:
        return []

    # 提取日期列（形如 "20240930" 的列）
    date_cols = [
        c for c in df.columns if isinstance(c, str) and re.match(r"^\d{8}$", c)
    ]
    if not date_cols:
        return []
    # 倒序后取前 periods 列
    date_cols = sorted(date_cols, reverse=True)[:periods]

    # 关键指标行匹配（不同版本 akshare 字段名可能略有差异）
    indicator_map = {
        "revenue": ["营业总收入", "营业收入"],
        "net_profit": ["归母净利润", "净利润", "归属于母公司股东的净利润"],
        "gross_margin": ["销售毛利率", "毛利率"],
        "roe": ["净资产收益率(ROE)", "净资产收益率", "ROE", "加权净资产收益率"],
        "debt_ratio": ["资产负债率"],
        "yoy_revenue": ["营业收入同比增长", "营业总收入同比增长", "营收同比"],
        "yoy_net_profit": ["归母净利润同比增长", "净利润同比增长", "净利同比"],
    }

    def _find_row(keys: list) -> Optional[pd.Series]:
        for k in keys:
            mask = df["指标"].astype(str).str.contains(k, na=False)
            if mask.any():
                return df.loc[mask].iloc[0]
        return None

    row_revenue = _find_row(indicator_map["revenue"])
    row_net = _find_row(indicator_map["net_profit"])
    row_gross = _find_row(indicator_map["gross_margin"])
    row_roe = _find_row(indicator_map["roe"])
    row_debt = _find_row(indicator_map["debt_ratio"])
    row_yoy_rev = _find_row(indicator_map["yoy_revenue"])
    row_yoy_np = _find_row(indicator_map["yoy_net_profit"])

    out: List[FinancialPeriod] = []
    for dcol in date_cols:
        # 格式化期间：20240930 → 2024-09-30
        period_str = f"{dcol[:4]}-{dcol[4:6]}-{dcol[6:8]}"
        out.append(
            FinancialPeriod(
                period=period_str,
                revenue_yi=_to_yi(row_revenue.get(dcol))
                if row_revenue is not None
                else 0.0,
                net_profit_yi=_to_yi(row_net.get(dcol)) if row_net is not None else 0.0,
                gross_margin_pct=_to_float(row_gross.get(dcol))
                if row_gross is not None
                else 0.0,
                roe_pct=_to_float(row_roe.get(dcol)) if row_roe is not None else 0.0,
                debt_ratio_pct=_to_float(row_debt.get(dcol))
                if row_debt is not None
                else 0.0,
                yoy_revenue=_to_float(row_yoy_rev.get(dcol))
                if row_yoy_rev is not None
                else 0.0,
                yoy_net_profit=_to_float(row_yoy_np.get(dcol))
                if row_yoy_np is not None
                else 0.0,
            )
        )
    return out


def _to_market_symbol(symbol: str) -> str:
    """6 位代码 → 带交易所前缀(akshare 部分接口要求 sh600519/sz000858)"""
    s = str(symbol).strip()
    if s.startswith(("sh", "sz", "bj")):
        return s
    if s.startswith(("60", "68", "9")):
        return f"sh{s}"
    if s.startswith(("00", "30", "20")):
        return f"sz{s}"
    if s.startswith(("4", "8")):
        return f"bj{s}"
    return f"sh{s}"


# ============== 股东结构 ==============
def _normalize_shareholder_df(
    df: pd.DataFrame, limit: int = 10
) -> List[ShareholderRow]:
    """通用股东表归一化"""
    if df is None or len(df) == 0:
        return []
    df = df.copy().head(limit)

    # 识别字段
    name_col = next(
        (c for c in df.columns if "股东" in str(c) and "名称" in str(c)), None
    ) or next((c for c in df.columns if str(c).strip() in ("股东名称", "名称")), None)
    if name_col is None:
        # 尝试首个字符串列
        for c in df.columns:
            if df[c].dtype == object:
                name_col = c
                break
    shares_col = next(
        (c for c in df.columns if "持股数" in str(c) or "持有数量" in str(c)), None
    ) or next((c for c in df.columns if "数量" in str(c)), None)
    ratio_col = next(
        (
            c
            for c in df.columns
            if "比例" in str(c) or "占比" in str(c) or "持股比" in str(c)
        ),
        None,
    )
    change_col = next(
        (c for c in df.columns if "增减" in str(c) and "比" not in str(c)), None
    ) or next((c for c in df.columns if "变化" in str(c) or "变动" in str(c)), None)

    out = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        # 持股数:可能是"亿股"、"万股"或数值
        shares_raw = row[shares_col] if shares_col else None
        shares_yi = _to_yi(shares_raw)
        # 如果数字异常小(< 0.0001),可能本身已是亿股单位
        if shares_yi == 0 and shares_raw is not None:
            shares_yi = _to_float(shares_raw) / 1e8

        ratio = _to_float(row[ratio_col]) if ratio_col else 0.0
        # akshare 部分接口返回 0-1 的小数比例,转为百分比
        if 0 < ratio < 1.0:
            ratio = ratio * 100

        out.append(
            ShareholderRow(
                rank=int(_to_float(row.get("名次", i)) or i),
                name=str(row[name_col]).strip() if name_col else "",
                shares_yi=shares_yi,
                ratio_pct=ratio,
                change_type=str(row[change_col]).strip() if change_col else "",
            )
        )
    return out


def fetch_top_holders(symbol: str) -> List[ShareholderRow]:
    """十大股东(东财)"""
    market_symbol = _to_market_symbol(symbol)
    df = _safe(ak.stock_gdfx_top_10_em, symbol=market_symbol)
    if df is None or len(df) == 0:
        # 兜底:新浪(可能网络不稳)
        df = _safe(ak.stock_main_stock_holder, stock=symbol)
    return _normalize_shareholder_df(df, limit=10)


def fetch_circulate_holders(symbol: str) -> List[ShareholderRow]:
    """十大流通股东(东财)"""
    market_symbol = _to_market_symbol(symbol)
    df = _safe(ak.stock_gdfx_free_top_10_em, symbol=market_symbol)
    if df is None or len(df) == 0:
        df = _safe(ak.stock_circulate_stock_holder, symbol=symbol)
    return _normalize_shareholder_df(df, limit=10)


def fetch_inst_changes(symbol: str) -> List[ShareholderRow]:
    """机构持仓变动（进出）"""
    df = _safe(ak.stock_institute_hold_detail, symbol=symbol)
    if df is None or len(df) == 0:
        return []
    df = df.copy().head(15)
    # 该接口返回字段不固定，做容错
    name_col = next(
        (
            c
            for c in df.columns
            if "机构" in str(c) and ("名" in str(c) or "称" in str(c))
        ),
        None,
    )
    if name_col is None:
        name_col = next((c for c in df.columns if df[c].dtype == object), None)
    shares_col = next(
        (c for c in df.columns if "持股数" in str(c) or "持仓" in str(c)), None
    )
    ratio_col = next(
        (c for c in df.columns if "占" in str(c) and "%" in str(c)), None
    ) or next((c for c in df.columns if "比例" in str(c)), None)
    change_col = next(
        (c for c in df.columns if "变" in str(c) or "增减" in str(c)), None
    )

    out = []
    for i, (_, row) in enumerate(df.iterrows(), 1):
        out.append(
            ShareholderRow(
                rank=i,
                name=str(row[name_col]).strip() if name_col else "",
                shares_yi=_to_yi(row[shares_col]) if shares_col else 0.0,
                ratio_pct=_to_float(row[ratio_col]) if ratio_col else 0.0,
                change_type=str(row[change_col]).strip() if change_col else "",
            )
        )
    return out


# ============== 同业对比 ==============
def _get_industry_name(symbol: str) -> str:
    """从个股信息里取所属行业（东财），带重试 + 清理 Ⅱ 后缀

    东财 stock_individual_info_em 偶发 RemoteDisconnected，重试 3 次稳定下来。
    返回的行业名末尾常带罗马数字（如 "白酒Ⅱ"），但 stock_board_industry_cons_em
    需要的板块名是 "白酒"（不带后缀），必须清理。
    """
    import time

    df = None
    for _attempt in range(3):
        df = _safe(ak.stock_individual_info_em, symbol=symbol)
        if df is not None and len(df) > 0:
            break
        time.sleep(0.5)
    if df is None or len(df) == 0:
        return ""
    try:
        info = dict(zip(df["item"], df["value"]))
    except Exception:
        return ""
    for k in ("行业", "所属行业", "申万行业"):
        if info.get(k):
            name = str(info[k]).strip()
            # 清理东财行业名末尾的罗马数字（如 "白酒Ⅱ" → "白酒"）
            for suf in ("Ⅱ", "Ⅲ", "Ⅳ", "II", "III", "IV"):
                if name.endswith(suf):
                    name = name[: -len(suf)].strip()
                    break
            return name
    return ""


def _get_industry_constituents(industry: str) -> List[Tuple[str, str]]:
    """获取行业成分股列表 [(symbol, name), ...]"""
    if not industry:
        return []
    df = _safe(ak.stock_board_industry_cons_em, symbol=industry)
    if df is None or len(df) == 0:
        return []
    sym_col = next(
        (c for c in df.columns if str(c).strip() in ("代码", "股票代码")), None
    )
    name_col = next(
        (c for c in df.columns if str(c).strip() in ("名称", "股票名称")), None
    )
    if not sym_col or not name_col:
        return []
    out = []
    for _, row in df.iterrows():
        s = str(row[sym_col]).strip()
        n = str(row[name_col]).strip()
        if s and len(s) == 6 and s.isdigit():
            out.append((s, n))
    return out


def fetch_industry_peers(symbol: str, top_k: int = 8) -> Tuple[str, List[PeerRow]]:
    """
    返回 (industry_name, list[PeerRow])
    按总市值降序前 K，本股始终保留并标记 is_self=True
    """
    industry = _get_industry_name(symbol)
    constituents = _get_industry_constituents(industry)
    if not constituents:
        return industry, []

    # 一次性拿全市场行情快照（含市值/PE/PB/涨跌幅）
    spot_df = _safe(ak.stock_zh_a_spot_em)
    if spot_df is None or len(spot_df) == 0:
        return industry, []

    spot_df = spot_df.copy()
    code_col = next((c for c in spot_df.columns if str(c).strip() == "代码"), None)
    name_col = next((c for c in spot_df.columns if str(c).strip() == "名称"), None)
    mcap_col = next((c for c in spot_df.columns if "总市值" in str(c)), None)
    pe_col = next(
        (c for c in spot_df.columns if str(c).strip() in ("市盈率-动态", "市盈率")),
        None,
    )
    pb_col = next((c for c in spot_df.columns if str(c).strip() == "市净率"), None)

    if not code_col:
        return industry, []

    spot_df[code_col] = spot_df[code_col].astype(str)
    code_set = {s for s, _ in constituents}
    sub = spot_df[spot_df[code_col].isin(code_set)].copy()
    if len(sub) == 0:
        return industry, []

    # 总市值降序
    if mcap_col:
        sub["_mcap_yi"] = sub[mcap_col].apply(_to_yi)
        sub = sub.sort_values("_mcap_yi", ascending=False)
    else:
        sub["_mcap_yi"] = 0.0

    # 取前 K，并保证本股在列表内
    top_codes = list(sub[code_col].head(top_k))
    if symbol not in top_codes:
        top_codes.append(symbol)

    # 按行业内顺序 + 本股放最末（前端会高亮）
    rows: List[PeerRow] = []
    for code in top_codes:
        match = sub[sub[code_col] == code]
        if len(match) == 0:
            # 本股不在 spot_df，可能是停牌：手动构造一个最简行
            rows.append(
                PeerRow(
                    symbol=code,
                    name=next((n for s, n in constituents if s == code), code),
                    is_self=(code == symbol),
                )
            )
            continue
        r = match.iloc[0]
        rows.append(
            PeerRow(
                symbol=code,
                name=str(r[name_col]).strip() if name_col else "",
                total_mcap_yi=float(r["_mcap_yi"]),
                pe=_to_float(r[pe_col]) if pe_col else 0.0,
                pb=_to_float(r[pb_col]) if pb_col else 0.0,
                roe_pct=0.0,  # spot_em 不返回 ROE，留空（前端显示 -）
                yoy_revenue_pct=0.0,  # 同上
                yoy_net_profit_pct=0.0,
                is_self=(code == symbol),
            )
        )

    return industry, rows


# ============== 单次入口（带 24h 缓存） ==============
def load_fundamentals(
    symbol: str, stock_name: str = "", force_refresh: bool = False
) -> FundamentalsData:
    """单次入口：5 路并行 fetch + 24h 缓存。任一 fetch 失败不影响其他"""
    if not force_refresh:
        cached = _read_cache(symbol)
        if cached:
            return _from_cache_dict(cached)

    data = FundamentalsData(
        symbol=symbol,
        stock_name=stock_name,
        data_date=datetime.now().strftime("%Y-%m-%d"),
    )

    errors = []
    jobs = {
        "financials": lambda: fetch_financial_summary(symbol, periods=4),
        "top_holders": lambda: fetch_top_holders(symbol),
        "circulate_holders": lambda: fetch_circulate_holders(symbol),
        "inst_changes": lambda: fetch_inst_changes(symbol),
        "peers": lambda: fetch_industry_peers(symbol, top_k=8),
    }
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = {ex.submit(fn): name for name, fn in jobs.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue
            if name == "financials":
                data.financials = result
            elif name == "top_holders":
                data.top_holders = result
            elif name == "circulate_holders":
                data.circulate_holders = result
            elif name == "inst_changes":
                data.inst_changes = result
            elif name == "peers":
                industry, peers = result
                data.industry_name = industry
                data.peers = peers

    # 全部失败才标 has_error
    if not data.financials and not data.top_holders and not data.peers:
        data.has_error = True
        data.error_msg = "; ".join(errors) if errors else "全部数据源不可用"

    # 写缓存
    _write_cache(symbol, data.to_dict())
    return data


# ============== 估值指标计算 ==============


def calc_valuation_metrics(
    pe: float = 0,
    pb: float = 0,
    eps: float = 0,
    revenue_yi: float = 0,
    net_profit_yi: float = 0,
    market_cap_yi: float = 0,
) -> dict:
    """计算估值指标：PEG/PS/EV-EBITDA 估算。"""
    result = {
        "pe": round(pe, 2) if pe else 0,
        "pb": round(pb, 2) if pb else 0,
        "eps": round(eps, 4) if eps else 0,
        "peg": 0.0,
        "ps": 0.0,
        "ev_ebitda_est": 0.0,
        "valuation_level": "unknown",
    }

    # PEG（PE / 净利润增速，需外部传入增速）
    # PS（市值 / 营收）
    if revenue_yi > 0 and market_cap_yi > 0:
        result["ps"] = round(market_cap_yi / revenue_yi, 2)

    # EV/EBITDA 估算（简化：市值 / 净利润 × 折旧系数）
    if net_profit_yi > 0 and market_cap_yi > 0:
        result["ev_ebitda_est"] = round(market_cap_yi / net_profit_yi * 0.8, 2)

    # 估值水平判断
    if pe > 0:
        if pe < 15:
            result["valuation_level"] = "低估"
        elif pe < 30:
            result["valuation_level"] = "合理"
        elif pe < 60:
            result["valuation_level"] = "偏高"
        else:
            result["valuation_level"] = "高估"

    return result


# ============== 盈利质量评估 ==============


def assess_earnings_quality(
    net_profit: float = 0,
    operating_cf: float = 0,
    non_recurring: float = 0,
) -> dict:
    """评估盈利质量。"""
    result = {
        "ocf_to_profit_ratio": 0.0,
        "non_recurring_ratio": 0.0,
        "quality_score": 0,
        "quality_level": "unknown",
        "warnings": [],
    }

    if net_profit > 0 and operating_cf != 0:
        ratio = operating_cf / net_profit
        result["ocf_to_profit_ratio"] = round(ratio, 2)
        if ratio >= 1.0:
            result["quality_score"] += 40
        elif ratio >= 0.7:
            result["quality_score"] += 25
        else:
            result["warnings"].append("经营现金流/净利润比偏低，盈利质量存疑")

    if non_recurring != 0 and net_profit > 0:
        ratio = abs(non_recurring) / net_profit
        result["non_recurring_ratio"] = round(ratio, 2)
        if ratio < 0.1:
            result["quality_score"] += 30
        elif ratio < 0.3:
            result["quality_score"] += 15
        else:
            result["warnings"].append("扣非净利润占比过高，盈利依赖非经常性损益")

    if net_profit > 0:
        result["quality_score"] += 30

    # 评级
    score = result["quality_score"]
    if score >= 80:
        result["quality_level"] = "优秀"
    elif score >= 60:
        result["quality_level"] = "良好"
    elif score >= 40:
        result["quality_level"] = "一般"
    else:
        result["quality_level"] = "较差"

    return result


# ============== 现金流分析 ==============


def analyze_cash_flow(
    operating_cf: float = 0,
    investing_cf: float = 0,
    financing_cf: float = 0,
    net_profit: float = 0,
) -> dict:
    """分析现金流状况。"""
    free_cf = operating_cf + investing_cf  # 自由现金流 = 经营 + 投资

    result = {
        "operating_cf": round(operating_cf, 2),
        "investing_cf": round(investing_cf, 2),
        "financing_cf": round(financing_cf, 2),
        "free_cash_flow": round(free_cf, 2),
        "cf_coverage": 0.0,
        "cf_pattern": "unknown",
        "cf_score": 0,
    }

    # 现金流覆盖比（经营现金流 / 净利润）
    if net_profit > 0:
        result["cf_coverage"] = round(operating_cf / net_profit, 2)

    # 现金流模式判断
    if operating_cf > 0 and investing_cf < 0 and financing_cf > 0:
        result["cf_pattern"] = "成长型"  # 经营+、投资-、融资+
    elif operating_cf > 0 and investing_cf < 0 and financing_cf < 0:
        result["cf_pattern"] = "成熟型"  # 经营+、投资-、融资-
    elif operating_cf > 0 and investing_cf > 0:
        result["cf_pattern"] = "收缩型"  # 经营+、投资+
    elif operating_cf < 0:
        result["cf_pattern"] = "预警型"  # 经营-
    else:
        result["cf_pattern"] = "其他"

    # 评分
    if operating_cf > 0:
        result["cf_score"] += 30
    if free_cf > 0:
        result["cf_score"] += 30
    if result["cf_coverage"] >= 1.0:
        result["cf_score"] += 20
    elif result["cf_coverage"] >= 0.5:
        result["cf_score"] += 10
    if financing_cf < 0:
        result["cf_score"] += 20  # 分红/还债

    return result


# ============== 资产负债分析 ==============


def analyze_balance_sheet(
    debt_ratio: float = 0,
    current_ratio: float = 0,
    roa: float = 0,
) -> dict:
    """分析资产负债健康度。"""
    result = {
        "debt_ratio": round(debt_ratio, 2),
        "current_ratio": round(current_ratio, 2),
        "roa": round(roa, 2),
        "health_score": 0,
        "health_level": "unknown",
        "warnings": [],
    }

    # 资产负债率评分
    if debt_ratio > 0:
        if debt_ratio < 40:
            result["health_score"] += 30
        elif debt_ratio < 60:
            result["health_score"] += 20
        elif debt_ratio < 70:
            result["health_score"] += 10
            result["warnings"].append("资产负债率偏高")
        else:
            result["warnings"].append("资产负债率过高，财务风险较大")

    # 流动比率评分
    if current_ratio > 0:
        if current_ratio >= 2.0:
            result["health_score"] += 30
        elif current_ratio >= 1.5:
            result["health_score"] += 20
        elif current_ratio >= 1.0:
            result["health_score"] += 10
        else:
            result["warnings"].append("流动比率不足，短期偿债压力大")

    # ROA 评分
    if roa > 0:
        if roa >= 10:
            result["health_score"] += 40
        elif roa >= 5:
            result["health_score"] += 25
        elif roa >= 2:
            result["health_score"] += 15
        else:
            result["health_score"] += 5

    # 评级
    score = result["health_score"]
    if score >= 80:
        result["health_level"] = "优秀"
    elif score >= 60:
        result["health_level"] = "良好"
    elif score >= 40:
        result["health_level"] = "一般"
    else:
        result["health_level"] = "较差"

    return result


# ============== 综合基本面评分 ==============


def compute_fundamental_score(
    valuation: dict | None = None,
    earnings: dict | None = None,
    cashflow: dict | None = None,
    balance: dict | None = None,
) -> dict:
    """综合基本面评分（0-100）。"""
    valuation = valuation or {}
    earnings = earnings or {}
    cashflow = cashflow or {}
    balance = balance or {}

    scores = {
        "valuation": 0,
        "earnings": 0,
        "cashflow": 0,
        "balance": 0,
    }

    # 估值评分
    level = valuation.get("valuation_level", "unknown")
    level_map = {"低估": 90, "合理": 70, "偏高": 40, "高估": 20}
    scores["valuation"] = level_map.get(level, 50)

    # 盈利质量评分
    scores["earnings"] = earnings.get("quality_score", 50)

    # 现金流评分
    scores["cashflow"] = cashflow.get("cf_score", 50)

    # 资产负债评分
    scores["balance"] = balance.get("health_score", 50)

    # 加权综合（各 25%）
    total = sum(scores.values()) / 4
    total = round(min(max(total, 0), 100), 1)

    # 评级
    if total >= 80:
        grade = "A"
    elif total >= 65:
        grade = "B"
    elif total >= 50:
        grade = "C"
    else:
        grade = "D"

    return {
        "total_score": total,
        "grade": grade,
        "dimension_scores": scores,
    }


# ============== 命令行自测 ==============
if __name__ == "__main__":
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "600519"
    name_map = {"600519": "贵州茅台", "300059": "东方财富", "000858": "五粮液"}
    name = name_map.get(code, code)

    print("=" * 70)
    print(f"测试 fundamentals.load_fundamentals({code} {name})")
    print("=" * 70)

    t0 = time.time()
    data = load_fundamentals(code, name, force_refresh=True)
    print(f"\n首次拉取耗时 {time.time() - t0:.1f}s\n")

    print(f"--- 财务摘要 ({len(data.financials)} 期) ---")
    for f in data.financials:
        print(
            f"  [{f.period}] 营收 {f.revenue_yi:.2f}亿 | 净利 {f.net_profit_yi:.2f}亿 | "
            f"毛利率 {f.gross_margin_pct:.2f}% | ROE {f.roe_pct:.2f}% | "
            f"负债率 {f.debt_ratio_pct:.2f}% | 营收同比 {f.yoy_revenue:+.2f}%"
        )

    print(f"\n--- 十大股东 ({len(data.top_holders)} 行) ---")
    for h in data.top_holders[:5]:
        print(
            f"  #{h.rank} {h.name[:20]:<22} {h.shares_yi:.4f}亿股 {h.ratio_pct:.2f}% {h.change_type}"
        )

    print(f"\n--- 流通股东 ({len(data.circulate_holders)} 行) ---")
    for h in data.circulate_holders[:5]:
        print(f"  #{h.rank} {h.name[:20]:<22} {h.shares_yi:.4f}亿股 {h.ratio_pct:.2f}%")

    print(f"\n--- 机构变动 ({len(data.inst_changes)} 行) ---")
    for h in data.inst_changes[:5]:
        print(f"  #{h.rank} {h.name[:20]:<22} {h.shares_yi:.4f}亿股 {h.change_type}")

    print(f"\n--- 同业对比 行业={data.industry_name} ({len(data.peers)} 行) ---")
    for p in data.peers:
        flag = "★本股" if p.is_self else "    "
        print(
            f"  {flag} {p.symbol} {p.name[:8]:<10} 市值 {p.total_mcap_yi:>8.1f}亿 "
            f"PE {p.pe:>6.2f} PB {p.pb:>5.2f}"
        )

    if data.has_error:
        print(f"\n[错误] {data.error_msg}")

    # 二次验证缓存
    print("\n" + "=" * 70)
    t1 = time.time()
    data2 = load_fundamentals(code, name)
    print(f"二次读取（走缓存）耗时 {time.time() - t1:.3f}s")
    print(f"缓存文件: {_cache_path(code)}")
