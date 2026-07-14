"""研究记忆 post-mortem 注入测试。"""

from __future__ import annotations

from backend.runtime.post_mortem import build_post_mortem_brief


def test_empty_symbol_returns_empty():
    assert build_post_mortem_brief("") == ""
    assert build_post_mortem_brief("   ") == ""


def test_unknown_symbol_no_history_returns_empty():
    text = build_post_mortem_brief("__no_such_symbol_xyz__")
    assert text == ""


def test_with_mocked_timeline(monkeypatch):
    class FakeRM:
        @staticmethod
        def get_timeline(symbol, limit=8):
            return {
                "snapshots": [
                    {
                        "created_at": "2026-01-01",
                        "signal": "买入",
                        "confidence": 70,
                        "risk_vetoed": False,
                    },
                    {
                        "created_at": "2026-02-01",
                        "signal": "观望",
                        "confidence": 55,
                        "risk_vetoed": False,
                    },
                ],
                "changes": [
                    {
                        "from": "买入",
                        "to": "观望",
                        "direction": "转谨慎",
                        "to_date": "2026-02-01",
                    }
                ],
                "summary": {
                    "count": 2,
                    "latest_signal": "观望",
                    "latest_confidence": 55,
                    "signal_distribution": {"买入": 1, "观望": 1},
                    "change_count": 1,
                    "avg_confidence": 62.5,
                },
            }

    import backend.runtime.post_mortem as pm

    monkeypatch.setattr(pm, "build_post_mortem_brief", pm.build_post_mortem_brief)
    monkeypatch.setitem(__import__("sys").modules, "backend.quant.research_memory", FakeRM())

    # Re-import path uses from backend.quant import research_memory inside function
    def _fake_import():
        return FakeRM()

    import backend.quant.research_memory as real_rm

    monkeypatch.setattr(
        "backend.quant.research_memory.get_timeline",
        FakeRM.get_timeline,
    )
    text = build_post_mortem_brief("600519")
    assert "自我复盘" in text or "Post-mortem" in text
    assert "观望" in text
    assert "转折" in text
