"""
归档自动标签模块
- 为每个已归档报告计算未来 3/5/10/20 日涨跌幅
- 计算 10 个交易日窗口内的最大回撤(基于报告日收盘价)
- 根据 decision 文字推断信号,并为 3/5/10 日打 hit 标签
  - 买入命中: 该窗口收益 > 0
  - 卖出命中: 该窗口收益 < 0
  - 观望命中: |该窗口收益| <= HOLD_HIT_THRESHOLD_PCT(默认 2%)
"""

import json
from pathlib import Path

from price_fetcher import get_price_after, get_price_range

try:
    from backend.project_paths import REPORTS_DIR
except ImportError:
    from project_paths import REPORTS_DIR


ARCHIVE_ROOT = REPORTS_DIR / "archive"
INDEX_FILE = ARCHIVE_ROOT / "index.json"

# 观望信号"命中"的判定阈值(%):区间双向波动均不超过该值视为"避震成功"
HOLD_HIT_THRESHOLD_PCT = 2.0
# 最大回撤窗口(交易日)
DRAWDOWN_WINDOW_DAYS = 10
# 单点收益的所有 (天数, 字段名),按从近到远排列
RETURN_KEYS = [
    (3, "3d_return"),
    (5, "5d_return"),
    (10, "10d_return"),
    (20, "20d_return"),
]
# 需要计算命中标签的窗口
HIT_DAYS = (3, 5, 10)
# 索引中"完整后验"必须包含的字段集合(用于判断能否提前 skip)
COMPLETE_KEYS = tuple(k for _, k in RETURN_KEYS) + ("max_drawdown_10d",)


def _load_index() -> list:
    """加载归档索引。"""
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_index(idx: list):
    """保存归档索引（原子写入）。"""
    import tempfile

    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".tmp",
        dir=ARCHIVE_ROOT,
        delete=False,
    )
    try:
        tmp.write(json.dumps(idx, ensure_ascii=False, indent=2))
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(INDEX_FILE)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def _decision_to_signal(decision: str) -> str:
    """从 'decision' 文字中提取规范信号方向。返回 '买入'/'卖出'/'观望' 或 ''。"""
    if not decision:
        return ""
    if "买入" in decision:
        return "买入"
    if "卖出" in decision:
        return "卖出"
    if "观望" in decision or "持有" in decision or "中性" in decision:
        return "观望"
    return ""


def _compute_hit(signal: str, return_pct: float, hold_threshold: float = HOLD_HIT_THRESHOLD_PCT) -> int:
    """根据信号方向与窗口收益判定是否命中。返回 1/0。"""
    if signal == "买入":
        return 1 if return_pct > 0 else 0
    if signal == "卖出":
        return 1 if return_pct < 0 else 0
    if signal == "观望":
        return 1 if abs(return_pct) <= hold_threshold else 0
    return 0


def tag_all_reports() -> dict:
    """遍历归档索引,为每个报告补齐 3/5/10/20 日收益、10 日最大回撤与命中标签。

    Returns:
        {"tagged": int, "skipped": int, "errors": int}
        - tagged: 本次有任何新字段被写入的条目
        - skipped: 已经完整或缺少必要元数据(symbol/date/close)的条目
        - errors: 仍未写入任何字段且尚不完整(通常因为后验数据不足)
    """
    idx = _load_index()
    if not idx:
        return {"tagged": 0, "skipped": 0, "errors": 0}

    tagged = 0
    skipped = 0
    errors = 0

    for item in idx:
        if all(k in item for k in COMPLETE_KEYS):
            skipped += 1
            continue

        symbol = item.get("symbol")
        date_str = item.get("date")
        report_close = item.get("close")

        if not symbol or not date_str or report_close is None:
            skipped += 1
            continue
        try:
            report_close = float(report_close)
        except (ValueError, TypeError):
            skipped += 1
            continue

        signal = _decision_to_signal(item.get("decision", ""))
        changed = False

        # 1) 单点收益(3/5/10/20 日)与命中标签
        for days, key in RETURN_KEYS:
            if key in item:
                continue
            future_price = get_price_after(symbol, date_str, days)
            if future_price is None:
                continue
            ret = (future_price - report_close) / report_close * 100
            item[key] = round(ret, 2)
            changed = True
            if days in HIT_DAYS and signal:
                item[f"hit_{days}d"] = _compute_hit(signal, ret)

        # 2) 10 日窗口最大回撤(相对报告日收盘价)
        if "max_drawdown_10d" not in item:
            series = get_price_range(symbol, date_str, DRAWDOWN_WINDOW_DAYS)
            if series:
                rel = [(close - report_close) / report_close * 100 for _, close in series]
                # 取最坏的相对跌幅,若全程未跌则记 0.0(便于统计零值)
                dd = min(min(rel), 0.0)
                item["max_drawdown_10d"] = round(dd, 2)
                changed = True

        if changed:
            tagged += 1
        else:
            errors += 1

    _save_index(idx)
    return {"tagged": tagged, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    print("Archive tagger loaded.")
    result = tag_all_reports()
    print(f"Result: {result}")
