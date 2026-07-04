"""Tests for backend.news_data — keyword expansion and NaN-safe helpers."""

import news_data

from news_data import (
    _expand_stock_keywords,
    _clean_str,
    _to_float_or_none,
    _simplify_product,
    _infer_industry_from_text,
    extract_business_terms,
    get_stock_related_news,
    get_industry_news,
    get_industry_keywords,
    get_concept_keywords,
    get_concept_news,
    build_concepts_brief_for_llm,
    build_topic_news_keywords,
    fetch_keyword_news_em,
    fetch_topic_news_em,
    merge_news_items,
    classify_announcement,
    merge_announcements,
    build_announcements_brief_for_llm,
    fetch_stock_news_em,
    _eastmoney_article_url,
    _parse_eastmoney_search_payload,
    ANN_COLORS,
)


# ---------------- _expand_stock_keywords ----------------


class TestExpandStockKeywords:
    def test_long_name_yields_full_prefix_suffix_and_symbol(self):
        kw = _expand_stock_keywords("贵州茅台", "600519")
        # 长关键词排前
        assert kw[0] == "600519"
        assert "贵州茅台" in kw
        assert "贵州" in kw
        assert "茅台" in kw

    def test_dedupe_short_name(self):
        # 名字本身就是 2 字时,不应有重复
        kw = _expand_stock_keywords("万科", "")
        assert kw == ["万科"]

    def test_strip_common_suffix_for_bank(self):
        kw = _expand_stock_keywords("招商银行", "600036")
        # 后缀剥离应给出"招商"
        assert "招商银行" in kw
        assert "招商" in kw

    def test_empty_input(self):
        assert _expand_stock_keywords("", "") == []
        assert _expand_stock_keywords("  ", None) == []  # type: ignore[arg-type]

    def test_symbol_is_string_safe(self):
        kw = _expand_stock_keywords("中国平安", 601318)  # type: ignore[arg-type]
        assert "601318" in kw


# ---------------- _clean_str / _to_float_or_none ----------------


def test_clean_str_filters_nan_and_none():
    assert _clean_str(None) == ""
    assert _clean_str("nan") == ""
    assert _clean_str("NaN") == ""
    assert _clean_str(float("nan")) == ""
    assert _clean_str("买入") == "买入"
    assert _clean_str("  买入  ") == "买入"
    assert _clean_str("", default="未评级") == "未评级"


def test_to_float_or_none_filters_nan():
    assert _to_float_or_none(None) is None
    assert _to_float_or_none(float("nan")) is None
    assert _to_float_or_none("") is None
    assert _to_float_or_none("abc") is None
    assert _to_float_or_none(1.5) == 1.5
    assert _to_float_or_none("2.3") == 2.3


def test_eastmoney_article_url_requires_numeric_code():
    assert _eastmoney_article_url("202601011234") == "http://finance.eastmoney.com/a/202601011234.html"
    assert _eastmoney_article_url("../bad") == ""
    assert _eastmoney_article_url("") == ""


def test_parse_eastmoney_search_payload_jsonp():
    payload = _parse_eastmoney_search_payload('cb({"result":{"cmsArticleWebOld":[{"title":"x"}]}});')
    assert payload["result"]["cmsArticleWebOld"][0]["title"] == "x"
    assert _parse_eastmoney_search_payload("not-json") == {}


# ---------------- get_stock_related_news ----------------


def test_related_news_matches_short_brand_name():
    news = [
        {"title": "茅台一季报靓丽", "summary": "主力净流入"},
        {"title": "比亚迪销量", "summary": ""},
        {"title": "代码 600519 异动", "summary": ""},
    ]
    hits = get_stock_related_news("贵州茅台", news, symbol="600519")
    titles = {n["title"] for n in hits}
    assert "茅台一季报靓丽" in titles
    assert "代码 600519 异动" in titles
    assert "比亚迪销量" not in titles


def test_related_news_dedupes_titles():
    dup = [{"title": "茅台公告", "summary": ""}, {"title": "茅台公告", "summary": ""}]
    hits = get_stock_related_news("贵州茅台", dup)
    assert len(hits) == 1


