"""机构级财务估值模型(纯 Python，可追溯）。

五个核心模型:
    1. compute_dcf           — WACC + 两阶段 FCF + 终值 + 敏感性
    2. build_comps_table     — 同业倍数、分位、隐含价
    3. project_three_stmt     — 5 年三表预测(联动)
    4. quick_lbo             — 入场 EV、债务计划、退出 IRR/MOIC
    5. accretion_dilution    — 并购 pro-forma EPS

所有函数接收 ``features`` 字典(单位多为"亿元"/百分比），返回结构化结果，
每一步推导记录在 ``methodology_log`` 中，便于报告引用"为什么是这个数"。

A 股默认假设:无风险利率 ~2.5%(10Y 国债)、ERP ~6%、税率 25%、终值增长 2.5%。

移植并改编自 UZI-Skill ``scripts/lib/fin_models.py`` (MIT)，其本身改编自
anthropics/financial-services-plugins。见 ``docs/uzi-integration/ATTRIBUTION.md``。
"""

from __future__ import annotations


# ────────────────────────────────────────────────────────────────
# A 股默认假设
# ────────────────────────────────────────────────────────────────
DEFAULT_RF = 0.025  # 10Y 国债收益率
DEFAULT_ERP = 0.06  # A 股历史股权风险溢价
DEFAULT_BETA = 1.00
DEFAULT_TAX = 0.25
DEFAULT_TERMINAL_G = 0.025  # 长期名义 GDP
DEFAULT_STAGE1_YEARS = 5
DEFAULT_STAGE2_YEARS = 5
DEFAULT_STAGE1_GROWTH = 0.10  # 高增长期
DEFAULT_STAGE2_GROWTH = 0.05  # 过渡期


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════
# 1. DCF
# ═══════════════════════════════════════════════════════════════


def compute_wacc(
    rf: float = DEFAULT_RF,
    erp: float = DEFAULT_ERP,
    beta: float = DEFAULT_BETA,
    cost_of_debt_pretax: float = 0.045,
    target_debt_ratio: float = 0.30,
    tax: float = DEFAULT_TAX,
) -> dict:
    """CAPM 股权成本 + 税后债务成本 → WACC。"""
    cost_of_equity = rf + beta * erp
    after_tax_kd = cost_of_debt_pretax * (1 - tax)
    equity_weight = 1 - target_debt_ratio
    wacc = equity_weight * cost_of_equity + target_debt_ratio * after_tax_kd
    return {
        "wacc": round(wacc, 4),
        "cost_of_equity": round(cost_of_equity, 4),
        "after_tax_kd": round(after_tax_kd, 4),
        "equity_weight": equity_weight,
        "debt_weight": target_debt_ratio,
        "inputs": {
            "rf": rf,
            "erp": erp,
            "beta": beta,
            "kd_pretax": cost_of_debt_pretax,
            "tax": tax,
        },
    }


