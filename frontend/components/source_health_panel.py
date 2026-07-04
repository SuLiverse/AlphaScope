"""数据源健康度面板 (v0.15)

在 Dashboard 中展示:
- Provider 健康状态表 (区分内置/自定义)
- 采集日志统计
- RAG 索引状态
"""

from __future__ import annotations

import logging

import streamlit as st
import pandas as pd

logger = logging.getLogger(__name__)


def render_source_health_panel():
    """渲染数据源健康度 Tab"""
    st.subheader("📊 数据源平台健康度")

    # ---- Provider 健康状态 ----
    st.markdown("### 🔌 Provider 状态")
    try:
        from backend.observability.source_health import SourceHealthMonitor
        from backend.providers.registry import get_registry

        monitor = SourceHealthMonitor()
        report = monitor.get_health_report()

        # 获取 provider 列表 (含 origin 信息)
        registry = get_registry()
        providers_info = registry.list_providers()
        origin_map = {p["name"]: p["origin"] for p in providers_info}

        custom_count = sum(1 for p in providers_info if p["origin"] == "custom")

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("总计", report["total"])
        col2.metric("健康", report["healthy"])
        col3.metric("降级", report["degraded"])
        col4.metric("不可用", report["unhealthy"])
        col5.metric("自定义", custom_count)

        if report.get("providers"):
            rows = []
            for p in report["providers"]:
                status_icon = {
                    "healthy": "🟢",
                    "degraded": "🟡",
                    "unhealthy": "🔴",
                }.get(p["status"], "⚪")
                latency = f"{p['avg_latency_ms']:.0f}ms" if p["avg_latency_ms"] > 0 else "N/A"
                origin = origin_map.get(p["name"], "unknown")
                origin_icon = "📦" if origin == "builtin" else "🔧"
                rows.append(
                    {
                        "状态": status_icon,
                        "来源": origin_icon,
                        "Provider": p["name"],
                        "延迟": latency,
                        "连续失败": p["consecutive_failures"],
                        "错误": p.get("error", "")[:50] if p.get("error") else "",
                    }
                )
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无 Provider 注册")

        # ---- 重新加载按钮 ----
        if st.button("🔄 重新加载 Provider", help="重新扫描 providers/ 和 custom_providers/ 目录"):
            registry.reload()
            st.success(f"Provider 已重新加载, 共 {len(registry.list_providers())} 个")
            st.rerun()

    except Exception as e:
        st.error(f"获取 Provider 状态失败: {e}")

    # ---- 采集日志统计 ----
    st.markdown("### 📋 最近采集日志")
    try:
        from backend.storage.db import Database

        db = Database()
        cur = db.conn.cursor()
        cur.execute(
            """SELECT source, endpoint, status, latency_ms, items_count,
                      error_message, started_at, finished_at
               FROM source_fetch_logs
               ORDER BY id DESC LIMIT 20"""
        )
        rows = cur.fetchall()
        if rows:
            df = pd.DataFrame([dict(r) for r in rows])
            # 格式化延迟
            if "latency_ms" in df.columns:
                df["latency_ms"] = df["latency_ms"].apply(lambda x: f"{x:.0f}ms" if x else "N/A")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("暂无采集日志 (调度器未运行或尚未采集数据)")

        # 统计汇总
        cur.execute(
            """SELECT source,
                      COUNT(*) as total,
                      SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
                      SUM(items_count) as items,
                      AVG(latency_ms) as avg_latency
               FROM source_fetch_logs
               GROUP BY source"""
        )
        stats = cur.fetchall()
        if stats:
            st.markdown("#### 📈 采集统计")
            df_stats = pd.DataFrame([dict(r) for r in stats])
            if "avg_latency" in df_stats.columns:
                df_stats["avg_latency"] = df_stats["avg_latency"].apply(lambda x: f"{x:.0f}ms" if x else "N/A")
            if "success_rate" not in df_stats.columns and "total" in df_stats.columns:
                df_stats["success_rate"] = df_stats.apply(
                    lambda r: f"{r['success'] / max(r['total'], 1) * 100:.0f}%" if r.get("total") else "N/A",
                    axis=1,
                )
            st.dataframe(df_stats, use_container_width=True, hide_index=True)

    except Exception as e:
        st.warning(f"获取采集日志失败: {e}")

    # ---- RAG 索引状态 ----
    st.markdown("### 🧠 RAG 向量索引")
    try:
        from backend.rag.vector_store import VectorStore

        store = VectorStore()
        stats = store.get_collection_stats()
        if stats:
            rows = [{"Collection": name, "文档数": count} for name, count in stats.items()]
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)
            total = sum(stats.values())
            st.caption(f"共 {len(stats)} 个 collection, {total} 个文档块")
        else:
            st.info("RAG 索引为空 (数据尚未入库)")
    except Exception as e:
        st.warning(f"获取 RAG 状态失败: {e}")

    # ---- 数据库状态 ----
    st.markdown("### 💾 数据库状态")
    try:
        from backend.storage.db import Database, DB_PATH

        db = Database()
        tables = [
            ("news_items", "新闻"),
            ("research_reports", "研报"),
            ("announcements", "公告"),
            ("price_bars", "行情"),
            ("source_fetch_logs", "采集日志"),
            ("evidence_items", "证据"),
        ]
        rows = []
        for table_name, label in tables:
            try:
                cur = db.conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cur.fetchone()[0]
                rows.append({"表": f"{label} ({table_name})", "记录数": count})
            except Exception:
                rows.append({"表": f"{label} ({table_name})", "记录数": 0})
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"数据库路径: {DB_PATH}")
    except Exception as e:
        st.warning(f"获取数据库状态失败: {e}")


def render_trust_badge(source: str) -> str:
    """为数据源渲染可信度徽标"""
    try:
        from backend.quality.source_rank import SourceRanker

        ranker = SourceRanker()
        level = ranker.get_trust_level(source)
        badge_map = {
            "S": "🟢 S",
            "A": "🔵 A",
            "B": "🟡 B",
            "C": "🟠 C",
            "D": "🔴 D",
        }
        return badge_map.get(level, "⚪ ?")
    except Exception:
        return "⚪ ?"
