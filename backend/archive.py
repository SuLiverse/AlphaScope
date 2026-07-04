"""
研究存档系统
- 自动落盘每次决策报告到 reports/archive/{symbol}/
- 维护索引文件 index.json，支持按股票/决策/时间检索
- 检测重复存档（同股票 5 分钟内不重复保存）
- v0.7：新增 report_type 字段(agent/roundtable),新增 save_roundtable()
"""

import json
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from backend.project_paths import REPORTS_DIR
except ImportError:
    from project_paths import REPORTS_DIR

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = REPORTS_DIR / "archive"
INDEX_FILE = ARCHIVE_ROOT / "index.json"

# v0.7：圆桌纪要根目录(独立于 archive,但索引共用 index.json)
ROUNDTABLE_ROOT = REPORTS_DIR / "roundtables"


def _safe_symbol(value: str) -> str:
    symbol = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._-]{1,24}", symbol):
        return symbol
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol).strip("._-")
    return cleaned[:24] or "unknown"


def _safe_filename_part(value: str, default: str = "report") -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._ ")
    return text[:80] or default


def _resolve_archive_path(path: str) -> Path:
    raw = Path(str(path)).expanduser()
    # 相对路径锚定 REPORTS_DIR (新索引格式, URL 可往返); 绝对路径分支兼容旧索引条目
    p = raw.resolve() if raw.is_absolute() else (REPORTS_DIR / raw).resolve()
    allowed_roots = [ARCHIVE_ROOT.resolve(), ROUNDTABLE_ROOT.resolve()]
    if not any(p == root or root in p.parents for root in allowed_roots):
        raise ValueError("报告路径不在允许的归档目录内")
    return p


def _to_index_path(fpath: Path) -> str:
    """索引/API 返回相对 REPORTS_DIR 的 POSIX 路径。

    绝对路径在 Linux 以 "/" 开头, 会被 /api/archive/report/{path} 的路径遍历防护
    400 拒绝 (创建接口返回的路径读取接口永远无法消费); 相对 POSIX 路径两个平台
    都能安全放进 URL 往返。转换失败时退回绝对路径 (旧行为)。
    """
    try:
        return fpath.resolve().relative_to(REPORTS_DIR.resolve()).as_posix()
    except Exception:
        return str(fpath)


def _ensure_dirs():
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        INDEX_FILE.write_text("[]", encoding="utf-8")


def _load_index() -> list:
    _ensure_dirs()
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except FileNotFoundError:
        return []
    except Exception as e:
        backup = INDEX_FILE.with_suffix(f".corrupt-{datetime.now().strftime('%Y%m%d%H%M%S')}.json")
        try:
            INDEX_FILE.replace(backup)
        except Exception:
            pass
        logger.warning("[Archive] 索引读取失败,已保留损坏文件: %s", e)
        return []


def _save_index(idx: list):
    _ensure_dirs()
    text = json.dumps(idx, ensure_ascii=False, indent=2)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(ARCHIVE_ROOT),
        delete=False,
        prefix="index.",
        suffix=".tmp",
    ) as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(INDEX_FILE)