def test_related_news_respects_limit():
    news = [{"title": f"茅台快讯 {i}", "summary": ""} for i in range(10)]
    hits = get_stock_related_news("贵州茅台", news, limit=3)
    assert len(hits) == 3


# ---------------- classify_announcement ----------------


class TestClassifyAnnouncement:
    def test_buyback_keyword(self):
        assert classify_announcement("关于回购股份实施进展的公告") == "回购"

    def test_quarterly_report(self):
        assert classify_announcement("2026年第一季度报告") == "年报/季报"
        assert classify_announcement("2025年度报告全文") == "年报/季报"

    def test_earnings_pre_announcement(self):
        assert classify_announcement("2026年半年度业绩预增公告") == "业绩预告"

    def test_shareholder_reduction(self):
        assert classify_announcement("控股股东减持计划公告") == "减持"

    def test_pledge(self):
        assert classify_announcement("关于控股股东部分股份解除质押的公告") == "股权质押"

    def test_unlock(self):
        assert classify_announcement("首次公开发行限售股解除限售公告") == "解禁"

    def test_inquiry(self):
        assert classify_announcement("关于收到深圳证券交易所问询函的公告") == "监管问询"

    def test_priority_picks_strongest_signal(self):
        # 同时含"业绩预告"(P1) 与 "回购"(P3)时,应优先业绩预告
        assert classify_announcement("业绩预告及回购方案公告") == "业绩预告"

    def test_falls_back_to_other(self):
        assert classify_announcement("关于补选独立董事的议案") == "其他"
        assert classify_announcement("") == "其他"
        assert classify_announcement(None) == "其他"  # type: ignore[arg-type]

    def test_color_palette_covers_all_labels(self):
        # 防止后续添加分类后忘了配色
        labels = {label for label, _, _ in __import__("news_data")._ANN_RULES}
        for lbl in labels:
            assert lbl in ANN_COLORS, f"{lbl} 缺颜色"


# ---------------- merge_announcements ----------------


def test_merge_announcements_dedupes_and_sorts():
    a = [
        {"title": "回购公告", "date": "2026-05-08", "source": "巨潮"},
        {"title": "季度报告", "date": "2026-04-25", "source": "巨潮"},
    ]
    b = [
        {"title": "回购公告", "date": "2026-05-08", "source": "东财"},  # 与 a[0] 重
        {"title": "新股发行", "date": "2026-05-17", "source": "东财"},
    ]
    out = merge_announcements(a, b)
    titles = [x["title"] for x in out]
    # 去重后 3 条,按日期降序
    assert titles == ["新股发行", "回购公告", "季度报告"]
    # 第一份(巨潮)优先保留
    assert next(x for x in out if x["title"] == "回购公告")["source"] == "巨潮"


def test_merge_announcements_drops_empty_and_titleless():
    out = merge_announcements(
        [{"title": "", "date": "2026-05-17"}, {"title": "正常", "date": "2026-05-17"}],
        None,  # type: ignore[arg-type]
        [],
    )
    assert [x["title"] for x in out] == ["正常"]


def test_brief_for_llm_renders_top_n():
    items = [{"title": f"公告{i}", "category": "回购", "date": "2026-05-17"} for i in range(10)]
    brief = build_announcements_brief_for_llm(items, max_items=3)
    assert brief.count("\n") == 2  # 3 行 = 2 个换行
    assert "回购" in brief


def test_brief_for_llm_handles_empty():
    assert build_announcements_brief_for_llm([]) == "无近期公告"


# ---------------- get_industry_keywords ----------------


class TestGetIndustryKeywords:
    def test_strip_roman_suffix(self):
        assert get_industry_keywords("白酒Ⅱ") == ["白酒Ⅱ", "白酒"]
        assert get_industry_keywords("化工Ⅲ") == ["化工Ⅲ", "化工"]

    def test_no_suffix_keeps_single(self):
        assert get_industry_keywords("银行") == ["银行"]

    def test_empty_input(self):
        assert get_industry_keywords("") == []
        assert get_industry_keywords(None) == []  # type: ignore[arg-type]


# ---------------- _expand_stock_keywords with products ----------------