def compute_dcf(features: dict, assumptions: dict | None = None) -> dict:
    """两阶段 DCF + 5x5 敏感性表。

    需要的 features:
        - fcf_latest_yi: 最新自由现金流(亿元，缺失则近似)
        - revenue_latest_yi / net_margin / market_cap_yi
        - shares_outstanding_yi: 总股本(亿股)
        - total_debt_yi / cash_yi (可选，用于 EV→股权桥接)
    """
    a = {
        "stage1_growth": DEFAULT_STAGE1_GROWTH,
        "stage2_growth": DEFAULT_STAGE2_GROWTH,
        "stage1_years": DEFAULT_STAGE1_YEARS,
        "stage2_years": DEFAULT_STAGE2_YEARS,
        "terminal_g": DEFAULT_TERMINAL_G,
        "beta": DEFAULT_BETA,
        "tax": DEFAULT_TAX,
        "target_debt_ratio": 0.30,
    }
    a.update(assumptions or {})

    wacc_info = compute_wacc(
        beta=a["beta"],
        tax=a["tax"],
        target_debt_ratio=a["target_debt_ratio"],
    )
    wacc = wacc_info["wacc"]

    # 基期 FCF — 缺失则用 营收 × 净利率 × 0.8 近似
    fcf0 = _num(features.get("fcf_latest_yi"))
    if fcf0 <= 0:
        rev = _num(features.get("revenue_latest_yi"))
        nm = _num(features.get("net_margin")) / 100
        fcf0 = rev * nm * 0.8
    if fcf0 <= 0:
        fcf0 = _num(features.get("market_cap_yi")) * 0.05  # 兜底:5% FCF 收益率

    projected_fcf: list[float] = []
    year_labels: list[str] = []
    cur = fcf0
    for i in range(1, a["stage1_years"] + 1):
        cur *= 1 + a["stage1_growth"]
        projected_fcf.append(round(cur, 3))
        year_labels.append(f"Y{i}")
    for i in range(1, a["stage2_years"] + 1):
        cur *= 1 + a["stage2_growth"]
        projected_fcf.append(round(cur, 3))
        year_labels.append(f"Y{a['stage1_years'] + i}")

    pv_fcf = []
    for idx, fcf in enumerate(projected_fcf, start=1):
        df = 1 / (1 + wacc) ** idx
        pv_fcf.append(round(fcf * df, 3))
    pv_explicit = round(sum(pv_fcf), 3)

    terminal_fcf = projected_fcf[-1] * (1 + a["terminal_g"])
    if wacc - a["terminal_g"] <= 0:
        tv_at_end = 0
    else:
        tv_at_end = terminal_fcf / (wacc - a["terminal_g"])
    n_years = len(projected_fcf)
    tv_pv = round(tv_at_end / (1 + wacc) ** n_years, 3)

    enterprise_value = round(pv_explicit + tv_pv, 3)
    net_debt = _num(features.get("total_debt_yi")) - _num(features.get("cash_yi"))
    equity_value = round(enterprise_value - net_debt, 3)

    shares_yi = _num(features.get("shares_outstanding_yi"))
    if shares_yi <= 0:
        mc = _num(features.get("market_cap_yi"))
        px = _num(features.get("price"))
        shares_yi = mc / px if px > 0 else 1.0
    per_share = round(equity_value / shares_yi, 2) if shares_yi > 0 else 0

    cur_price = _num(features.get("price"))
    if cur_price > 0 and per_share > 0:
        safety_margin = round((per_share - cur_price) / cur_price * 100, 1)
    else:
        safety_margin = 0

    sensitivity = _sensitivity_table(
        fcf0=fcf0,
        a=a,
        net_debt=net_debt,
        shares_yi=shares_yi,
        wacc_center=wacc,
        g_center=a["terminal_g"],
    )

    return {
        "method": "DCF (2-stage + Gordon Growth terminal)",
        "wacc_breakdown": wacc_info,
        "base_fcf_yi": round(fcf0, 3),
        "projected_fcf_yi": projected_fcf,
        "pv_fcf_yi": pv_fcf,
        "year_labels": year_labels,
        "pv_explicit_yi": pv_explicit,
        "terminal_value_yi": round(tv_at_end, 3),
        "tv_pv_yi": tv_pv,
        "tv_pct_of_ev": round(tv_pv / enterprise_value * 100, 1) if enterprise_value > 0 else 0,
        "enterprise_value_yi": enterprise_value,
        "net_debt_yi": round(net_debt, 3),
        "equity_value_yi": equity_value,
        "shares_yi": round(shares_yi, 3),
        "intrinsic_per_share": per_share,
        "current_price": cur_price,
        "safety_margin_pct": safety_margin,
        "verdict": _dcf_verdict(safety_margin),
        "sensitivity_table": sensitivity,
        "assumptions": a,
        "methodology_log": [
            f"Step 1 · WACC: CAPM k_e={wacc_info['cost_of_equity'] * 100:.2f}%, 税后 k_d={wacc_info['after_tax_kd'] * 100:.2f}%, 加权 WACC={wacc * 100:.2f}%",
            f"Step 2 · 基期 FCF={fcf0:.2f} 亿",
            f"Step 3 · 两段增长 {a['stage1_growth'] * 100:.0f}% ({a['stage1_years']}年) → {a['stage2_growth'] * 100:.0f}% ({a['stage2_years']}年)",
            f"Step 4 · 显式期 PV 合计 {pv_explicit:.1f} 亿",
            f"Step 5 · 终值 @ g={a['terminal_g'] * 100:.1f}% → PV={tv_pv:.1f} 亿(占 EV {round(tv_pv / enterprise_value * 100, 0) if enterprise_value > 0 else 0:.0f}%)",
            f"Step 6 · EV {enterprise_value:.1f} 亿 − 净债 {net_debt:.1f} 亿 = 股权价值 {equity_value:.1f} 亿",
            f"Step 7 · 每股内在价值 ¥{per_share:.2f}(当前价 ¥{cur_price:.2f}，安全边际 {safety_margin:+.1f}%)",
        ],
    }


