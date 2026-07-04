"""快速测试：把真实新闻喂进 LLM 情绪 Agent"""

from news_data import (
    fetch_telegraph_em,
    fetch_telegraph_cls,
    fetch_research_report,
    get_stock_related_news,
    build_news_brief_for_llm,
    build_research_brief_for_llm,
)
from llm_agents import call_agent, build_market_brief


def test_with_news(stock_name: str, symbol: str):
    print(f"\n{'=' * 70}\n{stock_name} ({symbol}) — 含真实新闻的情绪分析测试\n{'=' * 70}")

    # 1. 抓新闻
    print("[1/3] 抓取大盘资讯...")
    em = fetch_telegraph_em(limit=200)
    cls = fetch_telegraph_cls(limit=30)
    all_news = em + cls

    # 2. 找个股相关
    related = get_stock_related_news(stock_name, all_news, limit=8)
    print(f"  → 个股相关 {len(related)} 条")

    # 3. 抓研报
    print("[2/3] 抓取研报...")
    reports = fetch_research_report(symbol, limit=10)
    print(f"  → 研报 {len(reports)} 份")

    # 4. 构造 payload
    related_brief = build_news_brief_for_llm(related, max_items=8)
    market_brief_text = build_news_brief_for_llm(em[:6], max_items=6)
    research_brief = build_research_brief_for_llm(reports, max_items=8)

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
        "related_news_brief": related_brief,
        "market_news_brief": market_brief_text,
        "research_brief": research_brief,
    }

    brief = build_market_brief(payload)
    print("\n[3/3] 调用 LLM 情绪 Agent...")
    result = call_agent("sentiment", brief)
    print(f"\n→ 信号: {result['signal']} | 置信度: {result['confidence']}%")
    print(f"→ 理由: {result['reason']}")

    print(f"\n[Brief 预览-末尾 800 字]\n...{brief[-800:]}")


if __name__ == "__main__":
    test_with_news("贵州茅台", "600519")
