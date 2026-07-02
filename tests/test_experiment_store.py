"""实验记录持久化测试 — 用临时 SQLite 连接隔离,不污染开发库。"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 experiment_store 的 _db() 指向一条临时 SQLite 连接,完全隔离。
    CRUD 现在走 with _db().transaction() as conn:, 故 _FakeDB 需提供
    transaction() 上下文(单线程测试无需真锁)。"""
    from contextlib import contextmanager

    import backend.quant.experiment_store as es

    conn = sqlite3.connect(str(tmp_path / "exp.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    class _FakeDB:
        @property
        def conn(self):
            return conn

        @contextmanager
        def transaction(self):
            yield conn

    es._ensured = False  # 强制在临时连接上建表
    monkeypatch.setattr(es, "_db", lambda: _FakeDB())
    yield es
    es._ensured = False  # 还原,后续生产用真实库重新建表
    conn.close()


def _bt_payload(run_id="bt-1", symbol="600519"):
    return {
        "run_id": run_id,
        "mode": "backtest",
        "symbol": symbol,
        "strategy_id": "ma_crossover",
        "finished_at": "2026-06-27T10:00:00",
        "metrics": {
            "total_return": 12.3,
            "sharpe_ratio": 1.5,
            "max_drawdown": -8.0,
            "win_rate": 55.0,
            "trade_count": 9,
        },
    }


def _wf_payload(run_id="wf-1"):
    return {
        "run_id": run_id,
        "mode": "walk_forward",
        "symbol": "000001",
        "strategy_name": "rsi_reversal",
        "finished_at": "2026-06-27T11:00:00",
        "n_windows": 5,
        "scheme": "anchored",
        "aggregate": {
            "consistency_score": 72.0,
            "pct_profitable_windows": 80.0,
            "mean_oos_return": 1.2,
            "robustness": "稳健（历史样本外表现较一致）",
        },
    }


class TestSaveAndGet:
    def test_save_then_get_roundtrip(self, store):
        rid = store.save_experiment(_bt_payload())
        assert rid == "bt-1"
        got = store.get_experiment("bt-1")
        assert got is not None
        assert got["mode"] == "backtest"
        assert got["metrics"]["total_return"] == 12.3

    def test_get_missing_returns_none(self, store):
        assert store.get_experiment("__nope__") is None

    def test_save_generates_run_id_when_absent(self, store):
        rid = store.save_experiment({"mode": "backtest", "metrics": {}})
        assert rid and rid.startswith("backtest-")

    def test_save_non_dict_is_failsafe(self, store):
        assert store.save_experiment(None) is None  # type: ignore[arg-type]
        assert store.save_experiment("oops") is None  # type: ignore[arg-type]


class TestListAndFilter:
    def test_list_orders_desc_and_filters(self, store):
        store.save_experiment(_bt_payload(run_id="bt-1", symbol="600519"))
        store.save_experiment(_wf_payload(run_id="wf-1"))
        store.save_experiment(_bt_payload(run_id="bt-2", symbol="600519"))

        all_rows = store.list_experiments()
        assert len(all_rows) == 3
        # 倒序:created_at 越新越靠前(wf=11:00 最新)
        assert all_rows[0]["run_id"] == "wf-1"

        only_bt = store.list_experiments(mode="backtest")
        assert {r["run_id"] for r in only_bt} == {"bt-1", "bt-2"}

        only_sym = store.list_experiments(symbol="000001")
        assert [r["run_id"] for r in only_sym] == ["wf-1"]

    def test_list_summary_is_compact(self, store):
        store.save_experiment(_wf_payload())
        row = store.list_experiments(mode="walk_forward")[0]
        assert row["summary"]["consistency_score"] == 72.0
        assert "payload" not in row  # 列表不带完整载荷

    def test_count(self, store):
        assert store.count_experiments() == 0
        store.save_experiment(_bt_payload())
        assert store.count_experiments() == 1


class TestDeleteAndCompare:
    def test_delete(self, store):
        store.save_experiment(_bt_payload())
        assert store.delete_experiment("bt-1") is True
        assert store.get_experiment("bt-1") is None
        assert store.delete_experiment("bt-1") is False  # 已删,再删返回 False

    def test_compare_collects_summaries(self, store):
        store.save_experiment(_bt_payload(run_id="bt-1"))
        store.save_experiment(_wf_payload(run_id="wf-1"))
        cmp = store.compare_experiments(["bt-1", "wf-1", "__missing__"])
        assert len(cmp) == 2  # 缺失 id 跳过
        modes = {c["mode"] for c in cmp}
        assert modes == {"backtest", "walk_forward"}
        bt = next(c for c in cmp if c["mode"] == "backtest")
        assert bt["summary"]["sharpe_ratio"] == 1.5


class TestSummarize:
    def test_summarize_per_mode(self, store):
        chip = {
            "mode": "chip_distribution",
            "model": "turnover",
            "current_price": 100.0,
            "avg_cost": 95.0,
            "profit_ratio": 80.0,
            "concentration_90": 12.0,
        }
        s = store._summarize("chip_distribution", chip)
        assert s["profit_ratio"] == 80.0 and s["model"] == "turnover"

        cmp = {
            "mode": "strategy_compare",
            "evaluated": 8,
            "rank_by": "sharpe_ratio",
            "ranking": [{"strategy_id": "momentum", "total_return": 9.5}],
        }
        s2 = store._summarize("strategy_compare", cmp)
        assert s2["top_strategy"] == "momentum" and s2["evaluated"] == 8

    def test_prune_keeps_recent(self, store):
        for i in range(5):
            store.save_experiment(
                {
                    "run_id": f"r{i}",
                    "mode": "backtest",
                    "finished_at": f"2026-06-27T10:0{i}:00",
                    "metrics": {},
                }
            )
        # keep=2 → 只剩最近两条
        store._prune(keep=2)
        rows = store.list_experiments()
        assert len(rows) == 2
        assert {r["run_id"] for r in rows} == {"r3", "r4"}
