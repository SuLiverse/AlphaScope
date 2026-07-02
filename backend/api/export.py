"""导出 API — 把研究成果导出为可下载文件。

会话 → Markdown 研报(复用 backend.ai_assistant.report_generator.generate_report)。
纯新增,不改动既有功能。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger(__name__)


def _loads(value) -> dict:
    """容错地把 task 行里的 JSON 字段解析为 dict。"""
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

router = APIRouter(prefix="/api/export", tags=["export"])


def _safe_filename(stem: str) -> str:
    # 只保留 ASCII 字母数字与 -_/,其余(含中文)替换为 _,避免 HTTP 头 latin-1 编码失败
    keep = [c if (c.isascii() and (c.isalnum() or c in "-_")) else "_" for c in stem]
    name = "".join(keep).strip("_") or "report"
    return name[:80]


@router.get("/conversation/{conversation_id}.md")
def export_conversation_markdown(
    conversation_id: str, gate: bool = Query(default=False)
):
    """把一段 AI 研究对话导出为 Markdown 文件(浏览器下载)。

    ``?gate=true`` 时附加 M3 研报质量门控结果(critical/warning)到文末。
    """
    from backend.ai_assistant.conversation_store import ConversationStore
    from backend.ai_assistant.report_generator import generate_report
    from backend.storage.db import Database

    store = ConversationStore(db=Database())
    conv = store.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    messages = store.get_messages(conversation_id)
    markdown = generate_report(conv, messages)

    if gate:
        from backend.quality.report_gate import format_human, run_gate

        result = run_gate(markdown, mode=conv.get("mode"))
        markdown += "\n\n---\n\n## 质量门控\n\n```\n" + format_human(result) + "\n```\n"

    stem = _safe_filename(
        f"alphascope-{conv.get('stock_symbol') or conv.get('title') or conversation_id}"
    )
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
    )


# 研报大纲范式 → 标题框架与免责侧重
_REPORT_TEMPLATES = {
    "standard": {
        "title": "个股深度评级研究报告",
        "sections": [
            "投资建议与确定性评级",
            "主席综合裁决",
            "多 Agent 分析",
            "风控复核意见",
            "风险提示",
        ],
    },
    "macro": {
        "title": "行业及产业链专题跟踪报告",
        "sections": [
            "行业景气与宏观定位",
            "投资建议与确定性评级",
            "主席综合裁决",
            "多 Agent 分析",
            "产业链风险提示",
        ],
    },
    "risk": {
        "title": "黑天鹅情绪避险与信用预警评估",
        "sections": [
            "风险预警概览",
            "投资建议与确定性评级",
            "主席综合裁决",
            "多 Agent 分析",
            "风控复核意见",
            "违约/质押/舆情风险提示",
        ],
    },
}


def _rating_line(summary: dict) -> str:
    """从 summary 抽取确定性评级与评分行(后端 rating 模块产出)。"""
    score = summary.get("score")
    rating = summary.get("rating")
    parts = []
    if rating:
        parts.append(f"**评级**: {rating}")
    if isinstance(score, (int, float)):
        parts.append(f"**评分**: {float(score):.0f}/100")
    return "  |  ".join(parts)


def _safe_csv_like(value) -> str:
    return str(value or "").strip()


@router.get("/report/{task_id}.md")
def export_report_markdown(task_id: str):
    """把一个异步分析任务的完整结果导出为 Markdown 研报(浏览器下载)。

    从 TaskQueue 取 task.result, 按 task.input_data.report_template 选大纲框架,
    组装: 标题/评级/主席裁决/多 Agent/风控复核/风险/合规免责。
    """
    from backend.task_queue import TaskQueue

    task = TaskQueue().get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # task 行里 output_json / input_json 是 JSON 字符串, 需解析
    result = _loads(task.get("output_json"))
    if not result:
        raise HTTPException(status_code=404, detail="任务尚无可用结果")

    input_data = _loads(task.get("input_json"))
    symbol = _safe_csv_like(result.get("symbol") or input_data.get("stock_symbol"))
    name = _safe_csv_like(result.get("name") or input_data.get("stock_name") or symbol)
    template_key = _safe_csv_like(
        result.get("report_template") or input_data.get("report_template") or "standard"
    )
    tmpl = _REPORT_TEMPLATES.get(template_key, _REPORT_TEMPLATES["standard"])

    summary = result.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    agents = result.get("agents") or result.get("result", {}).get("agents") or {}
    chairman = _safe_csv_like(
        result.get("chairman_summary") or result.get("result", {}).get("chairman_summary")
    )
    critic_block = result.get("critic") or result.get("result", {}).get("critic") or {}
    research_report = _safe_csv_like(
        result.get("research_report") or result.get("result", {}).get("research_report")
    )

    lines: list[str] = []
    lines.append(f"# {tmpl['title']}")
    lines.append("")
    lines.append(f"**标的**: {name}（{symbol}）  ")
    lines.append(f"**生成时间**: {_now_str()}  ")
    rating_line = _rating_line(summary)
    if rating_line:
        lines.append(rating_line + "  ")
    model_status = result.get("model_status") or {}
    if isinstance(model_status, dict) and model_status.get("degraded"):
        lines.append("> ⚠️ 本次模型推理链路降级,所有方向性结论应在修复配置后复核。  ")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 各章节按范式顺序产出(有内容才写)
    def _section(title: str, body: str) -> None:
        body = (body or "").strip()
        if body:
            lines.append(f"## {title}")
            lines.append("")
            lines.append(body)
            lines.append("")

    body_map: dict[str, str] = {}

    # 评级行
    final = _safe_csv_like(summary.get("final"))
    if final or rating_line:
        body_map["评级"] = (final + ("\n\n" + rating_line if rating_line else "")).strip()

    # 主席裁决
    if chairman:
        body_map["主席裁决"] = chairman
    elif research_report:
        # 无主席时回退到编排器生成的报告正文
        body_map["主席裁决"] = research_report

    # 多 Agent
    if isinstance(agents, dict) and agents:
        agent_parts = []
        for r in agents.values():
            if not isinstance(r, dict):
                continue
            an = _safe_csv_like(r.get("name") or r.get("key"))
            sig = _safe_csv_like(r.get("signal"))
            conf = r.get("confidence")
            reason = _safe_csv_like(r.get("reason"))
            head = f"- **{an or 'Agent'}**: {sig or '观望'}" + (
                f"（置信度 {float(conf):.0f}%）" if isinstance(conf, (int, float)) else ""
            )
            agent_parts.append(f"{head}\n  {reason}" if reason else head)
        if agent_parts:
            body_map["多 Agent"] = "\n".join(agent_parts)

    # 风控复核
    critic_text = ""
    if isinstance(critic_block, dict):
        if critic_block.get("ok"):
            div = critic_block.get("divergence") or {}
            critic_text = _safe_csv_like(
                div.get("summary") or div.get("main_axis")
            )
        elif critic_block.get("error"):
            critic_text = "风控复核未完成:" + _safe_csv_like(critic_block.get("error"))
    if critic_text:
        body_map["风控复核"] = critic_text

    # 风险提示
    risk_lines: list[str] = []
    if isinstance(agents, dict):
        for r in agents.values():
            if isinstance(r, dict):
                for rk in r.get("risks") or []:
                    rk = _safe_csv_like(rk)
                    if rk and rk not in risk_lines:
                        risk_lines.append(f"- {rk}")
    body_map["风险"] = "\n".join(risk_lines)

    # 按选定范式顺序输出
    SECTION_LABEL = {
        "评级": ["投资建议与确定性评级", "风险预警概览", "行业景气与宏观定位"],
        "主席裁决": ["主席综合裁决"],
        "多 Agent": ["多 Agent 分析"],
        "风控复核": ["风控复核意见"],
        "风险": [
            "风险提示",
            "产业链风险提示",
            "违约/质押/舆情风险提示",
        ],
    }
    emitted = set()
    for title in tmpl["sections"]:
        for key, labels in SECTION_LABEL.items():
            if title in labels and key not in emitted and key in body_map:
                _section(title, body_map[key])
                emitted.add(key)
                break
    # 补上范式里没有但仍有内容的章节
    for key, body in body_map.items():
        if key not in emitted:
            _section(key, body)

    # 合规免责
    lines.append("---")
    lines.append("")
    lines.append("## 免责声明")
    lines.append("")
    lines.append(
        "本报告由研策中枢 AlphaScope 多 Agent 系统自动生成, 仅供研究、学习与辅助决策参考, "
        "**不构成投资建议, 不荐股, 不预测行情, 不承诺收益**。所有结论应结合真实数据源、"
        "个人风险承受能力与专业判断独立核验。回测与评级结果均不代表未来收益。"
    )
    lines.append("")

    markdown = "\n".join(lines)
    stem = _safe_filename(f"alphascope-report-{name or symbol or task_id}")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
    )


def _now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M")