def test_expand_keywords_includes_products():
    kw = _expand_stock_keywords("贵州茅台", "600519", products=["茅台酒", "其他系列酒"])
    # 短产品名直接保留
    assert "茅台酒" in kw
    # 长产品名经 _simplify_product 抽取核心词后保留 4 字以内
    assert "其他系列酒" not in kw  # 5 字超过单词上限
    # 长关键词在前
    assert kw.index("茅台酒") < kw.index("茅台")


def test_expand_keywords_simplifies_long_product_descriptions():
    # 大智慧的真实主营产品名,过去被原样塞进关键词导致零命中
    kw = _expand_stock_keywords(
        "大智慧",
        "601519",
        products=[
            "金融资讯及数据PC终端服务系统",
            "证券公司综合服务系统",
            "广告及互联网业务推广服务",
        ],
    )
    # 应该出现核心词
    assert "金融资讯" in kw
    # 整段描述不应该出现
    assert "金融资讯及数据PC终端服务系统" not in kw
    # 通用词("证券""广告""互联网")不应出现
    assert "证券" not in kw
    assert "广告" not in kw
    assert "互联网" not in kw
    # 不应出现带通用前缀的"数据 X"误词
    assert "数据移动" not in kw


def test_expand_keywords_includes_industry():
    kw = _expand_stock_keywords("大智慧", "601519", industry="证券信息服务")
    assert "证券信息服务" in kw


def test_expand_keywords_strips_roman_industry_suffix():
    kw = _expand_stock_keywords("贵州茅台", "600519", industry="白酒Ⅱ")
    assert "白酒Ⅱ" in kw
    assert "白酒" in kw


def test_expand_keywords_drops_short_or_generic_products():
    """v0.10 step 3 起,产品词收窄到 3-4 字非通用核心词。"""
    kw = _expand_stock_keywords("某公司", products=["酒", "饮料", "茶"])
    # 1-2 字一律丢(避免误判)
    assert "酒" not in kw
    assert "饮料" not in kw
    assert "茶" not in kw

    # 而 3 字真实产品名仍然保留
    kw2 = _expand_stock_keywords("某公司", products=["茅台酒"])
    assert "茅台酒" in kw2


# ---------------- get_industry_news ----------------


def test_industry_news_excludes_titles_already_matched():
    news = [
        {"title": "茅台一季报", "summary": ""},
        {"title": "白酒板块全线走强", "summary": ""},
    ]
    excluded = {"茅台一季报"}  # 已被 stock-related 命中
    hits = get_industry_news("白酒Ⅱ", news, exclude_titles=excluded)
    assert [n["title"] for n in hits] == ["白酒板块全线走强"]


def test_industry_news_empty_industry_returns_empty():
    news = [{"title": "白酒板块全线走强", "summary": ""}]
    assert get_industry_news("", news) == []


def test_industry_news_handles_no_match():
    news = [{"title": "互联网监管", "summary": ""}]
    assert get_industry_news("白酒Ⅱ", news) == []


# ---------------- _simplify_product ----------------


class TestSimplifyProduct:
    def test_short_product_returned_as_is(self):
        assert _simplify_product("茅台酒") == ["茅台酒"]

    def test_long_description_collapses_to_core(self):
        out = _simplify_product("金融资讯及数据PC终端服务系统")
        # 期望抽出"金融资讯",其他段被通用词黑名单过滤掉
        assert "金融资讯" in out
        # 不应保留整段或"数据移动"这类带通用前缀的词
        assert "数据移动" not in out

    def test_drops_generic_keywords(self):
        # 全是通用词应该完全过滤
        out = _simplify_product("证券公司综合服务系统")
        for tok in out:
            assert tok not in {"证券", "公司", "服务", "系统"}
            assert not tok.startswith("证券") or tok == "证券公司综合"  # noqa
        # 实际行为:证券公司综合 6 字也不收 -> 返回空
        assert out == []

    def test_drops_segments_with_ascii(self):
        out = _simplify_product("5G通信终端")
        for tok in out:
            assert not any(c.isascii() and c.isalnum() for c in tok)

    def test_empty(self):
        assert _simplify_product("") == []
        assert _simplify_product("  ") == []

    def test_caps_at_two_tokens(self):
        # 现在保守上限是 2
        out = _simplify_product("茅台酒、五粮液、汾酒、洋河")
        assert len(out) <= 2

    def test_two_char_short_words_dropped(self):
        # 2 字过宽的词全部丢:历史上"证券""广告""互联网"会大量误中
        out = _simplify_product("证券、广告、保险")
        assert out == []