def save_report(
    stock_name: str,
    symbol: str,
    payload: dict,
    llm_result: dict,
    chairman_text: str,
    report_md: str,
    dedupe_minutes: int = 5,
    report_type: str = "agent",
) -> dict:
    """
    保存报告到磁盘并更新索引。
    - dedupe_minutes：同 symbol 内的最近 N 分钟，若已存在则跳过保存
    - report_type: "agent"(默认,5 Agent 决策报告) / "roundtable"(专家圆桌)
    返回：{"saved": bool, "path": str, "reason": str}
    """
    _ensure_dirs()
    idx = _load_index()
    now = datetime.now()
    safe_symbol = _safe_symbol(symbol)
    safe_stock_name = _safe_filename_part(stock_name, default=safe_symbol)

    # 去重：同 symbol + report_type 在 dedupe_minutes 内不重复保存
    for item in idx:
        if item.get("symbol") == safe_symbol and item.get("type", "agent") == report_type:
            try:
                ts = datetime.fromisoformat(item["timestamp"])
                if (now - ts).total_seconds() < dedupe_minutes * 60:
                    return {
                        "saved": False,
                        "path": item["path"],
                        "reason": f"{dedupe_minutes} 分钟内已存档（{ts.strftime('%H:%M')}）",
                    }
            except Exception:
                continue

    # 落盘
    sub_dir = ARCHIVE_ROOT / safe_symbol
    sub_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y%m%d-%H%M%S')}-{safe_stock_name}.md"
    fpath = sub_dir / fname
    fpath.write_text(report_md, encoding="utf-8")

    # 抽取每个 Agent 的模型快照（用于回测不同模型组合的胜率）
    agent_models = {}
    agents_dict = (llm_result or {}).get("agents", {}) or {}
    for k, r in agents_dict.items():
        agent_models[k] = {
            "name": r.get("name", k),
            "vendor": r.get("vendor", "?"),
            "model": r.get("model", "?"),
            "primary_vendor": r.get("primary_vendor", r.get("vendor", "?")),
            "fallback_used": bool(r.get("fallback_used", False)),
            "signal": r.get("signal", ""),
            "confidence": r.get("confidence", 0),
            "ok": bool(r.get("ok", True)),
            # v0.9: 把审稿评分快照进归档,便于按 quality 维度回测
            "review": r.get("review") or None,
        }
    # 模型组合签名（基于实际生效的模型）
    combo_signature = (
        "|".join(f"{k}:{v['vendor']}/{v['model']}" for k, v in sorted(agent_models.items())) if agent_models else ""
    )
    # 主厂商组合签名（基于配置的主模型，便于按"理想配置"统计）
    primary_combo_signature = (
        "|".join(f"{k}:{v['primary_vendor']}" for k, v in sorted(agent_models.items())) if agent_models else ""
    )

    # 更新索引
    summary = llm_result.get("summary", {})
    meta = {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "type": report_type,
        "stock_name": stock_name,
        "symbol": safe_symbol,
        "decision": summary.get("final", "未知"),
        "buy": summary.get("buy", 0),
        "sell": summary.get("sell", 0),
        "hold": summary.get("hold", 0),
        "avg_confidence": round(float(summary.get("avg_confidence", 0)), 1),
        "close": payload.get("close"),
        "day_change": payload.get("day_change"),
        "period_change": payload.get("period_change"),
        "main_5d_yi": _safe_main_flow(payload.get("stock_fund_brief", "")),
        "chairman_excerpt": (chairman_text or "")[:80].replace("\n", " "),
        # 多模型异构架构 v0.5 新增
        "agent_models": agent_models,
        "combo_signature": combo_signature,
        "primary_combo_signature": primary_combo_signature,
        # 兜底统计：fallback_used 表示主厂商失败切到 DeepSeek，failed 表示连兜底都失败
        "fallback_count": sum(1 for v in agent_models.values() if v.get("fallback_used")),
        "failed_count": sum(1 for v in agent_models.values() if not v["ok"]),
        # v0.9: critic 总览(每个 agent 的具体 review 已经在 agent_models[k]['review'] 里)
        "critic": _summarize_critic((llm_result or {}).get("critic"), agent_models),
        "path": _to_index_path(fpath),
        "filename": fname,
    }
    idx.insert(0, meta)  # 最新在前
    _save_index(idx)

    return {"saved": True, "path": _to_index_path(fpath), "reason": "已存档"}


