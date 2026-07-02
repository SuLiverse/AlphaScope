"""通知推送 API — 渠道配置 + 测试 + 发送告警。

端点:
- GET  /api/notifiers              列出渠道(凭证不回传明文)
- POST /api/notifiers/{channel}    保存渠道凭证 + 启停
- DELETE /api/notifiers/{channel}  删除渠道
- POST /api/notifiers/{channel}/test  发一条测试消息
- POST /api/notifiers/dispatch     把一段消息推送到所有已启用渠道
- POST /api/notifiers/dispatch-alerts  把当前未确认告警打包推送
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/notifiers", tags=["notifiers"])


class ChannelSaveRequest(BaseModel):
    enabled: bool = Field(default=False)
    config: dict = Field(default_factory=dict, description="渠道凭证(各渠道字段不同)")


class DispatchRequest(BaseModel):
    title: str = Field(default="AlphaScope 通知")
    body: str = Field(default="")


@router.get("")
def list_channels():
    from backend import notifier_store

    return ApiResponse(success=True, data={"channels": notifier_store.list_channels()})


# 注意路由顺序:字面路径 /dispatch 与 /dispatch-alerts 必须先于参数路径 /{channel},
# 否则 POST /dispatch 会被 /{channel} 吞(channel="dispatch")。


@router.post("/dispatch")
def dispatch_message(req: DispatchRequest):
    """把一条消息推送到所有已启用渠道,返回每个渠道的结果。"""
    from backend import notifier_store
    from backend.notifiers import dispatch

    results = []
    for ch in notifier_store.list_channels():
        if not ch["enabled"]:
            continue
        cfg = notifier_store.get_channel_config(ch["channel"])
        r = dispatch(
            ch["channel"],
            {k: v for k, v in cfg.items() if k != "_enabled"},
            req.title,
            req.body,
        )
        results.append(r.to_dict())
    sent = sum(1 for r in results if r["ok"])
    return ApiResponse(
        success=True, data={"results": results, "sent": sent, "total": len(results)}
    )


@router.post("/dispatch-alerts")
def dispatch_alerts():
    """把当前所有未确认告警打包成一条消息,推送到已启用渠道。"""
    from backend import alert_store
    from backend import notifier_store
    from backend.notifiers import dispatch

    alerts = alert_store.list_alerts(unacknowledged_only=True, limit=50)
    if not alerts:
        return ApiResponse(success=True, data={"sent": False, "reason": "无未确认告警"})

    lines = [f"共 {len(alerts)} 条未确认告警:\n"]
    for a in alerts[:20]:
        lines.append(f"- [{a['severity']}] {a['message']}")
    body = "\n".join(lines)
    title = f"AlphaScope 告警({len(alerts)} 条)"

    results = []
    for ch in notifier_store.list_channels():
        if not ch["enabled"]:
            continue
        cfg = notifier_store.get_channel_config(ch["channel"])
        r = dispatch(
            ch["channel"],
            {k: v for k, v in cfg.items() if k != "_enabled"},
            title,
            body,
        )
        results.append(r.to_dict())

    # 推送成功后把告警标记为已确认,避免重复推送
    if any(r["ok"] for r in results):
        alert_store.acknowledge_all()

    return ApiResponse(
        success=True,
        data={"results": results, "alert_count": len(alerts)},
    )


@router.post("/{channel}")
def save_channel(channel: str, req: ChannelSaveRequest):
    from backend import notifier_store
    from backend.notifiers import CHANNELS

    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"未知渠道: {channel}")
    notifier_store.save_channel(channel, req.enabled, req.config)
    return ApiResponse(success=True, data={"channels": notifier_store.list_channels()})


@router.delete("/{channel}")
def delete_channel(channel: str):
    from backend import notifier_store

    ok = notifier_store.delete_channel(channel)
    return ApiResponse(success=ok, data={"channels": notifier_store.list_channels()})


@router.post("/{channel}/test")
def test_channel(channel: str):
    from backend import notifier_store
    from backend.notifiers import CHANNELS, dispatch

    if channel not in CHANNELS:
        raise HTTPException(status_code=400, detail=f"未知渠道: {channel}")
    cfg = notifier_store.get_channel_config(channel)
    if not cfg.get("_enabled") and not cfg:
        raise HTTPException(status_code=400, detail="渠道未配置或未启用")
    result = dispatch(
        channel,
        {k: v for k, v in cfg.items() if k != "_enabled"},
        "AlphaScope 测试通知",
        "这是一条来自研策中枢 AlphaScope 的测试消息。如果你收到了,说明渠道配置正确。",
    )
    return ApiResponse(success=result.ok, data=result.to_dict())

