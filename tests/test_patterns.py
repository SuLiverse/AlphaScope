"""K 线形态识别测试 (v1.9.16)。

用精心构造的确定性 OHLCV 夹具触发各形态:吞没/锤子/十字星/红三兵/三只乌鸦/
跳空/突破/金叉/双底,以及样本不足与失败安全。全部离线、确定性。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.quant.patterns import detect_patterns


def _d(i: int) -> str:
    return (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")


def _bar(i, o, h, lo, c):
    return {"date": _d(i), "open": o, "high": h, "low": lo, "close": c, "volume": 10000}


def _flat(i, c):
    return _bar(i, c, c + 0.1, c - 0.1, c)


def _names(report):
    return [p.name for p in report.patterns]


class TestInsufficientAndFailSafe:
    def test_insufficient(self):
        r = detect_patterns([_flat(0, 10), _flat(1, 10), _flat(2, 10)], "T")
        assert r.status == "insufficient"
        assert r.patterns == []

    def test_empty_never_raises(self):
        r = detect_patterns([], "T")
        assert r.status == "insufficient"

    def test_garbage_never_raises(self):
        r = detect_patterns([{"x": 1}, "junk", None, 123], "T")  # type: ignore[list-item]
        assert r.status == "insufficient"


class TestCandlestick:
    def test_bullish_engulfing(self):
        bars = [
            _flat(0, 11),
            _flat(1, 10.5),
            _bar(2, 10.0, 10.2, 8.8, 9.0),  # 阴线
            _bar(3, 8.9, 10.3, 8.8, 10.1),  # 阳线吞没
        ]
        # 补足到 >=5 根
        bars = [_flat(-2 + 0, 11.5), _flat(-1 + 1, 11.2)] + bars
        r = detect_patterns(bars, "T")
        assert "看涨吞没" in _names(r)

    def test_bearish_engulfing(self):
        bars = [
            _flat(0, 8.5),
            _flat(1, 9.0),
            _flat(2, 9.5),
            _bar(3, 10.0, 11.2, 9.8, 11.0),  # 阳线
            _bar(4, 11.1, 11.2, 9.7, 9.9),  # 阴线吞没
        ]
        r = detect_patterns(bars, "T")
        assert "看跌吞没" in _names(r)

    def test_hammer_in_downtrend(self):
        bars = [
            _bar(0, 20.5, 20.6, 19.9, 20.0),
            _bar(1, 20.0, 20.1, 18.9, 19.0),
            _bar(2, 19.0, 19.1, 17.9, 18.0),
            _bar(3, 18.0, 18.1, 16.9, 17.0),
            _bar(4, 17.0, 17.1, 15.9, 16.0),
            _bar(5, 16.0, 16.3, 15.0, 16.2),  # 长下影小实体锤子
        ]
        assert "锤子线" in _names(detect_patterns(bars, "T"))

    def test_doji(self):
        bars = [_flat(i, 10) for i in range(5)] + [_bar(5, 10.0, 10.5, 9.5, 10.02)]
        assert "十字星" in _names(detect_patterns(bars, "T"))

    def test_three_white_soldiers(self):
        bars = [
            _flat(0, 10),
            _flat(1, 10),
            _bar(2, 10.0, 10.6, 9.95, 10.5),
            _bar(3, 10.5, 11.1, 10.45, 11.0),
            _bar(4, 11.0, 11.6, 10.95, 11.5),
        ]
        assert "红三兵" in _names(detect_patterns(bars, "T"))

    def test_three_black_crows(self):
        bars = [
            _flat(0, 12),
            _flat(1, 12),
            _bar(2, 11.5, 11.55, 10.9, 11.0),
            _bar(3, 11.0, 11.05, 10.4, 10.5),
            _bar(4, 10.5, 10.55, 9.9, 10.0),
        ]
        assert "三只乌鸦" in _names(detect_patterns(bars, "T"))


class TestStructure:
    def test_gap_up(self):
        bars = [_flat(i, 10) for i in range(5)] + [_bar(5, 11.0, 11.3, 10.9, 11.2)]
        assert "向上跳空" in _names(detect_patterns(bars, "T"))

    def test_breakout_new_high(self):
        bars = [_flat(i, 10) for i in range(21)] + [_bar(21, 11.0, 11.2, 10.9, 11.0)]
        names = _names(detect_patterns(bars, "T"))
        assert any("突破" in n for n in names)

    def test_golden_cross(self):
        closes = [10.0] * 20 + [12.0] * 6
        bars = [_flat(i, c) for i, c in enumerate(closes)]
        names = _names(detect_patterns(bars, "T"))
        assert any("金叉" in n for n in names)

    def test_double_bottom(self):
        closes = [12, 11, 10, 9, 8, 9, 10, 11, 10, 9, 8.1, 9, 10, 11, 12]
        bars = [_flat(i, c) for i, c in enumerate(closes)]
        assert "双底(W底)" in _names(detect_patterns(bars, "T"))


class TestTightStructures:
    def test_box_requires_repeated_rail_touches_and_does_not_treat_098_as_breakout(self):
        # 40-bar box 10–12, rails touched ≥2 times, +1 detection bar.
        # Plan 032: 轨道窗口排除检测 bar → 夹具需 40+1 根;
        # 检测 bar 收盘 11.76 = 0.98*12, 只「接近」上轨而非突破。
        bars = []
        for i in range(40):
            phase = i % 10
            if phase < 3:
                bars.append(_bar(i, 11.8, 12.0, 11.5, 11.9))  # tag upper
            elif phase < 6:
                bars.append(_bar(i, 10.2, 10.5, 10.0, 10.1))  # tag lower
            else:
                bars.append(_bar(i, 11.0, 11.3, 10.8, 11.1))
        # Detection bar sits just under the prior-window upper rail (the loose 0.98
        # rule would call this 看涨突破). Plan 032: rails come from bars[:-1] now.
        bars.append(_bar(40, 11.6, 11.85, 11.5, 11.76))
        r = detect_patterns(bars, "T")
        boxes = [p for p in r.patterns if p.name == "箱体"]
        assert boxes, _names(r)
        assert boxes[0].direction == "neutral"
        assert boxes[0].projection is None

    def test_head_and_shoulders_top(self):
        # Left shoulder 12, head 14, right shoulder 12.2; neck ~10.
        closes = (
            [10] * 4
            + [12, 11.8, 11.5]  # LS
            + [11, 10.2, 10.0]  # trough
            + [13, 14, 13.5]  # head
            + [11, 10.1, 10.0]  # trough
            + [12.0, 12.2, 11.8]  # RS
            + [11, 10.5]
        )
        bars = []
        for i, c in enumerate(closes):
            if c >= 13.5:
                bars.append(_bar(i, c - 0.3, c, c - 0.5, c - 0.1))
            elif c >= 12:
                bars.append(_bar(i, c - 0.2, c, c - 0.4, c - 0.1))
            else:
                bars.append(_bar(i, c + 0.1, c + 0.2, c, c + 0.05))
        r = detect_patterns(bars, "T")
        tops = [p for p in r.patterns if p.name == "头肩顶"]
        assert tops, _names(r)
        assert tops[0].direction == "bearish"
        assert tops[0].projection is not None
        assert "几何投影不是预测" in tops[0].detail

    def test_cup_handle_uses_handle_subinterval_not_global_low(self):
        # Cup: drift down to 8 then recover to 12. Handle after right rim pulls to 11.
        # Global 20-day low would be the cup bottom (8) if we cheated — handle low must be ~11.
        bars = []
        # Left rim ~12
        for i in range(10):
            bars.append(_bar(i, 11.8, 12.1, 11.5, 11.9))
        # Cup down to 8
        for i in range(10, 25):
            c = 12.0 - (i - 10) * 0.27
            bars.append(_bar(i, c + 0.1, c + 0.2, c - 0.15, c))
        # Recover to a distinct right rim ~12.1
        for i in range(25, 40):
            c = 8.0 + (i - 25) * (4.1 / 14)
            bars.append(_bar(i, c - 0.1, c + 0.15, c - 0.15, c))
        # Handle AFTER right rim: pull back to ~11, highs stay below the rim
        for i in range(40, 50):
            c = 12.0 - (i - 40) * 0.10
            bars.append(_bar(i, c + 0.05, c + 0.08, c - 0.12, c))
        r = detect_patterns(bars, "T")
        cups = [p for p in r.patterns if p.name == "杯柄"]
        assert cups, _names(r)
        assert "柄低" in cups[0].detail
        assert "8.00" not in cups[0].detail  # must not use cup/global low as handle
        assert cups[0].projection is not None
        assert "几何投影不是预测" in cups[0].detail


class TestBreakoutReachabilityPlan032:
    """Plan 032: 上/下轨与柄高必须排除检测 bar。

    旧实现把检测 bar 自身算进窗口: ``close > upper`` / ``close < lower`` /
    ``close > handle_high`` 对合法 OHLC 永不成立——箱体/杯柄的看涨/看跌
    突破输出是死代码, 从未触发过。
    """

    def _box_bars(self) -> list[dict]:
        """40 根 10–12 箱体, 上/下沿各被触及 4 次(与既有箱体测试同一生成器)。"""
        bars = []
        for i in range(40):
            phase = i % 10
            if phase < 3:
                bars.append(_bar(i, 11.8, 12.0, 11.5, 11.9))  # tag upper
            elif phase < 6:
                bars.append(_bar(i, 10.2, 10.5, 10.0, 10.1))  # tag lower
            else:
                bars.append(_bar(i, 11.0, 11.3, 10.8, 11.1))
        return bars

    def _cup_bars(self) -> list[dict]:
        """杯(左沿 ~12.1 → 杯底 ~8 → 右沿)+ 柄回落(与既有杯柄测试同一生成器)。"""
        bars = []
        for i in range(10):
            bars.append(_bar(i, 11.8, 12.1, 11.5, 11.9))
        for i in range(10, 25):
            c = 12.0 - (i - 10) * 0.27
            bars.append(_bar(i, c + 0.1, c + 0.2, c - 0.15, c))
        for i in range(25, 40):
            c = 8.0 + (i - 25) * (4.1 / 14)
            bars.append(_bar(i, c - 0.1, c + 0.15, c - 0.15, c))
        for i in range(40, 50):
            c = 12.0 - (i - 40) * 0.10
            bars.append(_bar(i, c + 0.05, c + 0.08, c - 0.12, c))
        return bars

    def test_box_close_above_prior_window_upper_is_bullish(self):
        # 检测 bar 收盘 12.5 越过前窗上轨 12.0 → 看涨(旧代码上轨含检测 bar 高点, 永不可达)。
        bars = self._box_bars() + [_bar(40, 12.1, 12.6, 11.9, 12.5)]
        r = detect_patterns(bars, "T")
        boxes = [p for p in r.patterns if p.name == "箱体"]
        assert boxes, _names(r)
        assert boxes[0].direction == "bullish"
        assert boxes[0].projection is not None

    def test_box_close_below_prior_window_lower_is_bearish(self):
        # 检测 bar 收盘 9.5 跌破前窗下轨 10.0 → 看跌。
        bars = self._box_bars() + [_bar(40, 9.9, 10.1, 9.3, 9.5)]
        r = detect_patterns(bars, "T")
        boxes = [p for p in r.patterns if p.name == "箱体"]
        assert boxes, _names(r)
        assert boxes[0].direction == "bearish"
        assert boxes[0].projection is not None

    def test_box_close_inside_window_stays_neutral(self):
        # 防误报: 检测 bar 在箱体内正常震荡 → 仍为中性, 不得给出突破。
        bars = self._box_bars() + [_bar(40, 11.2, 11.4, 11.0, 11.2)]
        r = detect_patterns(bars, "T")
        boxes = [p for p in r.patterns if p.name == "箱体"]
        assert boxes, _names(r)
        assert boxes[0].direction == "neutral"
        assert boxes[0].projection is None

    def test_cup_handle_close_above_prior_handle_highs_is_bullish(self):
        # 检测 bar 收盘 12.6 高于柄区间(检测 bar 之前)全部高点 → 看涨
        # (旧代码柄高含检测 bar 自身高点 12.7, 分支永不可达)。
        bars = self._cup_bars() + [_bar(50, 12.5, 12.7, 12.3, 12.6)]
        r = detect_patterns(bars, "T")
        cups = [p for p in r.patterns if p.name == "杯柄"]
        assert cups, _names(r)
        assert cups[0].direction == "bullish"


class TestReportShape:
    def test_to_dict_and_counts(self):
        bars = [
            _flat(0, 10),
            _flat(1, 10),
            _bar(2, 10.0, 10.6, 9.95, 10.5),
            _bar(3, 10.5, 11.1, 10.45, 11.0),
            _bar(4, 11.0, 11.6, 10.95, 11.5),
        ]
        d = detect_patterns(bars, "600519").to_dict()
        for key in (
            "status",
            "symbol",
            "bars_used",
            "patterns",
            "counts",
            "note",
            "disclaimer",
        ):
            assert key in d
        assert d["symbol"] == "600519"
        assert d["counts"]["total"] == len(d["patterns"])
        assert "不构成任何投资建议" in d["disclaimer"]

    def test_patterns_sorted_recent_first(self):
        closes = [10.0] * 20 + [12.0] * 6
        bars = [_flat(i, c) for i, c in enumerate(closes)]
        r = detect_patterns(bars, "T")
        idxs = [p.index for p in r.patterns]
        assert idxs == sorted(idxs, reverse=True)
