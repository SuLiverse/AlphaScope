"""端到端验证：news + fund_flow + 4 Agent 并行 + 主席总结"""

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
from llm_agents import run_all_agents, summarize_with_chairman


def e2e(stock_name, symbol):
    print(f"\n{'=' * 70}\n端到端测试: {stock_name} ({symbol})\n{'=' * 70}")
    t0 = time.time()

    # 1. 新闻
    em = fetch_telegraph_em(limit=200)
    cls = fetch_telegraph_cls(limit=30)
    related = get_stock_related_news(stock_name, em + cls, limit=8)
    reports = fetch_research_report(symbol, limit=10)

    # 2. 资金流向
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

    t1 = time.time()
    print(f"[数据准备] 用时 {t1 - t0:.1f}s")
    print(f"  - 个股新闻 {len(related)} 条")
    print(f"  - 研报 {len(reports)} 份")
    print(f"  - 个股资金: 近5日主力 {s_stock.get('main_total_yi', 0):+.2f} 亿")
    print(f"  - 大盘资金: 近5日主力 {s_market.get('main_total_yi', 0):+.0f} 亿")

    print("\n[4 Agent 并行推理...]")
    res = run_all_agents(payload)
    t2 = time.time()
    print(f"[推理完成] 用时 {t2 - t1:.1f}s\n")

    for k in ["fundamental", "technical", "sentiment", "risk"]:
        if k in res["agents"]:
            r = res["agents"][k]
            print(f"  {r['name']:30s} {r['signal']} ({r['confidence']}%)")
            print(f"    └ {r['reason']}")

    print(
        f"\n[投票] 买{res['summary']['buy']} / 卖{res['summary']['sell']} / 观{res['summary']['hold']} | 均值 {res['summary']['avg_confidence']:.0f}% | 决策: {res['summary']['final']}"
    )

    print("\n[主席总结]")
    print(summarize_with_chairman(res, stock_name))


if __name__ == "__main__":
    e2e("贵州茅台", "600519")
