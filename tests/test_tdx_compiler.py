"""通达信(TDX)公式编译器与策略测试。"""

from __future__ import annotations

from datetime import datetime, timedelta


def _bars_from_closes(closes, volumes=None):
    base = datetime(2024, 1, 1)
    out = []
    for i, c in enumerate(closes):
        v = volumes[i] if volumes else 10000
        out.append(
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": c,
                "high": c + 1,
                "low": c - 1,
                "close": c,
                "volume": v,
                "symbol": "T",
            }
        )
    return out


class TestCompile:
    def test_empty_formula(self):
        from backend.quant.tdx_compiler import compile_formula

        r = compile_formula("")
        assert not r.ok and r.errors

    def test_macd_compiles(self):
        from backend.quant.tdx_compiler import compile_formula

        src = "DIFF:=EMA(CLOSE,12)-EMA(CLOSE,26);DEA:=EMA(DIFF,9);ENTERLONG:CROSS(DIFF,DEA);EXITLONG:CROSS(DEA,DIFF);"
        r = compile_formula(src)
        assert r.ok, r.errors
        assert "ENTERLONG" in r.buy_names
        assert "EXITLONG" in r.sell_names
        assert "CLOSE" in r.refs_used
        assert "DIFF" in r.var_names

    def test_unknown_function(self):
        from backend.quant.tdx_compiler import compile_formula

        r = compile_formula("ENTERLONG:FOOBAR(CLOSE,5);")
        assert not r.ok
        assert any("FOOBAR" in e for e in r.errors)

    def test_arg_count_mismatch(self):
        from backend.quant.tdx_compiler import compile_formula

        r = compile_formula("ENTERLONG:MA(CLOSE);")
        assert not r.ok
        assert any("MA" in e for e in r.errors)

    def test_no_buy_warns(self):
        from backend.quant.tdx_compiler import compile_formula

        r = compile_formula("X:=MA(CLOSE,5);")
        assert r.ok
        assert r.warnings  # 无买入信号告警

    def test_syntax_error_failsafe(self):
        from backend.quant.tdx_compiler import compile_formula

        r = compile_formula("ENTERLONG:MA(CLOSE,5)) AND ;")
        assert not r.ok  # 不抛异常,错误进 errors


class TestEvaluate:
    def test_ma_cross_generates_buy(self):
        from backend.quant.tdx_compiler import evaluate_formula

        # 先跌后涨:短均线上穿长均线 → 至少一次买入信号
        closes = [100 - i for i in range(15)] + [85 + 2 * i for i in range(25)]
        bars = _bars_from_closes(closes)
        res = evaluate_formula("ENTERLONG:CROSS(MA(CLOSE,5),MA(CLOSE,10));", bars)
        assert res.ok, res.errors
        assert any(res.buy)

    def test_ref_semantics(self):
        from backend.quant.tdx_compiler import evaluate_formula

        closes = [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]
        bars = _bars_from_closes(closes)
        # CLOSE>REF(CLOSE,1) 恒真(单调上涨), 预热首根为 NaN→False
        res = evaluate_formula("ENTERLONG:CLOSE>REF(CLOSE,1);", bars)
        assert res.ok
        assert res.buy[0] is False  # REF(,1) 首根无值
        assert all(res.buy[1:])

    def test_warmup_no_early_signal(self):
        from backend.quant.tdx_compiler import evaluate_formula

        closes = [100 + (i % 3) for i in range(40)]
        bars = _bars_from_closes(closes)
        res = evaluate_formula("ENTERLONG:CLOSE>MA(CLOSE,20);", bars)
        assert res.ok
        # MA20 预热段(前 19 根)为 NaN → 比较为 False,绝不前视
        assert not any(res.buy[:19])

    def test_hhv_llv_and_logic(self):
        from backend.quant.tdx_compiler import evaluate_formula

        closes = [10, 12, 11, 15, 9, 20, 8, 25]
        bars = _bars_from_closes(closes)
        res = evaluate_formula("ENTERLONG:CLOSE=HHV(CLOSE,3) AND CLOSE>REF(CLOSE,1);", bars)
        assert res.ok
        assert isinstance(res.buy, list) and len(res.buy) == len(closes)

    def test_empty_bars(self):
        from backend.quant.tdx_compiler import evaluate_formula

        res = evaluate_formula("ENTERLONG:CROSS(MA(CLOSE,5),MA(CLOSE,10));", [])
        assert res.ok and res.buy == []

    def test_bad_formula_no_signals(self):
        from backend.quant.tdx_compiler import evaluate_formula

        bars = _bars_from_closes([10] * 30)
        res = evaluate_formula("ENTERLONG:UNKNOWNVAR>5;", bars)
        assert not res.ok
        assert not any(res.buy)


class TestStrategy:
    def test_registered(self):
        from backend.quant.strategies import StrategyRegistry

        assert StrategyRegistry.get("tdx") is not None

    def test_empty_formula_no_signals(self):
        from backend.quant.strategies import StrategyRegistry

        strat = StrategyRegistry.create("tdx", {"formula": ""})
        bars = _bars_from_closes([10] * 30)
        sigs = strat.generate_signals(bars, {"equity": 100000})
        # 契约:与 bars 等长, 空公式整段为 hold(引擎侧等同无信号)
        assert len(sigs) == len(bars)
        assert all(s.action == "hold" for s in sigs)

    def test_signals_align_to_bars(self):
        from backend.quant.strategies import StrategyRegistry

        closes = [100 - i for i in range(15)] + [85 + 2 * i for i in range(25)]
        bars = _bars_from_closes(closes)
        strat = StrategyRegistry.create(
            "tdx",
            {
                "formula": "ENTERLONG:CROSS(MA(CLOSE,5),MA(CLOSE,10));EXITLONG:CROSS(MA(CLOSE,10),MA(CLOSE,5));",
                "position_size_pct": 20,
            },
        )
        sigs = strat.generate_signals(bars, {"equity": 1000000})
        assert len(sigs) == len(bars)
        assert {s.action for s in sigs} <= {"buy", "sell", "hold"}
        assert any(s.action == "buy" for s in sigs)

    def test_end_to_end_backtest(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import StrategyRegistry

        closes = [100 - i for i in range(15)] + [85 + 1.5 * i for i in range(35)]
        bars = _bars_from_closes(closes)
        strat = StrategyRegistry.create(
            "tdx",
            {"formula": "ENTERLONG:CROSS(MA(CLOSE,5),MA(CLOSE,10));EXITLONG:CLOSE<MA(CLOSE,5);"},
        )
        engine = BacktestEngine(initial_capital=1000000)
        result = engine.run(strat, bars, "T")
        assert "total_return" in result.performance
        assert isinstance(result.trades, list)