# ============== v0.7：专家圆桌纪要落盘 ==============
def save_roundtable(
    stock_name: str,
    symbol: str,
    opinions: dict,
    summary: dict,
    md_text: str,
    dedupe_minutes: int = 1,
) -> dict:
    """
    专家圆桌纪要落盘到 reports/roundtables/{symbol}/{YYYYMMDD-HHMMSS}-{stock_name}.md
    并在统一的 index.json 中追加 type='roundtable' 记录。

    返回 {"saved": bool, "path": str, "reason": str}
    """
    _ensure_dirs()
    idx = _load_index()
    now = datetime.now()
    safe_symbol = _safe_symbol(symbol)
    safe_stock_name = _safe_filename_part(stock_name, default=safe_symbol)

    # 去重:同 symbol 圆桌纪要 dedupe_minutes 内不重复
    for item in idx:
        if item.get("symbol") == safe_symbol and item.get("type") == "roundtable":
            try:
                ts = datetime.fromisoformat(item["timestamp"])
                if (now - ts).total_seconds() < dedupe_minutes * 60:
                    return {
                        "saved": False,
                        "path": item["path"],
                        "reason": f"{dedupe_minutes} 分钟内已存档圆桌（{ts.strftime('%H:%M')}）",
                    }
            except Exception:
                continue

    # 落盘
    sub_dir = ROUNDTABLE_ROOT / safe_symbol
    sub_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{now.strftime('%Y%m%d-%H%M%S')}-{safe_stock_name}.md"
    fpath = sub_dir / fname
    fpath.write_text(md_text, encoding="utf-8")

    # 抽取专家观点快照
    expert_snapshot = {}
    for k, op in (opinions or {}).items():
        # 兼容 ExpertOpinion dataclass / 普通 dict
        if hasattr(op, "__dict__"):
            d = {
                "name": getattr(op, "expert_name", k),
                "vendor": getattr(op, "vendor", "?"),
                "model": getattr(op, "model", "?"),
                "action": getattr(op, "action", "观望"),
                "position": getattr(op, "position", 0),
                "stop_loss": getattr(op, "stop_loss", 0.0),
                "fallback_used": bool(getattr(op, "fallback_used", False)),
                "ok": bool(getattr(op, "ok", True)),
            }
        elif isinstance(op, dict):
            d = {
                "name": op.get("expert_name", k),
                "vendor": op.get("vendor", "?"),
                "model": op.get("model", "?"),
                "action": op.get("action", "观望"),
                "position": op.get("position", 0),
                "stop_loss": op.get("stop_loss", 0.0),
                "fallback_used": bool(op.get("fallback_used", False)),
                "ok": bool(op.get("ok", True)),
            }
        else:
            continue
        expert_snapshot[k] = d

    # 决策文字: 取多数派 action
    summary = summary or {}
    actions = {
        "建议买入": summary.get("buy", 0),
        "建议观望": summary.get("hold", 0),
        "建议减持": summary.get("reduce", 0),
        "建议卖出": summary.get("sell", 0),
    }
    decision = max(actions, key=actions.get) if any(actions.values()) else "建议观望"

    excerpt_parts = []
    for key in ("buffett", "lynch", "chanlun", "macro", "risk_officer"):
        s = expert_snapshot.get(key)
        if s:
            excerpt_parts.append(f"{s['name']}{s['action']}{s['position']}%")
    excerpt = " | ".join(excerpt_parts)[:80]

    meta = {
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "type": "roundtable",
        "stock_name": stock_name,
        "symbol": safe_symbol,
        "decision": decision,
        "buy": summary.get("buy", 0),
        "sell": summary.get("sell", 0),
        "hold": summary.get("hold", 0),
        "reduce": summary.get("reduce", 0),
        "avg_position": round(float(summary.get("avg_position", 0)), 1),
        "valid_count": summary.get("valid_count", 0),
        "total_count": summary.get("total_count", 0),
        "expert_snapshot": expert_snapshot,
        "fallback_count": sum(1 for s in expert_snapshot.values() if s.get("fallback_used")),
        "failed_count": sum(1 for s in expert_snapshot.values() if not s.get("ok")),
        "chairman_excerpt": excerpt,
        # 兼容字段(便于在 Tab7 共用列表渲染时不报错)
        "avg_confidence": 0.0,
        "agent_models": {},
        "combo_signature": "",
        "primary_combo_signature": "",
        "path": _to_index_path(fpath),
        "filename": fname,
    }
    idx.insert(0, meta)
    _save_index(idx)

    return {"saved": True, "path": _to_index_path(fpath), "reason": "圆桌纪要已存档"}


def _summarize_critic(critic_block, agent_models: dict):
    """v0.9: 把 critic 块压成索引层用得到的小摘要;具体 review 仍保留在 agent_models[k]['review']。

    返回 None 表示本次未启用/未拿到 critic 数据,前端可据此隐藏审稿区块。
    """
    if not isinstance(critic_block, dict) or not critic_block.get("ok"):
        if isinstance(critic_block, dict) and critic_block.get("error"):
            return {"ok": False, "error": str(critic_block.get("error"))[:160]}
        return None

    scores = [
        v["review"]["quality_score"]
        for v in agent_models.values()
        if isinstance(v.get("review"), dict) and isinstance(v["review"].get("quality_score"), int)
    ]
    avg_q = round(sum(scores) / len(scores), 1) if scores else None
    overconfident = sum(
        1 for v in agent_models.values() if isinstance(v.get("review"), dict) and v["review"].get("overconfident")
    )
    div = critic_block.get("divergence") or {}
    return {
        "ok": True,
        "vendor": critic_block.get("vendor", ""),
        "model": critic_block.get("model", ""),
        "fallback_used": bool(critic_block.get("fallback_used", False)),
        "avg_quality": avg_q,
        "reviewed_count": len(scores),
        "overconfident_count": overconfident,
        "divergence_level": div.get("level", ""),
        "divergence_axis": div.get("main_axis", ""),
        "divergence_summary": div.get("summary", ""),
    }


