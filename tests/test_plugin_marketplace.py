"""插件市场测试 / Plugin Marketplace (Phase D #2).

覆盖:
1. 目录完整性 (始终跑): list_catalog / categories 覆盖规划主要项目
2. 已装/未装区分 (始终跑): list_installed / list_not_installed 互斥且无遗漏
3. 推荐与分类筛选 (始终跑): recommend / by_category
4. 安装命令 (始终跑): install_hint
5. 概览 (始终跑): describe

合规: 测试只校验目录/分类逻辑, 不涉及买卖指令。
"""

from __future__ import annotations

from backend import plugin_marketplace as pm


# ============================================================
# 1. 目录完整性
# ============================================================


def test_list_catalog_nonempty():
    catalog = pm.list_catalog()
    assert len(catalog) >= 10  # 至少 10 个已知插件


def test_catalog_covers_core_plan_projects():
    """catalog 必须覆盖规划里的核心项目 (vectorBT/OpenBB/Qlib/TradingAgents/skfolio)。"""
    names = {p["name"] for p in pm.list_catalog()}
    required = {"vectorbt", "openbb", "qlib", "tradingagents", "skfolio", "mlflow"}
    assert required.issubset(names), f"catalog 缺失: {required - names}"


def test_catalog_entries_have_required_fields():
    """每个 catalog 条目必须有 name/category/display_name/install_hint。"""
    for p in pm.list_catalog():
        for field in (
            "name",
            "category",
            "display_name",
            "description",
            "install_hint",
            "license_safety",
        ):
            assert field in p, f"插件 {p.get('name')} 缺字段 {field}"


def test_all_licenses_are_safe_or_known():
    """catalog 里所有插件的 license_safety 应该是已知值 (safe 是主基调)。"""
    valid = {"safe", "copyleft_risk", "noncommercial", "proprietary", "unknown"}
    for p in pm.list_catalog():
        assert p["license_safety"] in valid


# ============================================================
# 2. 已装/未装区分
# ============================================================


def test_list_installed_returns_list():
    installed = pm.list_installed()
    assert isinstance(installed, list)
    # 本环境至少有 demo (registry 永远有 demo)
    names = {p["name"] for p in installed}
    assert "demo" in names


def test_installed_entries_have_health():
    installed = pm.list_installed()
    for p in installed:
        assert "health" in p
        assert "allow_live_order" in p
        # 所有已装插件必须 allow_live_order=False (No-Live-Order 边界)
        assert p["allow_live_order"] is False


def test_list_not_installed_returns_list():
    not_installed = pm.list_not_installed()
    assert isinstance(not_installed, list)


def test_installed_and_not_installed_disjoint():
    """已装与未装不应有交集 (互斥)。"""
    installed_names = {p["name"] for p in pm.list_installed()}
    not_installed_names = {p["name"] for p in pm.list_not_installed()}
    assert installed_names & not_installed_names == set()


# ============================================================
# 3. 推荐与分类筛选
# ============================================================


def test_recommend_must_have_returns_nonempty():
    must = pm.recommend("必接")
    assert len(must) >= 5  # 规划「必接」至少 5 个


def test_recommend_entries_match_priority():
    must = pm.recommend("必接")
    for p in must:
        assert p["recommended"] == "必接"


def test_by_category_filters_correctly():
    backtests = pm.by_category("backtest")
    for p in backtests:
        assert p["category"] == "backtest"
    assert len(backtests) >= 3  # vectorbt/backtrader/pybroker/bt


def test_by_category_unknown_returns_empty():
    assert pm.by_category("totally_unknown_category") == []


# ============================================================
# 4. 安装命令
# ============================================================


def test_install_hint_known_plugin():
    hint = pm.install_hint("vectorbt")
    assert hint is not None
    assert "pip install" in hint


def test_install_hint_unknown_returns_none():
    assert pm.install_hint("totally_unknown_plugin") is None


def test_install_hint_tradingagents_uses_git():
    """TradingAgents 未上 PyPI, 安装命令应是 git+。"""
    hint = pm.install_hint("tradingagents")
    assert hint is not None
    assert "git+" in hint


# ============================================================
# 5. 概览
# ============================================================


def test_describe_structure():
    info = pm.describe()
    assert "total_catalog" in info
    assert "installed_count" in info
    assert "not_installed_count" in info
    assert "categories" in info
    assert "must_have_remaining" in info
    assert isinstance(info["categories"], list)


def test_describe_counts_consistent():
    info = pm.describe()
    # installed + not_installed (catalog 里的) 应该合理
    assert info["installed_count"] >= 1  # demo 至少在


# ---------------- API 端点 ----------------


def test_marketplace_endpoint_overview():
    """GET /api/integrations/marketplace 返回概览 + 完整目录。"""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    client = TestClient(app)
    r = client.get("/api/integrations/marketplace")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "overview" in data
    assert "plugins" in data
    assert isinstance(data["plugins"], list)
    assert data["total"] == len(data["plugins"])
    # 概览含分类
    assert "categories" in data["overview"]


def test_marketplace_endpoint_category_filter():
    """GET /api/integrations/marketplace?category=X 只返回该分类。"""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    client = TestClient(app)
    # 先取一个真实分类
    all_cats = client.get("/api/integrations/marketplace").json()["data"]["overview"]["categories"]
    if not all_cats:
        return  # 无分类可测, 跳过
    cat = all_cats[0]
    r = client.get(f"/api/integrations/marketplace?category={cat}")
    assert r.status_code == 200
    plugins = r.json()["data"]["plugins"]
    assert all(p["category"] == cat for p in plugins)


def test_marketplace_route_not_swallowed_by_name_param():
    """路由顺序: /marketplace 不能被 /{name} 吞(应返回市场目录, 不是某个 adapter 详情)。"""
    from fastapi.testclient import TestClient

    from backend.api.main import app

    client = TestClient(app)
    r = client.get("/api/integrations/marketplace")
    # 若被 /{name} 吞, 会走 get_integration(name="marketplace"), 返回 adapter 详情或 404,
    # 不会有 overview/plugins 结构
    data = r.json()["data"]
    assert "plugins" in data  # 确认走的是市场端点