def _sensitivity_table(fcf0, a, net_debt, shares_yi, wacc_center, g_center) -> dict:
    """5x5 敏感性:WACC(行) × 终值增长(列)。"""
    wacc_row = [
        wacc_center - 0.02,
        wacc_center - 0.01,
        wacc_center,
        wacc_center + 0.01,
        wacc_center + 0.02,
    ]
    g_col = [
        g_center - 0.01,
        g_center - 0.005,
        g_center,
        g_center + 0.005,
        g_center + 0.01,
    ]

    rows = []
    for w in wacc_row:
        row = []
        for g in g_col:
            cur = fcf0
            proj = []
            for _ in range(a["stage1_years"]):
                cur *= 1 + a["stage1_growth"]
                proj.append(cur)
            for _ in range(a["stage2_years"]):
                cur *= 1 + a["stage2_growth"]
                proj.append(cur)
            pv_exp = sum(f / (1 + w) ** (i + 1) for i, f in enumerate(proj))
            tv = proj[-1] * (1 + g) / (w - g) if w - g > 0 else 0
            tv_pv = tv / (1 + w) ** len(proj)
            ev = pv_exp + tv_pv
            eq = ev - net_debt
            ps = eq / shares_yi if shares_yi > 0 else 0
            row.append(round(ps, 2))
        rows.append(row)
    return {
        "wacc_axis": [f"{round(w * 100, 1)}%" for w in wacc_row],
        "g_axis": [f"{round(g * 100, 1)}%" for g in g_col],
        "values_per_share": rows,
        "center_cell": rows[2][2],
    }


def _dcf_verdict(safety_margin: float) -> str:
    if safety_margin >= 30:
        return "🟢 深度低估 — 安全边际充足"
    if safety_margin >= 15:
        return "🟡 略微低估 — 可关注"
    if safety_margin >= -15:
        return "⚪ 基本合理"
    if safety_margin >= -30:
        return "🟠 略微高估"
    return "🔴 明显高估"


# ═══════════════════════════════════════════════════════════════
# 2. COMPS
# ═══════════════════════════════════════════════════════════════