def _safe_main_flow(brief: str) -> float:
    """从 fund_flow brief 文本里提取近 5 日主力净流入/流出数值（亿元）"""
    if not brief:
        return None
    # 匹配 "主力合计净流入/流出: ±X.XX亿" 或 "主力净流入/流出 X.XX"
    patterns = [
        r"主力(?:合计)?净流[入出][^-+\d]*([+-]?\d+\.?\d*)",
        r"近5日主力\s*([+-]?\d+\.?\d*)",
    ]
    for pat in patterns:
        m = re.search(pat, brief)
        if m:
            try:
                val = float(m.group(1))
                # 如果文本明确写"流出"且数值为正，自动取负（防御）
                if "流出" in brief[: m.start() + 20] and val > 0:
                    val = -val
                return val
            except Exception:
                continue
    return None


def list_reports(
    stock_filter: str = None,
    decision_filter: str = None,
    date_from: str = None,
    date_to: str = None,
    type_filter: str = None,
    limit: int = 200,
) -> list:
    """检索历史报告。type_filter: None(全部) / "agent" / "roundtable" """
    idx = _load_index()
    out = []
    for item in idx:
        if stock_filter and stock_filter not in (item.get("stock_name", "") + item.get("symbol", "")):
            continue
        if decision_filter and decision_filter not in item.get("decision", ""):
            continue
        if date_from and item.get("date", "") < date_from:
            continue
        if date_to and item.get("date", "") > date_to:
            continue
        if type_filter and item.get("type", "agent") != type_filter:
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def load_report(path: str) -> str:
    """读取报告 markdown 全文"""
    try:
        p = _resolve_archive_path(path)
    except Exception:
        return "⚠️ 报告路径不在允许的归档目录内"
    if not p.exists():
        return f"⚠️ 报告文件不存在：{path}"
    return p.read_text(encoding="utf-8")


def get_stats() -> dict:
    """全局统计：总报告数、按决策分类、覆盖股票数、最近活跃日"""
    idx = _load_index()
    if not idx:
        return {"total": 0, "buy": 0, "sell": 0, "hold": 0, "stocks": 0, "latest": None}
    stocks = set()
    counts = {"建议买入": 0, "建议卖出": 0, "建议观望": 0}
    fallbacks = 0
    combos = {}
    for item in idx:
        stocks.add(item.get("symbol"))
        d = item.get("decision", "")
        for k in counts:
            if k in d:
                counts[k] += 1
        fallbacks += int(item.get("fallback_count", 0) or 0)
        sig = item.get("combo_signature", "")
        if sig:
            combos[sig] = combos.get(sig, 0) + 1
    return {
        "total": len(idx),
        "buy": counts["建议买入"],
        "sell": counts["建议卖出"],
        "hold": counts["建议观望"],
        "stocks": len(stocks),
        "latest": idx[0].get("timestamp"),
        "fallback_total": fallbacks,
        "distinct_combos": len(combos),
    }


def get_combo_stats() -> list:
    """模型组合横向统计：返回 [(combo_signature, count, buy/sell/hold分布, 平均置信度)]
    用于回测：相同标的下不同模型组合的决策差异"""
    idx = _load_index()
    combos = {}
    for item in idx:
        sig = item.get("combo_signature", "")
        if not sig:
            continue
        if sig not in combos:
            combos[sig] = {
                "count": 0,
                "buy": 0,
                "sell": 0,
                "hold": 0,
                "avg_conf_sum": 0.0,
            }
        combos[sig]["count"] += 1
        d = item.get("decision", "")
        if "买入" in d:
            combos[sig]["buy"] += 1
        elif "卖出" in d:
            combos[sig]["sell"] += 1
        elif "观望" in d:
            combos[sig]["hold"] += 1
        combos[sig]["avg_conf_sum"] += float(item.get("avg_confidence", 0) or 0)
    out = []
    for sig, v in combos.items():
        n = max(v["count"], 1)
        out.append(
            {
                "combo": sig,
                "count": v["count"],
                "buy": v["buy"],
                "sell": v["sell"],
                "hold": v["hold"],
                "avg_confidence": round(v["avg_conf_sum"] / n, 1),
            }
        )
    out.sort(key=lambda x: -x["count"])
    return out


