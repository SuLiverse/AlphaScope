"""游资席位速查表 + 龙虎榜席位分析逻辑。

席位匹配逻辑:龙虎榜拿到的"营业部名称"包含某游资席位关键字时，认定该游资在场。

移植并改编自 UZI-Skill ``scripts/lib/seat_db.py`` (MIT)，见
``docs/uzi-integration/ATTRIBUTION.md``。
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════
# 游资席位库
# 每个游资: real_name / tier / style / premium(溢价倾向) / seats(营业部关键字) / fit_rules(射程)
# ═══════════════════════════════════════════════════════════════
SEATS: dict[str, dict] = {
    # ────── 殿堂级 ──────
    "章盟主": {
        "real_name": "章建平",
        "tier": "legend",
        "style": "大资金趋势波段，格局锁仓",
        "premium": "neutral",
        "seats": [
            "国泰君安证券股份有限公司上海江苏路证券营业部",
            "国泰君安证券股份有限公司宁波彩虹北路证券营业部",
            "中信证券股份有限公司杭州延安路证券营业部",
        ],
        "fit_rules": {
            "min_mcap": 20_000_000_000,
            "trend": "up",
            "style_match": "trend",
        },
    },
    "孙哥": {
        "real_name": "孙煜",
        "tier": "legend",
        "style": "板块引导，波段锁仓",
        "premium": "neutral_positive",
        "seats": [
            "中信证券股份有限公司上海溧阳路证券营业部",
            "中信证券股份有限公司上海古北路证券营业部",
            "中信证券股份有限公司上海分公司",
        ],
        "fit_rules": {"min_mcap": 10_000_000_000, "is_sector_leader": True},
    },
    "赵老哥": {
        "real_name": "赵强",
        "tier": "legend",
        "style": "打板，二板定龙头",
        "premium": "positive",
        "seats": [
            "浙商证券股份有限公司绍兴解放北路证券营业部",
            "中国银河证券股份有限公司绍兴证券营业部",
            "中国银河证券股份有限公司北京阜成路证券营业部",
        ],
        "fit_rules": {"is_first_or_second_board": True, "is_sector_leader": True},
    },
    "佛山无影脚": {
        "real_name": "廖国沛",
        "tier": "legend",
        "style": "一日游，翘板，砸盘王",
        "premium": "negative",  # 反向指标
        "seats": [
            "光大证券股份有限公司佛山绿景路证券营业部",
            "光大证券股份有限公司佛山季华六路证券营业部",
            "湘财证券股份有限公司佛山祖庙路证券营业部",
        ],
        "fit_rules": {"max_mcap": 8_000_000_000, "is_oversold": True},
    },
    "炒股养家": {
        "tier": "legend",
        "style": "情绪揣摩，通道排板",
        "premium": "next_day_70",
        "seats": [
            "华鑫证券有限责任公司上海红宝石路证券营业部",
            "华鑫证券有限责任公司上海宛平南路证券营业部",
        ],
        "fit_rules": {"sentiment_cycle": True},
    },
    # ────── 新生代 ──────
    "陈小群": {
        "real_name": "陈宴群",
        "tier": "new_gen",
        "style": "龙头接力、一线天、反核按钮",
        "premium": "next_day_57",
        "seats": ["中国银河证券股份有限公司大连黄河路证券营业部"],
        "fit_rules": {"is_sector_leader": True, "is_hot_theme": True},
    },
    "呼家楼": {
        "tier": "new_gen",
        "style": "多席位协同、板块平铺扫货、欢乐豆玩法",
        "seats": [
            "中信证券股份有限公司上海凯滨路证券营业部",
            "中信证券股份有限公司北京总部",
            "中信建投证券股份有限公司北京朝外大街证券营业部",
        ],
        "fit_rules": {"is_hottest_in_sector": True},
    },
    "方新侠": {
        "tier": "new_gen",
        "style": "大成交趋势票、格局锁仓",
        "seats": [
            "兴业证券股份有限公司陕西分公司",
            "中信证券股份有限公司西安朱雀大街证券营业部",
        ],
        "fit_rules": {"min_turnover": 1_000_000_000, "trend": "up"},
    },
    "作手新一": {
        "real_name": "严冬",
        "tier": "new_gen",
        "style": "龙头战法，连板+趋势兼做",
        "seats": ["国泰君安证券股份有限公司南京太平南路证券营业部"],
        "fit_rules": {"is_sector_leader": True},
    },
    "小鳄鱼": {
        "tier": "new_gen",
        "style": "基本面辅助选股",
        "seats": [
            "南京证券股份有限公司南京大钟亭证券营业部",
            "中金财富证券有限公司南京龙蟠中路证券营业部",
        ],
        "fit_rules": {"min_fundamental_score": 70},
    },
    "交易猿": {
        "tier": "new_gen",
        "style": "大容量票锁仓、龙头加速",
        "seats": [
            "华泰证券股份有限公司天津东丽开发区二纬路证券营业部",
            "招商证券股份有限公司福州六一中路证券营业部",
        ],
        "fit_rules": {"min_mcap": 15_000_000_000, "is_sector_leader": True},
    },
    "毛老板": {
        "tier": "new_gen",
        "style": "AI主线大资金重仓",
        "seats": [
            "国泰君安证券股份有限公司北京光华路证券营业部",
            "方正证券股份有限公司乐山龙游路证券营业部",
            "广发证券股份有限公司上海东方路证券营业部",
        ],
        "fit_rules": {"is_ai_theme": True, "min_mcap": 10_000_000_000},
    },
    "消闲派": {
        "tier": "new_gen",
        "style": "满仓满融极致进攻、龙头加速锁仓",
        "seats": ["华泰证券股份有限公司浙江分公司"],
        "fit_rules": {"is_accelerating": True},
    },
    # ────── 区域帮派 ──────
    "拉萨天团": {
        "tier": "regional",
        "style": "群狼一日游，反向指标",
        "premium": "negative",
        "seats": ["东方财富证券股份有限公司拉萨"],  # 前缀模糊匹配
        "fit_rules": {"short_term_only": True},
    },
    "成都帮": {
        "tier": "regional",
        "style": "底部黑马点火一日游",
        "seats": ["华泰证券股份有限公司成都南一环路第二证券营业部"],
        "fit_rules": {"is_oversold": True},
    },
    "苏南帮": {
        "tier": "regional",
        "style": "多席位联动低价小盘",
        "seats": [
            "华泰证券股份有限公司无锡",
            "华泰证券股份有限公司镇江",
            "华泰证券股份有限公司南京",
        ],
        "fit_rules": {"max_mcap": 5_000_000_000},
    },
    "宁波桑田路": {
        "tier": "regional",
        "style": "连板接力",
        "seats": ["国盛证券有限责任公司宁波桑田路证券营业部"],
        "fit_rules": {"is_continuous_limit_up": True},
    },
    # ────── 2025 新晋 ──────
    "六一中路": {
        "tier": "new_2025",
        "style": "题材打板接力，2024 低空经济封神",
        "seats": ["招商证券股份有限公司福州六一中路证券营业部"],
        "fit_rules": {"is_hot_theme": True, "is_sector_leader": True},
    },
    "流沙河": {
        "tier": "new_2025",
        "style": "低吸/接力新晋",
        "seats": [
            "招商证券股份有限公司北京车公庄西路证券营业部",
            "华泰证券股份有限公司上海武定路证券营业部",
        ],
        "fit_rules": {"is_hot_theme": True},
    },
    "古北路": {
        "tier": "new_2025",
        "style": "2025 重新活跃顶级短线",
        "seats": ["中信证券股份有限公司上海古北路证券营业部"],
        "fit_rules": {"is_sector_leader": True},
    },
    "北京炒家": {
        "tier": "new_2025",
        "style": "首板战法，20-80亿题材股",
        "seats": ["首板专精，无固定席位"],
        "fit_rules": {
            "min_mcap": 2_000_000_000,
            "max_mcap": 8_000_000_000,
            "is_first_board": True,
            "max_institution_pct": 10,
        },
    },
    "瑞鹤仙": {
        "tier": "new_2025",
        "style": "题材短线，2025 新晋接力游资",
        "seats": ["银河证券", "招商证券深圳"],  # 关键字模糊匹配
        "fit_rules": {"is_hot_theme": True, "is_sector_leader": True},
    },
    "鑫多多": {
        "tier": "new_2025",
        "style": "题材打板 + 龙头接力，2025 新晋人气游资",
        "seats": ["华鑫证券", "招商证券", "中信证券"],  # 模糊匹配
        "fit_rules": {"is_hot_theme": True, "is_first_or_second_board": True},
    },
}

# 游资通用大市值上界(元)· fit_rules 未显式设 max_mcap 时生效。
# 理由:A 股游资几乎不玩 500 亿以上大盘股(流动性不足以拉动)。
FALLBACK_YOUZI_MAX_MCAP_YUAN = 50_000_000_000  # 500 亿元
_MEGA_CAP_ALLOWLIST = frozenset({"章盟主"})  # 可做大盘的游资


def _seat_text(row: dict) -> str:
    """把一条龙虎榜记录的所有字段拼成可搜索文本。"""
    return " ".join(str(v) for v in row.values())


def match_seats_in_lhb(lhb_records: list[dict]) -> dict[str, list[dict]]:
    """对 SEATS 中每个游资，找出提及其任一席位关键字的龙虎榜记录。

    Returns: ``{游资昵称: [命中的记录, ...]}``，仅含有命中的游资。
    """
    matches: dict[str, list[dict]] = {}
    for nick, info in SEATS.items():
        seat_keywords = info.get("seats", [])
        hits = [row for row in lhb_records if any(kw in _seat_text(row) for kw in seat_keywords)]
        if hits:
            matches[nick] = hits
    return matches


def _is_institutional(seat_name: str) -> bool:
    """机构席位关键词识别。"""
    seat = str(seat_name or "")
    return "机构专用" in seat or ("机构" in seat and "证券" not in seat)


def _num(value) -> float:
    """宽松地把金额字段转 float(空/异常 → 0)。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def split_inst_vs_youzi(records: list[dict]) -> dict:
    """把龙虎榜记录按机构 vs 游资席位拆分买卖额与净额。

    兼容多种列名:营业部名称/交易营业部名称/交易营业部;
    买入金额/买入额、卖出金额/卖出额。
    """
    inst_buy = inst_sell = youzi_buy = youzi_sell = 0.0
    for r in records:
        seat = str(r.get("营业部名称") or r.get("交易营业部名称") or r.get("交易营业部") or "")
        buy = _num(r.get("买入金额") or r.get("买入额") or 0)
        sell = _num(r.get("卖出金额") or r.get("卖出额") or 0)
        if _is_institutional(seat):
            inst_buy += buy
            inst_sell += sell
        else:
            youzi_buy += buy
            youzi_sell += sell
    return {
        "institutional_buy": inst_buy,
        "institutional_sell": inst_sell,
        "institutional_net": inst_buy - inst_sell,
        "youzi_buy": youzi_buy,
        "youzi_sell": youzi_sell,
        "youzi_net": youzi_buy - youzi_sell,
    }


def is_in_range(nickname: str, ticker_features: dict) -> bool:
    """按 fit_rules 判断某游资是否"射程"覆盖该股票。

    ticker_features 可含: market_cap, trend, is_sector_leader, sentiment_cycle 等。
    对未显式设 max_mcap 的游资，隐式套用 500 亿上限(allowlist 除外)。
    """
    info = SEATS.get(nickname)
    if not info:
        return False
    rules = info.get("fit_rules", {})
    mc = ticker_features.get("market_cap", 0) or 0
    if "min_mcap" in rules and mc < rules["min_mcap"]:
        return False
    if "max_mcap" in rules and mc > rules["max_mcap"]:
        return False
    if "max_mcap" not in rules and nickname not in _MEGA_CAP_ALLOWLIST:
        if mc > FALLBACK_YOUZI_MAX_MCAP_YUAN:
            return False
    for k, v in rules.items():
        if k.startswith(("min_", "max_")):
            continue
        if k in ticker_features and ticker_features[k] != v:
            return False
    return True