# ---------------- _infer_industry_from_text ----------------


class TestInferIndustry:
    def test_finance_keyword(self):
        assert _infer_industry_from_text("证券信息服务、大数据") == "证券信息服务"

    def test_baijiu_via_brand_map(self):
        assert _infer_industry_from_text("茅台酒及系列酒的生产与销售") == "白酒"

    def test_battery(self):
        assert _infer_industry_from_text("动力电池、储能电池") == "电池"

    def test_no_match_returns_empty(self):
        assert _infer_industry_from_text("随便一段没有匹配的文本") == ""
        assert _infer_industry_from_text("") == ""


# ---------------- fetch_stock_news_em (offline shape only) ----------------


def test_fetch_stock_news_em_handles_empty_symbol():
    """空 symbol 时不应触网,直接返回空列表。"""
    assert fetch_stock_news_em("") == []
    assert fetch_stock_news_em(None) == []  # type: ignore[arg-type]


def test_fetch_keyword_news_em_handles_empty_keyword():
    """空 keyword 时不应触网,直接返回空列表。"""
    assert fetch_keyword_news_em("") == []
    assert fetch_keyword_news_em(None) == []  # type: ignore[arg-type]


# ---------------- extract_business_terms ----------------


class TestExtractBusinessTerms:
    def test_dapuwei_real_scope(self):
        scope = (
            "数据存储技术产品、微电子芯片技术产品、智能系统产品、机器学习产品、"
            "软件产品、硬件产品、大数据产品、云存储产品、信息安全产品、"
            "计算机技术产品、网络技术产品、通信技术及系统集成产品的研发、设计、"
            "测试、销售、咨询、服务;货物及技术进出口。"
        )
        terms = extract_business_terms(scope)
        # 期望抽到这些行业级核心词
        assert "数据存储" in terms
        assert "微电子芯片" in terms
        assert "机器学习" in terms
        assert "云存储" in terms
        assert "信息安全" in terms
        # 不应抽到流程/通用噪声
        assert "技术进出口" not in terms
        assert "系统集成" not in terms
        # 无半截词或纯通用词
        for t in terms:
            assert "进出口" not in t

    def test_short_text_yields_short_list(self):
        terms = extract_business_terms("茅台酒及系列酒的生产与销售;饮料、食品的生产、销售")
        # 茅台酒、饮料、食品 都是合法核心词;通用词被过滤
        assert "茅台酒" in terms

    def test_empty_returns_empty(self):
        assert extract_business_terms("") == []
        assert extract_business_terms(None) == []  # type: ignore[arg-type]

    def test_caps_at_max_terms(self):
        long = "、".join([f"{c}{c}{c}产品" for c in "ABCDEFG"])
        # 全是 ASCII 段会被过滤,这里换成中文
        long = "、".join(
            [
                "甲甲甲",
                "乙乙乙",
                "丙丙丙",
                "丁丁丁",
                "戊戊戊",
                "己己己",
                "庚庚庚",
                "辛辛辛",
                "壬壬壬",
            ]
        )
        terms = extract_business_terms(long, max_terms=3)
        assert len(terms) <= 3


# ---------------- get_industry_news with extra_keywords ----------------


def test_industry_news_uses_extra_keywords():
    news = [
        {"title": "数据存储行业景气度回升", "summary": ""},
        {"title": "白酒板块走强", "summary": ""},
        {"title": "机器学习芯片出货", "summary": ""},
    ]
    # 行业本身只能匹配"白酒板块"
    hits_no_extra = get_industry_news("白酒", news)
    assert any("白酒" in n["title"] for n in hits_no_extra)
    # 加上 extra_keywords 后,扩展词的新闻也能召回
    hits = get_industry_news(
        "计算机设备",
        news,
        extra_keywords=["数据存储", "机器学习"],
    )
    titles = {n["title"] for n in hits}
    assert "数据存储行业景气度回升" in titles
    assert "机器学习芯片出货" in titles


# ---------------- concept news helpers ----------------