def get_combo_performance(min_samples: int = 1) -> list:
    """v0.8: 模型组合后验表现统计。

    依赖 archive_tagger.tag_all_reports() 已经回填的字段:
    - 3d_return / 5d_return / 10d_return / 20d_return
    - max_drawdown_10d
    - hit_3d / hit_5d / hit_10d (1/0)

    对仅有信号分布、尚无后验标签的报告,聚合时跳过未填字段(samples_with_label 体现样本量)。

    Args:
        min_samples: 至少有多少条 5 日后验样本才返回该组合,过滤过短的小样本。

    Returns:
        list[dict],按 5 日命中率降序、其次按样本量降序排序。
    """

    def _avg(values: list):
        cleaned = [v for v in values if isinstance(v, (int, float)) and v == v]
        if not cleaned:
            return None
        return round(sum(cleaned) / len(cleaned), 2)

    def _rate(values: list):
        cleaned = [v for v in values if v in (0, 1)]
        if not cleaned:
            return None
        return round(sum(cleaned) / len(cleaned), 3)

    idx = _load_index()
    combos = {}
    for item in idx:
        if item.get("type", "agent") != "agent":
            continue
        sig = item.get("combo_signature", "")
        if not sig:
            continue
        decision = item.get("decision", "")
        bucket = combos.setdefault(
            sig,
            {
                "combo": sig,
                "count": 0,
                "buy": 0,
                "sell": 0,
                "hold": 0,
                "ret_3d": [],
                "ret_5d": [],
                "ret_10d": [],
                "ret_20d": [],
                "drawdown_10d": [],
                "hit_3d": [],
                "hit_5d": [],
                "hit_10d": [],
                "buy_hit_5d": [],
                "sell_hit_5d": [],
                "hold_hit_5d": [],
            },
        )
        bucket["count"] += 1
        if "买入" in decision:
            bucket["buy"] += 1
        elif "卖出" in decision:
            bucket["sell"] += 1
        elif "观望" in decision:
            bucket["hold"] += 1

        for key, dest in (
            ("3d_return", "ret_3d"),
            ("5d_return", "ret_5d"),
            ("10d_return", "ret_10d"),
            ("20d_return", "ret_20d"),
            ("max_drawdown_10d", "drawdown_10d"),
            ("hit_3d", "hit_3d"),
            ("hit_5d", "hit_5d"),
            ("hit_10d", "hit_10d"),
        ):
            if key in item and item[key] is not None:
                bucket[dest].append(item[key])

        if "hit_5d" in item and item["hit_5d"] in (0, 1):
            if "买入" in decision:
                bucket["buy_hit_5d"].append(item["hit_5d"])
            elif "卖出" in decision:
                bucket["sell_hit_5d"].append(item["hit_5d"])
            elif "观望" in decision:
                bucket["hold_hit_5d"].append(item["hit_5d"])

    out = []
    for sig, b in combos.items():
        samples_5d = len(b["ret_5d"])
        if samples_5d < min_samples:
            continue
        out.append(
            {
                "combo": sig,
                "count": b["count"],
                "buy": b["buy"],
                "sell": b["sell"],
                "hold": b["hold"],
                "samples_with_label": samples_5d,
                "avg_3d_return": _avg(b["ret_3d"]),
                "avg_5d_return": _avg(b["ret_5d"]),
                "avg_10d_return": _avg(b["ret_10d"]),
                "avg_20d_return": _avg(b["ret_20d"]),
                "avg_drawdown_10d": _avg(b["drawdown_10d"]),
                "hit_rate_3d": _rate(b["hit_3d"]),
                "hit_rate_5d": _rate(b["hit_5d"]),
                "hit_rate_10d": _rate(b["hit_10d"]),
                "buy_hit_rate_5d": _rate(b["buy_hit_5d"]),
                "sell_hit_rate_5d": _rate(b["sell_hit_5d"]),
                "hold_hit_rate_5d": _rate(b["hold_hit_5d"]),
            }
        )

    # 排序:先按 5 日命中率(None 视为 -1),其次按样本量
    out.sort(
        key=lambda x: (
            x["hit_rate_5d"] if x["hit_rate_5d"] is not None else -1,
            x["samples_with_label"],
        ),
        reverse=True,
    )
    return out


def delete_report(path: str) -> bool:
    """删除单条报告（同时清理索引）"""
    try:
        p = _resolve_archive_path(path)
    except Exception:
        return False
    idx = _load_index()
    new_idx = [i for i in idx if i.get("path") != path]
    if len(new_idx) == len(idx):
        return False
    _save_index(new_idx)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
    return True


if __name__ == "__main__":
    # 简单自测
    print("Archive module loaded.")
    print("Stats:", get_stats())
    print("Recent reports:")
    for r in list_reports(limit=5):
        print(f"  [{r['date']} {r['time']}] {r['stock_name']}({r['symbol']}) → {r['decision']} @{r['avg_confidence']}%")
