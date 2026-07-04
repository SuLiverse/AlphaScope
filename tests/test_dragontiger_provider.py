"""M1 · 龙虎榜「机构 vs 游资」provider + 杀猪盘信号 测试(全程不联网)。"""

from __future__ import annotations

from backend.dragon_tiger import lhb as lhb_mod
from backend.dragon_tiger.seat_db import (
    is_in_range,
    match_seats_in_lhb,
    split_inst_vs_youzi,
)
from backend.dragon_tiger import trap_signals as trap
from backend.providers.dragontiger_provider import (
    DragonTigerProvider,
    _normalize_cn_code,
)
from backend.providers.registry import ProviderRegistry, _discover_and_register


class TestSeatDb:
    def test_match_seats_finds_youzi(self):
        rows = [
            {
                "营业部名称": "国泰君安证券股份有限公司上海江苏路证券营业部",
                "买入金额": 1e8,
            },
            {"营业部名称": "某不知名营业部", "买入金额": 1e6},
        ]
        matched = match_seats_in_lhb(rows)
        assert "章盟主" in matched
        assert len(matched["章盟主"]) == 1

    def test_match_seats_empty_when_no_hit(self):
        rows = [{"营业部名称": "完全不相关的营业部"}]
        assert match_seats_in_lhb(rows) == {}

    def test_split_inst_vs_youzi(self):
        rows = [
            {"营业部名称": "机构专用", "买入金额": 5e7, "卖出金额": 1e7},
            {
                "营业部名称": "华鑫证券有限责任公司上海红宝石路证券营业部",
                "买入金额": 2e7,
                "卖出金额": 8e6,
            },
        ]
        split = split_inst_vs_youzi(rows)
        assert split["institutional_net"] == 5e7 - 1e7
        assert split["youzi_net"] == 2e7 - 8e6

    def test_split_handles_alt_columns_and_blanks(self):
        rows = [{"交易营业部名称": "机构专用", "买入额": "30000000", "卖出额": None}]
        split = split_inst_vs_youzi(rows)
        assert split["institutional_buy"] == 3e7
        assert split["institutional_sell"] == 0.0

    def test_is_in_range_mcap_bounds(self):
        feats_ok = {"market_cap": 30_000_000_000, "trend": "up", "style_match": "trend"}
        assert is_in_range("章盟主", feats_ok) is True
        feats_small = {
            "market_cap": 10_000_000_000,
            "trend": "up",
            "style_match": "trend",
        }
        assert is_in_range("章盟主", feats_small) is False  # 低于 min_mcap 200亿

    def test_is_in_range_implicit_megacap_cap(self):
        # 孙哥无显式 max_mcap → 隐式 500 亿上限
        assert is_in_range("孙哥", {"market_cap": 60_000_000_000, "is_sector_leader": True}) is False
        # 章盟主在 allowlist，可做大盘
        assert (
            is_in_range(
                "章盟主",
                {"market_cap": 900_000_000_000, "trend": "up", "style_match": "trend"},
            )
            is True
        )


class TestTrapSignals:
    def test_scan_hits_multiple_signals(self):
        body = "必涨 强烈推荐 即将爆发 主力建仓完毕 微信群 VIP 直播间"

        def fake_search(query: str, max_results: int = 3):
            return [{"title": "t", "body": body, "url": "http://x"}]

        out = trap.scan_trap_signals("测试股份", search_fn=fake_search)
        assert out["signals_hit_count"] == 3  # signal 1 / 2 / 3
        assert "注意" in out["trap_level"]

    def test_scan_clean_when_no_promo(self):
        def fake_search(query: str, max_results: int = 3):
            return [
                {
                    "title": "正常财经新闻",
                    "body": "公司发布季度财报，营收稳健。",
                    "url": "",
                }
            ]

        out = trap.scan_trap_signals("测试股份", search_fn=fake_search)
        assert out["signals_hit_count"] == 0
        assert "安全" in out["trap_level"]

    def test_scan_without_search_fn_is_graceful(self):
        out = trap.scan_trap_signals("测试股份", search_fn=None)
        # 默认 provider 在测试环境通常不可用 → 未扫描;无论如何不应抛异常
        assert "signals_hit_count" in out


class TestProvider:
    def test_normalize_cn_code(self):
        assert _normalize_cn_code("600519") == "600519"
        assert _normalize_cn_code("sh600519") == "600519"
        assert _normalize_cn_code("000001.SZ") == "000001"
        assert _normalize_cn_code("AAPL") == ""

    def test_metadata(self):
        p = DragonTigerProvider()
        assert p.name == "dragontiger"
        assert p.markets == ["CN"]
        assert "dragon_tiger" in p.data_types

    def test_get_dragon_tiger_empty_symbol(self):
        assert DragonTigerProvider().get_dragon_tiger({"symbol": "AAPL"}) == {}

    def test_get_dragon_tiger_summary(self, monkeypatch):
        fake_records = [
            {
                "营业部名称": "国泰君安证券股份有限公司上海江苏路证券营业部",
                "买入金额": 1e8,
                "卖出金额": 2e7,
            },
            {"营业部名称": "机构专用", "买入金额": 3e7, "卖出金额": 5e7},
        ]
        monkeypatch.setattr(lhb_mod, "fetch_lhb_recent", lambda code, days=30: fake_records)
        monkeypatch.setattr(lhb_mod, "fetch_sector_lhb", lambda top=30: [])

        out = DragonTigerProvider().get_dragon_tiger({"symbol": "600519"})
        assert out["code"] == "600519"
        assert out["lhb_count_30d"] == 2
        assert "章盟主" in out["matched_youzi"]
        assert out["inst_vs_youzi"]["institutional_net"] == 3e7 - 5e7


class TestDiscovery:
    def test_registry_discovers_dragontiger(self):
        registry = ProviderRegistry()
        _discover_and_register(registry)
        names = {p["name"] for p in registry.list_providers()}
        assert "dragontiger" in names
