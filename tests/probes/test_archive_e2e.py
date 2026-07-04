"""端到端验证：news + fund_flow + 5 Agent (异构模型) + 主席 + 自动存档（含模型组合元数据）"""

import time

from news_data import (
    fetch_telegraph_em,
    fetch_telegraph_cls,
    fetch_research_report,
    get_stock_related_news,
    build_news_brief_for_llm,
    build_research_brief_for_llm,
)
from fund_flow import (
    fetch_individual_fund_flow,
    fetch_market_fund_flow,
    summarize_fund_flow,
    build_fund_flow_brief_for_llm,
)
from llm_agents import run_all_agents, summarize_with_chairman, get_agent_model_table
from archive import save_report, list_reports, get_stats, get_combo_stats


def e2e_with_archive(stock_name, symbol):
    print(f"\n{'=' * 70}\n端到端 + 存档测试: {stock_name} ({symbol}) v0.5 异构\n{'=' * 70}")

    print("[模型阵容]")
    for k, name, vendor, model in get_agent_model_table():
        print(f"  {name:<24} → {vendor}/{model}")
    print()

    t0 = time.time()

    em = fetch_telegraph_em(limit=200)
    cls = fetch_telegraph_cls(limit=30)
    related = get_stock_related_news(stock_name, em + cls, limit=8)
    reports = fetch_research_report(symbol, limit=10)

    df_stock = fetch_individual_fund_flow(symbol, days=30)
    df_market = fetch_market_fund_flow(days=30)
    s_stock = summarize_fund_flow(df_stock, recent_days=5) if df_stock is not None else {}
    s_market = summarize_fund_flow(df_market, recent_days=5) if df_market is not None else {}

    payload = {
        "name": stock_name,
        "symbol": symbol,
        "close": 1680.50,
        "day_change": 1.25,
        "period_change": 8.6,
        "period_high": 1750,
        "period_low": 1520,
        "days": 120,
        "ma5": "1665.30",
        "ma20": "1640.20",
        "ma60": "1620.10",
        "macd": "5.2",
        "dif": "12.3",
        "dea": "7.1",
        "rsi": "62.5",
        "volume": 28500,
        "total_amount": 350.5,
        "turnover": 0.23,
        "vol_ratio": 1.35,
        "volatility": 1.85,
        "fundamentals": "白酒龙头, 高端市占第一",
        "related_news_brief": build_news_brief_for_llm(related, max_items=8),
        "market_news_brief": build_news_brief_for_llm(em[:6], max_items=6),
        "research_brief": build_research_brief_for_llm(reports, max_items=8),
        "stock_fund_brief": build_fund_flow_brief_for_llm(s_stock, kind=stock_name) if s_stock else "",
        "market_fund_brief": build_fund_flow_brief_for_llm(s_market, kind="大盘") if s_market else "",
    }

    print(f"[1] 数据准备 用时 {time.time() - t0:.1f}s | 新闻 {len(related)} 条 | 研报 {len(reports)} 份")

    print("[2] 5 Agent (异构模型) 并行推理...")
    t1 = time.time()
    res = run_all_agents(payload, include_retail=True)
    print(f"    完成 用时 {time.time() - t1:.1f}s")

    for k in ["fundamental", "technical", "sentiment", "risk", "retail"]:
        r = res["agents"].get(k)
        if r:
            ok_flag = "OK" if r.get("ok") else "FALLBACK"
            print(f"      {r['name']:<22} [{r.get('vendor', '?')}/{r.get('model', '?')}] {ok_flag}")
            print(f"        → {r['signal']} ({r['confidence']}%)")

    summary = res["summary"]
    print(f"[3] 投票: 买{summary['buy']}/卖{summary['sell']}/观{summary['hold']} → {summary['final']}")

    print("[4] 主席总结...")
    chairman = summarize_with_chairman(res, stock_name)
    print(f"    {chairman[:120]}...")

    print("[5] 自动存档（含模型组合元数据）...")
    report_md = f"""# {stock_name}（{symbol}）AI 投研报告

> 生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")}

## 行情快照
- 收盘 ¥{payload["close"]} | 当日 {payload["day_change"]:+.2f}%

## 资金流向
{payload.get("stock_fund_brief", "")}

## Agent 观点（异构模型）
"""
    for k in ["fundamental", "technical", "sentiment", "risk", "retail"]:
        r = res["agents"].get(k)
        if r:
            report_md += f"\n### {r['name']}\n> {r.get('vendor', '?')}/{r.get('model', '?')}\n- 信号：{r['signal']} ({r['confidence']}%)\n- {r['reason']}\n"

    report_md += f"\n## 投票\n买{summary['buy']}/卖{summary['sell']}/观{summary['hold']} → **{summary['final']}**\n\n## 主席\n{chairman}\n"

    arc_res = save_report(stock_name, symbol, payload, res, chairman, report_md, dedupe_minutes=0)
    print(f"    {arc_res['reason']} → {arc_res['path']}")

    print("\n[6] 索引检查（v0.5 模型组合元数据）:")
    s = get_stats()
    print(f"    总数 {s['total']} | 股票 {s['stocks']} | 买/卖/观 {s['buy']}/{s['sell']}/{s['hold']}")
    print(f"    出现过的模型组合: {s.get('distinct_combos', 0)} | 主→兜底次数: {s.get('fallback_total', 0)}")
    print("    最近 3 条：")
    for r in list_reports(limit=3):
        print(
            f"      [{r['date']} {r['time']}] {r['stock_name']}({r['symbol']}) → {r['decision']} @{r['avg_confidence']}%"
        )
        am = r.get("agent_models", {})
        if am:
            print(f"        模型快照: {len(am)} 个 Agent，组合签名长度 {len(r.get('combo_signature', ''))} 字符")

    print("\n[7] 模型组合横向统计:")
    combos = get_combo_stats()
    for c in combos[:5]:
        sig_short = c["combo"][:80] + ("..." if len(c["combo"]) > 80 else "")
        print(f"    [{c['count']}次] 买{c['buy']}/卖{c['sell']}/观{c['hold']} 均{c['avg_confidence']}%")
        print(f"      {sig_short}")

    print(f"\n总耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    e2e_with_archive("贵州茅台", "600519")