def test_concept_keywords_filters_broad_concepts_and_strips_suffix():
    concepts = [
        {"name": "融资融券"},
        {"name": "存储芯片概念"},
        {"name": "信创"},
        {"name": "AI芯片板块"},
    ]
    kws = get_concept_keywords(concepts)
    assert "融资融券" not in kws
    assert "存储芯片概念" in kws
    assert "存储芯片" in kws
    assert "信创" in kws
    assert "AI芯片" in kws


def test_concept_news_matches_and_dedupes_titles():
    concepts = [{"name": "存储芯片"}, {"name": "信创"}]
    news = [
        {"title": "存储芯片板块走强", "summary": "", "source": "东财"},
        {"title": "信创订单回暖", "summary": "", "source": "财联社"},
        {"title": "白酒板块回调", "summary": "", "source": "东财"},
        {"title": "存储芯片板块走强", "summary": "重复", "source": "新浪"},
    ]
    hits = get_concept_news(concepts, news, limit=10)
    assert [n["title"] for n in hits] == ["存储芯片板块走强", "信创订单回暖"]


def test_concept_news_respects_excluded_titles():
    concepts = [{"name": "算力"}]
    news = [
        {"title": "算力租赁需求增长", "summary": ""},
        {"title": "算力芯片供给紧张", "summary": ""},
    ]
    hits = get_concept_news(concepts, news, exclude_titles={"算力租赁需求增长"})
    assert [n["title"] for n in hits] == ["算力芯片供给紧张"]


def test_concepts_brief_includes_membership_and_news():
    concepts = [{"name": "存储芯片", "pct_chg": 2.35, "lead_stock": "大普微"}]
    news = [
        {
            "title": "存储芯片板块走强",
            "summary": "国产替代加速",
            "source": "东财",
            "datetime": "2026-05-17",
        }
    ]
    brief = build_concepts_brief_for_llm(concepts, news)
    assert "所属概念" in brief
    assert "存储芯片" in brief
    assert "+2.35%" in brief
    assert "存储芯片板块走强" in brief


def test_concepts_brief_empty_returns_empty():
    assert build_concepts_brief_for_llm([], []) == ""


# ---------------- topic news helpers ----------------


def test_merge_news_items_dedupes_and_sorts():
    a = [
        {"title": "存储芯片板块走强", "datetime": "2026-05-16 09:00", "source": "东财"},
        {"title": "信创订单回暖", "datetime": "2026-05-15 10:00", "source": "财联社"},
    ]
    b = [
        {
            "title": "存储芯片板块走强",
            "datetime": "2026-05-16 12:00",
            "source": "东财搜索",
        },
        {"title": "算力需求提升", "datetime": "2026-05-17 08:00", "source": "东财搜索"},
    ]
    merged = merge_news_items(a, b)
    assert [n["title"] for n in merged] == [
        "算力需求提升",
        "存储芯片板块走强",
        "信创订单回暖",
    ]
    assert merged[1]["source"] == "东财"


def test_build_topic_news_keywords_combines_industry_business_and_concepts():
    concepts = [{"name": "存储芯片概念"}, {"name": "信创"}, {"name": "融资融券"}]
    kws = build_topic_news_keywords(
        industry="计算机设备Ⅱ",
        business_terms=["数据存储", "机器学习"],
        concepts=concepts,
        limit=8,
    )
    assert kws[:2] == ["计算机设备Ⅱ", "计算机设备"]
    assert "数据存储" in kws
    assert "机器学习" in kws
    assert "存储芯片" in kws
    assert "信创" in kws
    assert "融资融券" not in kws


def test_fetch_topic_news_em_dedupes_keywords_and_results(monkeypatch):
    calls = []

    def fake_fetch(keyword, limit=8):
        calls.append((keyword, limit))
        return [
            {"title": f"{keyword}新闻", "datetime": "2026-05-17", "source": "东财搜索"},
            {"title": "重复新闻", "datetime": "2026-05-16", "source": "东财搜索"},
        ]

    monkeypatch.setattr(news_data, "fetch_keyword_news_em", fake_fetch)
    out = fetch_topic_news_em(["算力", "算力", "信创"], limit_each=3, total_limit=10)
    assert calls == [("算力", 3), ("信创", 3)]
    assert [n["title"] for n in out] == ["算力新闻", "信创新闻", "重复新闻"]
