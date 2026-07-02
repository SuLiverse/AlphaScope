"""研究记忆 research_memory 测试 — 纯函数组 + 临时 SQLite 隔离 DB 组。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pytest

import backend.quant.research_memory as rm


# ----------------------------- 纯函数组(无需 DB) -----------------------------


class TestNormSignal:
    def test_chinese_canonical(self):
        assert rm._norm_signal("买入") == "买入"
        assert rm._norm_signal("卖出") == "卖出"
        assert rm._norm_signal("观望") == "观望"

    def test_synonyms_and_english(self):
        assert rm._norm_signal("看多") == "买入"
        assert rm._norm_signal("BUY") == "买入"
        assert rm._norm_signal("bearish") == "卖出"
        assert rm._norm_signal("hold") == "观望"

    def test_empty_or_unknown(self):
        assert rm._norm_signal("") == "未知"
        assert rm._norm_signal(None) == "未知"
        assert rm._norm_signal("强势") == "强势"  # 不识别则保留原文


class TestChangeDirection:
    def test_more_positive(self):
        assert rm._change_direction("观望", "买入") == "转积极"
        assert rm._change_direction("卖出", "观望") == "转积极"

    def test_more_cautious(self):
        assert rm._change_direction("买入", "观望") == "转谨慎"
        assert rm._change_direction("买入", "卖出") == "转谨慎"

    def test_unknown_is_adjustment(self):
        assert rm._change_direction("买入", "未知") == "调整"


class TestBuildSnapshot:
    def _result(self):
        return {
            "mode": "deep",
            "summary": {
                "final": "买入",
                "buy": 3,
                "sell": 1,
                "hold": 1,
                "avg_confidence": 68.0,
            },
            "debate": {
                "consensus": "偏看多",
                "consensus_score": 62.0,
                "divergence_level": "中",
            },
            "risk_gate": {"vetoed": False},
            "data_verification": {"overall": "ok"},
        }

    def test_maps_all_fields(self):
        snap = rm.build_snapshot(
            "600519",
            "贵州茅台",
            self._result(),
            {"close": 1720.5},
            now=datetime(2026, 6, 27, 10, 0, 0),
        )
        assert snap["symbol"] == "600519"
        assert snap["name"] == "贵州茅台"
        assert snap["signal"] == "买入"
        assert snap["confidence"] == 68.0
        assert snap["buy"] == 3 and snap["sell"] == 1 and snap["hold"] == 1
        assert snap["consensus"] == "偏看多"
        assert snap["consensus_score"] == 62.0
        assert snap["divergence"] == "中"
        assert snap["risk_vetoed"] is False
        assert snap["data_status"] == "ok"
        assert snap["close"] == 1720.5
        assert snap["mode"] == "deep"
        assert snap["snapshot_id"].startswith("600519-")

    def test_failure_safe_on_empty_result(self):
        snap = rm.build_snapshot(
            "000001", "", {}, None, now=datetime(2026, 6, 27, 10, 0, 0)
        )
        assert snap["symbol"] == "000001"
        assert snap["signal"] == "未知"
        assert snap["confidence"] == 0.0

    def test_is_meaningful_filters_empty(self):
        empty = rm.build_snapshot(
            "X", "", {}, None, now=datetime(2026, 6, 27, 10, 0, 0)
        )
        assert rm._is_meaningful(empty) is False
        full = rm.build_snapshot(
            "X", "", self._result(), None, now=datetime(2026, 6, 27, 10, 0, 0)
        )
        assert rm._is_meaningful(full) is True


def _snap(signal, conf, date):
    return {"signal": signal, "confidence": conf, "created_at": date}


class TestComputeChanges:
    def test_no_change_when_stable(self):
        snaps = [_snap("买入", 60, "2026-06-01"), _snap("买入", 65, "2026-06-02")]
        assert rm.compute_changes(snaps) == []

    def test_detects_transitions_in_order(self):
        snaps = [
            _snap("买入", 70, "2026-06-01"),
            _snap("观望", 50, "2026-06-05"),
            _snap("卖出", 40, "2026-06-10"),
        ]
        changes = rm.compute_changes(snaps)
        assert len(changes) == 2
        assert changes[0]["from"] == "买入" and changes[0]["to"] == "观望"
        assert changes[0]["direction"] == "转谨慎"
        assert changes[1]["from"] == "观望" and changes[1]["to"] == "卖出"
        assert changes[1]["to_date"] == "2026-06-10"

    def test_empty_input(self):
        assert rm.compute_changes([]) == []
        assert rm.compute_changes(None) == []


class TestSummarizeHistory:
    def test_distribution_and_changes(self):
        snaps = [
            _snap("买入", 70, "2026-06-01"),
            _snap("买入", 60, "2026-06-02"),
            _snap("观望", 50, "2026-06-03"),
        ]
        s = rm.summarize_history(snaps)
        assert s["count"] == 3
        assert s["latest_signal"] == "观望"
        assert s["signal_distribution"] == {"买入": 2, "观望": 1}
        assert s["change_count"] == 1
        assert s["avg_confidence"] == 60.0
        assert s["first_date"] == "2026-06-01"
        assert s["latest_date"] == "2026-06-03"

    def test_empty(self):
        s = rm.summarize_history([])
        assert s["count"] == 0 and s["change_count"] == 0


# ----------------------------- DB 组(临时 SQLite 隔离) -----------------------------


@pytest.fixture
def mem(tmp_path, monkeypatch):
    """把 research_memory 的 _db() 指向临时 SQLite 连接,完全隔离。
    CRUD 现在走 with _db().transaction() as conn:, 故 _FakeDB 需提供
    transaction() 上下文(单线程测试无需真锁, 直接 yield 同一连接)。"""
    from contextlib import contextmanager

    conn = sqlite3.connect(str(tmp_path / "rm.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    class _FakeDB:
        @property
        def conn(self):
            return conn

        @contextmanager
        def transaction(self):
            # 临时隔离 DB 单线程使用, 无需真锁; 直接复用同一连接。
            yield conn

    rm._ensured = False
    monkeypatch.setattr(rm, "_db", lambda: _FakeDB())
    yield rm
    rm._ensured = False
    conn.close()


def _result(final="买入", conf=68.0):
    return {
        "mode": "deep",
        "summary": {
            "final": final,
            "buy": 3,
            "sell": 1,
            "hold": 1,
            "avg_confidence": conf,
        },
        "debate": {
            "consensus": "偏看多",
            "consensus_score": 62.0,
            "divergence_level": "中",
        },
        "risk_gate": {"vetoed": False},
        "data_verification": {"overall": "ok"},
    }


class TestRecordAndTimeline:
    def test_record_then_timeline_roundtrip(self, mem):
        rid = mem.record_snapshot(
            "600519",
            "贵州茅台",
            _result("买入"),
            {"close": 1700},
            now=datetime(2026, 6, 1, 9, 0, 0),
        )
        assert rid is not None
        tl = mem.get_timeline("600519")
        assert tl["symbol"] == "600519"
        assert len(tl["snapshots"]) == 1
        assert tl["summary"]["latest_signal"] == "买入"

    def test_multiple_snapshots_track_change(self, mem):
        mem.record_snapshot(
            "600519",
            "贵州茅台",
            _result("买入"),
            {"close": 1700},
            now=datetime(2026, 6, 1, 9, 0, 0),
        )
        mem.record_snapshot(
            "600519",
            "贵州茅台",
            _result("观望"),
            {"close": 1680},
            now=datetime(2026, 6, 5, 9, 0, 0),
        )
        mem.record_snapshot(
            "600519",
            "贵州茅台",
            _result("卖出"),
            {"close": 1600},
            now=datetime(2026, 6, 9, 9, 0, 0),
        )
        tl = mem.get_timeline("600519")
        assert len(tl["snapshots"]) == 3
        assert tl["summary"]["change_count"] == 2
        # 升序:第一条是最早的买入
        assert tl["snapshots"][0]["signal"] == "买入"
        assert tl["snapshots"][-1]["signal"] == "卖出"

    def test_skips_empty_result(self, mem):
        rid = mem.record_snapshot(
            "000001", "", {}, None, now=datetime(2026, 6, 1, 9, 0, 0)
        )
        assert rid is None
        assert mem.count() == 0

    def test_record_failure_safe_on_bad_input(self, mem):
        # 不抛出, 返回 None
        assert mem.record_snapshot("", "", _result(), None) is None


class TestListSymbols:
    def test_aggregates_count_and_latest(self, mem):
        mem.record_snapshot(
            "600519",
            "茅台",
            _result("买入"),
            {"close": 1700},
            now=datetime(2026, 6, 1, 9, 0, 0),
        )
        mem.record_snapshot(
            "600519",
            "茅台",
            _result("观望"),
            {"close": 1680},
            now=datetime(2026, 6, 5, 9, 0, 0),
        )
        mem.record_snapshot(
            "000001",
            "平安",
            _result("卖出"),
            {"close": 11},
            now=datetime(2026, 6, 3, 9, 0, 0),
        )
        syms = mem.list_symbols()
        by = {s["symbol"]: s for s in syms}
        assert by["600519"]["count"] == 2
        assert by["600519"]["latest_signal"] == "观望"  # 最近一次
        assert by["000001"]["count"] == 1
        # 按最近分析倒序:600519(06-05) 在 000001(06-03) 前
        assert syms[0]["symbol"] == "600519"


class TestDeleteAndPrune:
    def test_delete_snapshot(self, mem):
        rid = mem.record_snapshot(
            "600519",
            "茅台",
            _result("买入"),
            {"close": 1700},
            now=datetime(2026, 6, 1, 9, 0, 0),
        )
        assert mem.delete_snapshot(rid) is True
        assert mem.count() == 0

    def test_delete_symbol(self, mem):
        mem.record_snapshot(
            "600519",
            "茅台",
            _result("买入"),
            {"close": 1700},
            now=datetime(2026, 6, 1, 9, 0, 0),
        )
        mem.record_snapshot(
            "600519",
            "茅台",
            _result("观望"),
            {"close": 1680},
            now=datetime(2026, 6, 5, 9, 0, 0),
        )
        assert mem.delete_symbol("600519") == 2
        assert mem.count() == 0

    def test_prune_keeps_recent(self, mem):
        for i in range(5):
            mem.record_snapshot(
                "600519",
                "茅台",
                _result("买入"),
                {"close": 1700 + i},
                now=datetime(2026, 6, 1 + i, 9, 0, 0),
            )
        mem._prune_symbol("600519", keep=3)
        assert mem.count() == 3
        tl = mem.get_timeline("600519")
        # 保留最近 3 天(06-03/04/05)
        assert tl["snapshots"][0]["created_at"].startswith("2026-06-03")