def build_comps_table(target: dict, peers: list[dict]) -> dict:
    """同业倍数对标(中位/分位 + 隐含价)。

    每个 dict 可含: name, ticker, pe, pb, ps, ev_ebitda, ev_sales,
    roe, net_margin, revenue_growth, market_cap_yi。
    """
    if not peers:
        return {"error": "no peers provided", "target": target}

    metrics = [
        "pe",
        "pb",
        "ps",
        "ev_ebitda",
        "ev_sales",
        "roe",
        "net_margin",
        "revenue_growth",
    ]

    import statistics

    stats: dict[str, dict] = {}
    for m in metrics:
        values = [_num(p.get(m)) for p in peers if _num(p.get(m)) > 0]
        if not values:
            continue
        stats[m] = {
            "min": round(min(values), 2),
            "p25": round(
                statistics.quantiles(values, n=4)[0] if len(values) > 1 else values[0],
                2,
            ),
            "median": round(statistics.median(values), 2),
            "p75": round(
                statistics.quantiles(values, n=4)[2] if len(values) > 1 else values[0],
                2,
            ),
            "max": round(max(values), 2),
            "mean": round(sum(values) / len(values), 2),
            "n": len(values),
        }

    target_pct: dict[str, float] = {}
    for m, s in stats.items():
        tv = _num(target.get(m))
        if tv <= 0:
            continue
        values = sorted([_num(p.get(m)) for p in peers if _num(p.get(m)) > 0])
        rank = sum(1 for v in values if v < tv)
        target_pct[m] = round(rank / len(values) * 100, 0) if values else 50

    cur_px = _num(target.get("price"))
    implied = {}
    if stats.get("pe") and target.get("eps"):
        implied["via_median_pe"] = round(stats["pe"]["median"] * _num(target.get("eps")), 2)
    if stats.get("pb") and target.get("bvps"):
        implied["via_median_pb"] = round(stats["pb"]["median"] * _num(target.get("bvps")), 2)

    pe_pct = target_pct.get("pe", 50)
    if pe_pct <= 25:
        val_verdict = "🟢 便宜(PE 低于 75% 同行)"
    elif pe_pct <= 50:
        val_verdict = "🟡 合理偏低"
    elif pe_pct <= 75:
        val_verdict = "⚪ 合理偏高"
    else:
        val_verdict = "🔴 昂贵(PE 高于 75% 同行)"

    return {
        "method": "Comparable Company Analysis (peer multiples)",
        "target": target,
        "peers": peers,
        "peer_stats": stats,
        "target_percentile": target_pct,
        "implied_price": implied,
        "current_price": cur_px,
        "valuation_verdict": val_verdict,
        "methodology_log": [
            f"Step 1 · 同行池 n={len(peers)}",
            f"Step 2 · PE 中位数 {stats.get('pe', {}).get('median', '-')}，目标 PE {target.get('pe', '-')}",
            f"Step 3 · 目标 PE 分位 {pe_pct}%",
            f"Step 4 · 隐含价 (中位 PE × EPS) = ¥{implied.get('via_median_pe', '-')}",
            f"Step 5 · 结论: {val_verdict}",
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 3. 三表预测(5 年)
# ═══════════════════════════════════════════════════════════════


def project_three_stmt(features: dict, assumptions: dict | None = None) -> dict:
    """简化版 5 年 利润表/资产负债表/现金流量表 预测(内部联动)。"""
    a = {
        "revenue_growth_y1": 0.12,
        "revenue_growth_y2": 0.10,
        "revenue_growth_y3": 0.08,
        "revenue_growth_y4": 0.06,
        "revenue_growth_y5": 0.05,
        "gross_margin": 0.35,
        "opex_pct_revenue": 0.18,
        "tax_rate": DEFAULT_TAX,
        "capex_pct_revenue": 0.05,
        "dep_pct_revenue": 0.04,
        "nwc_pct_revenue": 0.10,
    }
    a.update(assumptions or {})

    rev0 = _num(features.get("revenue_latest_yi"))
    if rev0 <= 0:
        return {"error": "no base revenue", "methodology_log": ["缺少基期营收"]}

    years = ["Y1", "Y2", "Y3", "Y4", "Y5"]
    growth = [
        a["revenue_growth_y1"],
        a["revenue_growth_y2"],
        a["revenue_growth_y3"],
        a["revenue_growth_y4"],
        a["revenue_growth_y5"],
    ]

    rev, cogs, gross, opex, ebit, tax, ni = [], [], [], [], [], [], []
    prev_rev = rev0
    for g in growth:
        r = prev_rev * (1 + g)
        c = r * (1 - a["gross_margin"])
        gp = r - c
        op = r * a["opex_pct_revenue"]
        e = gp - op
        t = e * a["tax_rate"]
        n = e - t
        rev.append(round(r, 2))
        cogs.append(round(c, 2))
        gross.append(round(gp, 2))
        opex.append(round(op, 2))
        ebit.append(round(e, 2))
        tax.append(round(t, 2))
        ni.append(round(n, 2))
        prev_rev = r

    dep = [round(r * a["dep_pct_revenue"], 2) for r in rev]
    capex = [round(r * a["capex_pct_revenue"], 2) for r in rev]
    nwc_chg = [round((rev[i] - (rev[i - 1] if i > 0 else rev0)) * a["nwc_pct_revenue"], 2) for i in range(len(rev))]
    ocf = [round(ni[i] + dep[i] - nwc_chg[i], 2) for i in range(len(rev))]
    fcf = [round(ocf[i] - capex[i], 2) for i in range(len(rev))]

    equity0 = _num(features.get("equity_yi"))
    if equity0 <= 0:
        equity0 = _num(features.get("market_cap_yi")) / max(_num(features.get("pb")) or 2.0, 0.1)
    equity_series = []
    eq = equity0
    for n in ni:
        eq = eq + n
        equity_series.append(round(eq, 2))

    return {
        "method": "3-Statement Projection (5-year, linked)",
        "years": years,
        "income_statement": {
            "revenue": rev,
            "cogs": cogs,
            "gross_profit": gross,
            "opex": opex,
            "ebit": ebit,
            "tax": tax,
            "net_income": ni,
        },
        "cash_flow": {
            "net_income": ni,
            "dep_amort": dep,
            "nwc_change": nwc_chg,
            "ocf": ocf,
            "capex": capex,
            "fcf": fcf,
        },
        "balance_sheet": {"equity_rollforward": equity_series},
        "assumptions": a,
        "growth_path": [f"{g * 100:.0f}%" for g in growth],
        "methodology_log": [
            f"Step 1 · 基期营收 {rev0:.1f} 亿 · 5 年增速 {[f'{g * 100:.0f}%' for g in growth]}",
            f"Step 2 · 毛利率 {a['gross_margin'] * 100:.0f}% · 运营费率 {a['opex_pct_revenue'] * 100:.0f}%",
            f"Step 3 · Y5 营收 {rev[-1]:.1f} 亿 · 净利 {ni[-1]:.1f} 亿",
            f"Step 4 · 5 年累计 FCF {sum(fcf):.1f} 亿",
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 4. QUICK LBO
# ═══════════════════════════════════════════════════════════════


def quick_lbo(
    features: dict,
    entry_multiple: float = 8.0,
    debt_multiple: float = 5.0,
    exit_multiple: float = 8.0,
    hold_years: int = 5,
    ebitda_growth: float = 0.08,
    interest_rate: float = 0.06,
) -> dict:
    """PE 风格快速 LBO 检验:标准杠杆下买方能否赚 20%+ IRR(作为估值交叉验证锚)。"""
    ebitda = _num(features.get("ebitda_yi"))
    if ebitda <= 0:
        rev = _num(features.get("revenue_latest_yi"))
        nm = _num(features.get("net_margin")) / 100
        ni = rev * nm
        ebitda = ni / 0.6 if ni > 0 else rev * 0.15

    entry_ev = entry_multiple * ebitda
    entry_debt = debt_multiple * ebitda
    entry_equity = entry_ev - entry_debt

    path = []
    cur = ebitda
    for _ in range(1, hold_years + 1):
        cur *= 1 + ebitda_growth
        path.append(round(cur, 2))

    debt = entry_debt
    debt_schedule = [round(debt, 2)]
    for y_ebitda in path:
        interest = debt * interest_rate
        fcf = y_ebitda * 0.5 - interest
        paydown = max(0, fcf * 0.7)
        debt = max(0, debt - paydown)
        debt_schedule.append(round(debt, 2))

    exit_ebitda = path[-1]
    exit_ev = exit_multiple * exit_ebitda
    exit_debt = debt_schedule[-1]
    exit_equity = exit_ev - exit_debt

    if entry_equity > 0 and exit_equity > 0:
        moic = exit_equity / entry_equity
        irr = moic ** (1 / hold_years) - 1
    else:
        moic = 0
        irr = 0

    return {
        "method": "Quick LBO Test",
        "entry_ebitda_yi": round(ebitda, 2),
        "entry_multiple": entry_multiple,
        "entry_ev_yi": round(entry_ev, 2),
        "entry_debt_yi": round(entry_debt, 2),
        "entry_equity_yi": round(entry_equity, 2),
        "leverage_turns": debt_multiple,
        "ebitda_path": path,
        "debt_schedule": debt_schedule,
        "exit_ebitda_yi": round(exit_ebitda, 2),
        "exit_multiple": exit_multiple,
        "exit_ev_yi": round(exit_ev, 2),
        "exit_equity_yi": round(exit_equity, 2),
        "moic": round(moic, 2),
        "irr_pct": round(irr * 100, 1),
        "pass_pe_test": irr >= 0.20,
        "verdict": "🟢 PE 买方可赚 20%+ IRR"
        if irr >= 0.20
        else ("🟡 PE 买方 15-20% IRR" if irr >= 0.15 else "🔴 低于 PE 收益门槛"),
        "methodology_log": [
            f"Step 1 · 入场 EBITDA {ebitda:.1f} 亿 × {entry_multiple}x = EV {entry_ev:.1f} 亿",
            f"Step 2 · {debt_multiple}x 杠杆 → 债 {entry_debt:.1f} 亿 + 股本 {entry_equity:.1f} 亿",
            f"Step 3 · {hold_years} 年 {ebitda_growth * 100:.0f}% 成长 → Y{hold_years} EBITDA {exit_ebitda:.1f} 亿",
            f"Step 4 · 退出 {exit_multiple}x × {exit_ebitda:.1f} = {exit_ev:.1f} 亿 EV",
            f"Step 5 · 退出股权 {exit_equity:.1f} / 入场股权 {entry_equity:.1f} = {moic:.2f}x MOIC ({irr * 100:.1f}% IRR)",
        ],
    }


# ═══════════════════════════════════════════════════════════════
# 5. 并购 / 增厚-摊薄
# ═══════════════════════════════════════════════════════════════


def accretion_dilution(
    acquirer: dict,
    target: dict,
    premium_pct: float = 0.30,
    cash_pct: float = 0.50,
    synergies_yi: float = 0.0,
    new_debt_rate: float = 0.05,
) -> dict:
    """并购模型 — pro-forma EPS 增厚/摊薄。

    每个 dict: name, shares_yi, price, eps, pe, net_income_yi。
    """
    a_px = _num(acquirer.get("price"))
    a_shares = _num(acquirer.get("shares_yi"))
    a_eps = _num(acquirer.get("eps"))
    a_ni = _num(acquirer.get("net_income_yi"))

    t_px = _num(target.get("price"))
    t_shares = _num(target.get("shares_yi"))
    t_ni = _num(target.get("net_income_yi"))

    offer_px = t_px * (1 + premium_pct)
    equity_value = offer_px * t_shares
    cash_needed = equity_value * cash_pct
    stock_needed = equity_value * (1 - cash_pct)

    new_shares_issued = stock_needed / a_px if a_px > 0 else 0
    after_shares = a_shares + new_shares_issued

    after_tax_interest = cash_needed * new_debt_rate * (1 - DEFAULT_TAX)
    pro_forma_ni = a_ni + t_ni + synergies_yi - after_tax_interest
    pro_forma_eps = pro_forma_ni / after_shares if after_shares > 0 else 0

    accretion = (pro_forma_eps - a_eps) / a_eps * 100 if a_eps > 0 else 0

    return {
        "method": "Accretion/Dilution",
        "offer_price": round(offer_px, 2),
        "equity_value_yi": round(equity_value, 2),
        "cash_portion_yi": round(cash_needed, 2),
        "stock_portion_yi": round(stock_needed, 2),
        "new_shares_issued_yi": round(new_shares_issued, 3),
        "pro_forma_shares_yi": round(after_shares, 3),
        "pro_forma_ni_yi": round(pro_forma_ni, 2),
        "pro_forma_eps": round(pro_forma_eps, 3),
        "standalone_eps": round(a_eps, 3),
        "accretion_pct": round(accretion, 1),
        "verdict": "🟢 增厚" if accretion > 3 else ("⚪ 中性" if -3 <= accretion <= 3 else "🔴 摊薄"),
        "methodology_log": [
            f"Step 1 · 报价 ¥{offer_px:.2f}(溢价 {premium_pct * 100:.0f}%)→ 总对价 {equity_value:.1f} 亿",
            f"Step 2 · 现金 {cash_pct * 100:.0f}% = {cash_needed:.1f} 亿; 换股 {stock_needed:.1f} 亿 → 新增 {new_shares_issued:.2f} 亿股",
            f"Step 3 · 合并 NI = {a_ni:.1f} + {t_ni:.1f} + 协同 {synergies_yi:.1f} − 利息 {after_tax_interest:.1f} = {pro_forma_ni:.1f}",
            f"Step 4 · Pro-forma EPS = {pro_forma_eps:.3f}(vs 独立 {a_eps:.3f}，{'增厚' if accretion > 0 else '摊薄'} {abs(accretion):.1f}%)",
        ],
    }
