"""watchlist_store CRUD 往返 + 去重 + 并发测试。

watchlist_store 是本轮 DB 锁改造的高频 store(API + 后台告警扫描依赖), 此前零测试。
用真实 Database 单例 + 唯一测试 symbol, 末尾清理不污染开发库。锁住 add/list/remove/
去重 + 并发不抛 database is locked。
"""

from __future__ import annotations

import threading

from backend import watchlist_store

_TEST_SYM_PREFIX = "WL_TEST_"


def _cleanup():
    """清掉所有测试 symbol(前缀), 避免污染开发库。"""
    for item in watchlist_store.list_watchlist():
        if item["symbol"].startswith(_TEST_SYM_PREFIX):
            watchlist_store.remove_watchlist(item["symbol"])


def test_add_list_remove_roundtrip():
    _cleanup()
    sym = f"{_TEST_SYM_PREFIX}1"
    watchlist_store.add_watchlist(sym, "测试股A")
    items = watchlist_store.list_watchlist()
    assert any(i["symbol"] == sym and i["name"] == "测试股A" for i in items)

    # remove 后不再出现
    watchlist_store.remove_watchlist(sym)
    items = watchlist_store.list_watchlist()
    assert all(i["symbol"] != sym for i in items)
    _cleanup()


def test_add_dedupe_by_symbol_updates_name():
    """同 symbol 再次 add 走 ON CONFLICT 更新 name, 不产生重复行。"""
    _cleanup()
    sym = f"{_TEST_SYM_PREFIX}2"
    watchlist_store.add_watchlist(sym, "旧名")
    watchlist_store.add_watchlist(sym, "新名")
    items = [i for i in watchlist_store.list_watchlist() if i["symbol"] == sym]
    assert len(items) == 1  # 去重, 不重复
    assert items[0]["name"] == "新名"  # name 被更新
    _cleanup()


def test_add_empty_symbol_noop():
    """空 symbol 不写入(add_watchlist 内部 strip 后早退)。"""
    _cleanup()
    before = len(watchlist_store.list_watchlist())
    watchlist_store.add_watchlist("", "空")
    watchlist_store.add_watchlist("   ", "空白")
    after = len(watchlist_store.list_watchlist())
    assert after == before  # 没新增
    _cleanup()


def test_concurrent_adds_no_lock_error():
    """4 线程并发 add + 主线程并发 list: transaction() 锁应串行化, 不抛 database is locked。"""
    _cleanup()
    errors: list[str] = []

    def writer(tid: int):
        try:
            for i in range(20):
                watchlist_store.add_watchlist(f"{_TEST_SYM_PREFIX}C{tid}_{i}", f"并发{tid}-{i}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer-{tid}: {e}")

    def reader():
        try:
            for _ in range(40):
                watchlist_store.list_watchlist()
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader: {e}")

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _cleanup()
    assert errors == [], f"并发访问抛错(锁未生效?): {errors}"
