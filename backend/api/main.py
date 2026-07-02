"""
FastAPI 主入口 (v0.50)

提供完整的 REST API 和 SSE 流式输出：
- /api/chat/stream — 对话流式输出 (SSE)
- /api/analysis/run — 运行 Agent 分析
- /api/vision/analyze — 图片/K线图分析
- /api/agents — Agent 配置管理
- /api/teams — 专家团管理
- /api/models/providers — 模型供应商管理
- /api/reports — 分析报告
- /api/conversations — 对话管理
- /api/knowledge — 知识库管理

使用方式：
    uvicorn backend.api.main:app --reload --port 8000
"""

import asyncio
import hmac
import json
import logging
import os
import re
import tomllib
from pathlib import Path
from typing import AsyncGenerator, Any, Optional

logger = logging.getLogger(__name__)

# 启动时加载项目根 .env (若存在), 使 AI_FINANCE_MASTER_KEY 等配置对后端可用
try:
    from dotenv import load_dotenv

    _ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE)
        logger.info("已加载环境配置: %s", _ENV_FILE)
except ImportError:
    pass


def _load_api_version() -> str:
    env_version = os.environ.get("ALPHASCOPE_VERSION", "").strip()
    if env_version:
        return env_version

    pyproject_path = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        with pyproject_path.open("rb") as file:
            project = tomllib.load(file).get("project", {})
        version = project.get("version")
        if isinstance(version, str) and version.strip():
            return version
    except OSError:
        logger.warning("Unable to read project version from %s", pyproject_path)
    except tomllib.TOMLDecodeError:
        logger.warning("Unable to parse project version from %s", pyproject_path)
    return "0.0.0"


def _split_csv_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [item.strip() for item in value.split(",") if item.strip()]


def _cors_middleware_options() -> dict[str, Any]:
    if os.environ.get("ALPHASCOPE_ALLOW_ALL_CORS", "").strip() == "1":
        return {
            "allow_origins": ["*"],
            "allow_origin_regex": None,
        }

    return {
        "allow_origins": _split_csv_env("ALPHASCOPE_CORS_ORIGINS"),
        "allow_origin_regex": os.environ.get(
            "ALPHASCOPE_CORS_ORIGIN_REGEX",
            r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
        ),
    }


def _safe_float_for_api(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


try:
    from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

if HAS_FASTAPI:
    from backend.price_store import get_prices
    from backend.schemas.api import (
        AnalysisRequest,
        AnalysisResultData,
        ApiResponse,
        ChatRequest,
        ConversationCreate,
        ConversationData,
        FileUploadData,
        HealthData,
        ReportData,
        SearchData,
        TeamData,
    )

    api_version = _load_api_version()

    app = FastAPI(
        title="研策中枢 AlphaScope API",
        description="研策中枢 AlphaScope API — 多 Agent 异构分析、专家团、K线图视觉分析",
        version=api_version,
    )

    app.add_middleware(
        CORSMiddleware,
        **_cors_middleware_options(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    LOCAL_TOKEN_HEADER = "X-AlphaScope-Local-Token"
    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def _local_api_token() -> str:
        return os.environ.get("ALPHASCOPE_LOCAL_API_TOKEN", "").strip()

    def _is_local_token_required(request: Request) -> bool:
        return bool(_local_api_token()) and request.method.upper() not in SAFE_METHODS

    def _has_valid_local_token(request: Request) -> bool:
        expected = _local_api_token()
        provided = request.headers.get(LOCAL_TOKEN_HEADER, "")
        return bool(provided) and hmac.compare_digest(provided, expected)

    @app.middleware("http")
    async def enforce_local_api_token(request: Request, call_next):
        if _is_local_token_required(request) and not _has_valid_local_token(request):
            return JSONResponse(
                status_code=401,
                content=ApiResponse(
                    success=False,
                    error="Missing or invalid local API token",
                ).model_dump(),
            )
        return await call_next(request)

    # ============== 注册路由 ==============

    from backend.api.settings import router as settings_router
    from backend.api.reports import router as reports_router
    from backend.api.tasks import router as tasks_router
    from backend.api.agents import router as agents_router
    from backend.api.knowledge import router as knowledge_router
    from backend.api.evidence import router as evidence_router
    from backend.api.prices import router as prices_router
    from backend.api.technical import router as technical_router
    from backend.api.fundamentals import router as fundamentals_router
    from backend.api.news import router as news_router
    from backend.api.vision import router as vision_router
    from backend.api.diagnostics import router as diagnostics_router
    from backend.api.fund_flow import router as fund_flow_router
    from backend.api.factors import router as factors_router
    from backend.api.quant import router as quant_router
    from backend.api.funds import router as funds_router
    from backend.api.portfolio_new import router as portfolio_router
    from backend.api.report_gen import router as report_gen_router
    from backend.api.stocks import router as stocks_router
    from backend.api.valuation import router as valuation_router
    from backend.api.dragon_tiger import router as dragon_tiger_router
    from backend.api.export import router as export_router
    from backend.api.quality import router as quality_router
    from backend.api.experts import router as experts_router
    from backend.api.brief import router as brief_router
    from backend.api.watchlist import router as watchlist_router
    from backend.api.datasources import router as datasources_router
    from backend.api.csv_upload import router as csv_upload_router
    from backend.api.monitor import router as monitor_router
    from backend.api.research_memory import router as research_memory_router
    from backend.api.tickflow import router as tickflow_router
    from backend.api.datalake import router as datalake_router
    from backend.api.factor_registry import router as factor_registry_router
    from backend.api.integrations import router as integrations_router
    from backend.api.alerts import router as alerts_router
    from backend.api.portfolio_calc import router as portfolio_calc_router
    from backend.api.notifiers import router as notifiers_router

    # 启动时把已保存的数据源凭证注入环境变量, 使 provider 自动注册时可用
    from backend.datasource_config import init_credentials_on_startup

    init_credentials_on_startup()

    app.include_router(settings_router)
    app.include_router(reports_router)
    app.include_router(tasks_router)
    app.include_router(agents_router)
    app.include_router(knowledge_router)
    app.include_router(evidence_router)
    app.include_router(prices_router)
    app.include_router(technical_router)
    app.include_router(fundamentals_router)
    app.include_router(news_router)
    app.include_router(vision_router)
    app.include_router(diagnostics_router)
    app.include_router(fund_flow_router)
    app.include_router(factors_router)
    app.include_router(quant_router)
    app.include_router(funds_router)
    # portfolio_calc 须在 portfolio_new 之前注册:其 /positions /optimizers 等单段路径
    # 否则会被 portfolio_new 的 /{portfolio_id} 参数路由先吞掉。
    app.include_router(portfolio_calc_router)
    app.include_router(portfolio_router)
    app.include_router(report_gen_router)
    app.include_router(stocks_router)
    app.include_router(valuation_router)
    app.include_router(dragon_tiger_router)
    app.include_router(export_router)
    app.include_router(quality_router)
    app.include_router(experts_router)
    app.include_router(brief_router)
    app.include_router(watchlist_router)
    app.include_router(datasources_router)
    app.include_router(csv_upload_router)
    app.include_router(monitor_router)
    app.include_router(research_memory_router)
    app.include_router(tickflow_router)
    app.include_router(datalake_router)
    app.include_router(factor_registry_router)
    app.include_router(integrations_router)
    app.include_router(alerts_router)
    app.include_router(notifiers_router)

    # ============== 启动钩子: 后台监控 ==============

    @app.on_event("startup")
    def _startup_hook():
        # 启动自选股定时监控后台线程(非阻塞,失败不影响 API)
        try:
            from backend.ingestion.startup import auto_startup

            auto_startup()
        except Exception as e:  # noqa: BLE001
            logger.warning("启动监控后台线程失败: %s", e)

    # ============== 全局错误处理 ==============

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=ApiResponse(success=False, error=exc.detail).model_dump(),
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content=ApiResponse(success=False, error="内部服务器错误").model_dump(),
        )

    # ============== 健康检查 ==============

    @app.get("/", response_model=ApiResponse[dict[str, Any]])
    async def root():
        return ApiResponse(
            success=True,
            data={
                "status": "ok",
                "service": "研策中枢 AlphaScope API",
                "version": api_version,
            },
        )

    @app.get("/health", response_model=ApiResponse[HealthData])
    async def health():
        return ApiResponse(
            success=True,
            data=HealthData(status="healthy", version=api_version),
        )

    @app.get("/api/providers/health", response_model=ApiResponse[dict[str, Any]])
    def providers_health():
        """数据源健康状态(含质量分 v1.9.4)"""
        from backend.observability.source_health import compute_quality_score
        from backend.providers.registry import get_registry

        registry = get_registry()
        providers = []
        healthy = degraded = unhealthy = 0
        good = warn = poor = 0
        for name, provider in registry._providers.items():
            h = provider.health
            status = h.status.value if hasattr(h.status, "value") else str(h.status)
            if status == "healthy":
                healthy += 1
            elif status == "degraded":
                degraded += 1
            else:
                unhealthy += 1
            entry = {
                "name": name,
                "status": status,
                "consecutive_failures": h.consecutive_failures,
                "avg_latency_ms": round(h.avg_latency_ms, 1),
                "last_success": h.last_success,
                "last_error": h.error_message,
                "data_types": provider.data_types,
                "markets": provider.markets,
            }
            # 质量分: 成功率 × 新鲜度 × 完整度, 0-100 + 红黄绿 grade
            q = compute_quality_score(entry)
            entry.update(q)
            if q["grade"] == "good":
                good += 1
            elif q["grade"] == "warn":
                warn += 1
            else:
                poor += 1
            providers.append(entry)
        avg_quality = (
            round(sum(p["quality_score"] for p in providers) / len(providers), 1)
            if providers
            else 0.0
        )
        return ApiResponse(
            success=True,
            data={
                "total": len(providers),
                "healthy": healthy,
                "degraded": degraded,
                "unhealthy": unhealthy,
                "quality_good": good,
                "quality_warn": warn,
                "quality_poor": poor,
                "avg_quality": avg_quality,
                "providers": providers,
            },
        )

    @app.get("/api/providers/capabilities", response_model=ApiResponse[dict[str, Any]])
    def providers_capabilities():
        """数据源能力描述(v1.9.4, deep-research ProviderCapability)

        用统一 schema 表达每个数据源的市场/数据类型/粒度/延迟/成本/速率限制/
        凭证需求/优先级/可降级, 供前端用同一套 UI 筛选展示(对标 tickflow tiers.yaml)。
        """
        from backend.providers.registry import get_registry

        registry = get_registry()
        caps = registry.get_all_capabilities()
        return ApiResponse(
            success=True,
            data={
                "total": len(caps),
                "capabilities": caps,
            },
        )

    # ============== 对话 API ==============

    @app.post("/api/conversations", response_model=ApiResponse[ConversationData])
    def create_conversation(req: ConversationCreate):
        """创建新对话"""
        from backend.ai_assistant.conversation_store import ConversationStore
        from backend.storage.db import Database

        store = ConversationStore(db=Database())
        provider = ""
        model = ""
        try:
            from backend.models.provider_gateway import get_configured_provider

            provider, model = get_configured_provider()
        except Exception:
            provider, model = "deepseek", "deepseek-chat"
        conv_id = store.create_conversation(
            title=req.title,
            stock_symbol=req.stock_symbol or "",
            stock_name=req.stock_name or "",
            mode=req.mode,
            provider=provider,
            model=model,
        )
        return ApiResponse(
            success=True,
            data=ConversationData(id=conv_id, title=req.title, mode=req.mode),
            message="对话已创建",
        )

    @app.get("/api/conversations", response_model=ApiResponse[dict[str, Any]])
    def list_conversations(stock_symbol: Optional[str] = None, limit: int = Query(20, ge=1, le=500)):
        """列出对话"""
        from backend.ai_assistant.conversation_store import ConversationStore
        from backend.storage.db import Database

        store = ConversationStore(db=Database())
        convs = store.list_conversations(stock_symbol=stock_symbol, limit=limit)
        return ApiResponse(success=True, data={"conversations": convs})

    @app.get(
        "/api/conversations/{conversation_id}",
        response_model=ApiResponse[dict[str, Any]],
    )
    def get_conversation(conversation_id: str):
        """获取对话详情"""
        from backend.ai_assistant.conversation_store import ConversationStore
        from backend.storage.db import Database

        store = ConversationStore(db=Database())
        conv = store.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="对话不存在")
        messages = store.get_messages(conversation_id)
        return ApiResponse(
            success=True, data={"conversation": conv, "messages": messages}
        )

    @app.delete(
        "/api/conversations/{conversation_id}",
        response_model=ApiResponse[dict[str, str]],
    )
    def delete_conversation(conversation_id: str):
        """删除对话"""
        from backend.ai_assistant.conversation_store import ConversationStore
        from backend.storage.db import Database

        store = ConversationStore(db=Database())
        store.delete_conversation(conversation_id)
        return ApiResponse(success=True, data={"status": "deleted"})

    # ============== 对话流式 API (SSE) ==============

    async def _sse_generator(
        result: dict, conversation_id: str
    ) -> AsyncGenerator[str, None]:
        """将分析结果转为 SSE 事件流"""
        status_event = {
            "type": "status",
            "mode": result.get("mode", "free"),
            "data": {"conversation_id": conversation_id},
        }
        yield f"data: {json.dumps(status_event)}\n\n"

        content = result.get("content", "")
        chunk_size = 20
        for i in range(0, len(content), chunk_size):
            chunk = content[i : i + chunk_size]
            yield f"data: {json.dumps({'type': 'content', 'chunk': chunk})}\n\n"
            await asyncio.sleep(0.02)

        evidence = result.get("evidence", [])
        if evidence:
            yield f"data: {json.dumps({'type': 'evidence', 'data': evidence})}\n\n"

        agents = result.get("agents", {})
        if agents:
            yield f"data: {json.dumps({'type': 'agents', 'data': agents})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    @app.post("/api/chat/stream")
    def chat_stream(req: ChatRequest):
        """对话流式输出 (SSE)"""
        from backend.ai_assistant.orchestrator import (
            AnalysisMode as ChatAnalysisMode,
            ChatOrchestrator,
        )

        orch = ChatOrchestrator()
        mode_was_explicit = "mode" in req.model_fields_set
        try:
            requested_mode = ChatAnalysisMode(req.mode)
        except ValueError:
            requested_mode = ChatAnalysisMode.FREE
        mode_override = requested_mode.value if mode_was_explicit else None

        conv_id = req.conversation_id
        if not conv_id:
            conv_id = orch.new_conversation(
                stock_symbol=req.stock_symbol or "",
                stock_name=req.stock_name or "",
                mode=requested_mode,
            )

        stock_data = None
        if req.stock_symbol:
            stock_data = {"symbol": req.stock_symbol, "name": req.stock_name or ""}

        try:
            result = orch.send_message(
                conversation_id=conv_id,
                user_input=req.message,
                stock_data=stock_data,
                expert_team_id=req.expert_team_id,
                mode_override=mode_override,
                provider=(req.provider or "").strip() or None,
                model=(req.model or "").strip() or None,
            )
        except Exception as e:
            logger.exception("Chat stream failed: %s", e)
            raise HTTPException(status_code=500, detail="内部服务器错误") from e

        return StreamingResponse(
            _sse_generator(result, conv_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/chat", response_model=ApiResponse[dict[str, Any]])
    def chat(req: ChatRequest):
        """真实模型对话。用于主工作台聊天框的非流式调用。"""
        from backend.ai_assistant.orchestrator import (
            AnalysisMode as ChatAnalysisMode,
            ChatOrchestrator,
        )

        orch = ChatOrchestrator()
        try:
            requested_mode = ChatAnalysisMode(req.mode)
        except ValueError:
            requested_mode = ChatAnalysisMode.FREE

        provider = (req.provider or "").strip()
        model = (req.model or "").strip()
        conv_id = req.conversation_id
        if not conv_id:
            conv_id = orch.new_conversation(
                stock_symbol=req.stock_symbol or "",
                stock_name=req.stock_name or "",
                mode=requested_mode,
                provider=provider,
                model=model,
            )

        stock_data = None
        if req.stock_symbol:
            context = req.context or {}
            stock_data = {
                "symbol": req.stock_symbol,
                "name": req.stock_name or "",
                "close": _safe_float_for_api(context.get("close")),
                "day_change": _safe_float_for_api(context.get("day_change")),
                "period_change": _safe_float_for_api(context.get("period_change")),
                "ma5": context.get("ma5", "N/A"),
                "ma20": context.get("ma20", "N/A"),
                "ma60": context.get("ma60", "N/A"),
                "fund_dir": str(context.get("fund_dir") or "暂无主力资金数据"),
                "data_date": str(context.get("data_date") or ""),
            }

        try:
            result = orch.send_message(
                conversation_id=conv_id,
                user_input=req.message,
                stock_data=stock_data,
                expert_team_id=req.expert_team_id,
                mode_override=requested_mode.value,
                provider=provider or None,
                model=model or None,
            )
        except Exception as e:
            logger.exception("Chat failed: %s", e)
            raise HTTPException(status_code=500, detail="模型调用失败") from e

        result["conversation_id"] = conv_id
        return ApiResponse(success=True, data=result)

    # ============== 分析 API ==============

    def _meaningful_price_bars(symbol: str, limit: int = 30) -> list[dict[str, Any]]:
        bars = get_prices(symbol, limit=limit)
        return [
            bar
            for bar in bars
            if any(
                _safe_float_for_api(bar.get(field)) > 0
                for field in ("open", "close", "high", "low", "volume")
            )
        ]

    @app.post("/api/analysis/run", response_model=ApiResponse[AnalysisResultData])
    def run_analysis(req: AnalysisRequest):
        """运行 Agent 分析"""
        from backend.runtime.orchestrator import run_agents_with_mode
        from backend.agent_modes import AnalysisMode

        mode_map = {
            "standard": AnalysisMode.STANDARD,
            "deep": AnalysisMode.DEEP,
            "auto": AnalysisMode.AUTO,
        }
        mode = mode_map.get(req.mode, AnalysisMode.DEEP)

        bars = _meaningful_price_bars(req.stock_symbol, limit=30)
        if not bars:
            return ApiResponse(success=False, error="行情数据不足，无法生成正常分析")

        bars = sorted(bars, key=lambda bar: str(bar.get("date") or ""))
        latest = bars[-1]
        previous = bars[-2] if len(bars) > 1 else latest
        latest_close = _safe_float_for_api(latest.get("close"))
        previous_close = _safe_float_for_api(previous.get("close"))
        first_close = _safe_float_for_api(bars[0].get("close"))

        stock_data = {
            "symbol": req.stock_symbol,
            "name": req.stock_name,
            "close": latest_close,
            "day_change": latest_close - previous_close,
            "period_change": latest_close - first_close,
            "period_high": max(_safe_float_for_api(bar.get("high")) for bar in bars),
            "period_low": min(_safe_float_for_api(bar.get("low")) for bar in bars),
            "days": len(bars),
            "volume": _safe_float_for_api(latest.get("volume")),
            "total_amount": _safe_float_for_api(latest.get("amount")),
        }

        result = run_agents_with_mode(
            stock_data=stock_data,
            mode=mode,
            agent_configs=req.agent_configs,
            global_ai_settings=req.global_ai_settings,
        )
        model_status = result.get("model_status") or {}
        total_agents = int(model_status.get("total_agents") or 0)
        ok_agents = int(model_status.get("ok_agents") or 0)
        all_agents_failed = total_agents > 0 and ok_agents == 0

        # 研究记忆(v1.9.18):把本次结论快照旁路落库, 供「研究记忆」页回看结论随时间变化。
        # 失败安全 —— 记不上绝不影响分析返回。
        try:
            from backend.quant import research_memory

            research_memory.record_snapshot(
                req.stock_symbol, req.stock_name, result, stock_data
            )
        except Exception:
            pass

        return ApiResponse(
            success=not all_agents_failed,
            error=model_status.get("message") if all_agents_failed else None,
            error_code="analysis_all_agents_failed" if all_agents_failed else None,
            data=AnalysisResultData(
                stock_symbol=req.stock_symbol,
                stock_name=req.stock_name,
                mode=result.get("mode", req.mode),
                result={
                    "summary": result.get("summary"),
                    "brief": result.get("brief"),
                    "research_report": result.get("research_report"),
                    "agents": {
                        k: {
                            "signal": v.get("signal"),
                            "confidence": v.get("confidence"),
                            "reason": v.get("reason"),
                            "evidence_ids": v.get("evidence_ids", []),
                        }
                        for k, v in result.get("agents", {}).items()
                    },
                    "critic": result.get("critic"),
                    "chairman_summary": result.get("chairman_summary"),
                    "evidence_pool": result.get("evidence_pool", []),
                    "risk_gate": result.get("risk_gate"),
                    "debate": result.get("debate"),
                    "data_verification": result.get("data_verification"),
                    "model_status": model_status,
                    "mode_name": result.get("mode_name"),
                },
            ),
        )

    # ============== 视觉分析 API (已迁移至 backend/api/vision.py) ==============

    # ============== Agent 配置 API ==============

    @app.get("/api/agents", response_model=ApiResponse[dict[str, Any]])
    def list_agents():
        """列出所有 Agent 配置"""
        from backend.agents.base import get_default_agent_configs

        return ApiResponse(success=True, data={"agents": get_default_agent_configs()})

    @app.get("/api/agents/models", response_model=ApiResponse[dict[str, Any]])
    def list_agent_models():
        """列出 Agent 模型分配表"""
        from backend.agents.financial_agents import get_agent_model_table

        table = get_agent_model_table()
        return ApiResponse(
            success=True,
            data={
                "agents": [
                    {"key": k, "name": n, "vendor": v, "model": m}
                    for k, n, v, m in table
                ]
            },
        )

    # ============== 专家团 API ==============

    @app.get("/api/teams", response_model=ApiResponse[dict[str, Any]])
    def list_teams():
        """列出所有专家团"""
        from backend.teams.team_loader import list_team_names

        return ApiResponse(success=True, data={"teams": list_team_names()})

    @app.get("/api/teams/{team_id}", response_model=ApiResponse[TeamData])
    def get_team(team_id: str):
        """获取专家团详情"""
        from backend.teams.team_loader import get_team

        team = get_team(team_id)
        if not team:
            raise HTTPException(status_code=404, detail="专家团不存在")
        return ApiResponse(
            success=True,
            data=TeamData(
                id=team.id,
                name=team.name,
                description=team.description,
                members=[
                    {
                        "id": m.id,
                        "name": m.name,
                        "role": m.role,
                        "provider": m.provider,
                        "model": m.model,
                    }
                    for m in team.members
                ],
            ),
        )

    # ============== 模型供应商 API ==============

    @app.get("/api/models/providers", response_model=ApiResponse[dict[str, Any]])
    def list_providers():
        """列出所有模型供应商"""
        from backend.models.provider_gateway import get_provider_list

        return ApiResponse(success=True, data={"providers": get_provider_list()})

    @app.get(
        "/api/models/providers/{provider_id}/models",
        response_model=ApiResponse[dict[str, Any]],
    )
    def list_provider_models(provider_id: str):
        """列出指定供应商的模型"""
        from backend.models.provider_gateway import get_provider_models

        models = get_provider_models(provider_id)
        return ApiResponse(success=True, data={"models": models})

    # ============== 报告 API ==============

    @app.get("/api/reports/{report_id}", response_model=ApiResponse[ReportData])
    def get_report(report_id: str):
        """获取分析报告"""
        from backend.ai_assistant.report_generator import generate_report
        from backend.ai_assistant.conversation_store import ConversationStore
        from backend.storage.db import Database

        store = ConversationStore(db=Database())
        conv = store.get_conversation(report_id)
        if not conv:
            raise HTTPException(status_code=404, detail="报告不存在")
        messages = store.get_messages(report_id)
        md = generate_report(conv, messages)
        return ApiResponse(
            success=True,
            data=ReportData(
                id=report_id,
                title=conv.get("title", ""),
                content=md,
                conversation_id=report_id,
                created_at=conv.get("created_at"),
            ),
        )

    # ============== 分析模式 API ==============

    @app.get("/api/modes", response_model=ApiResponse[dict[str, Any]])
    def list_modes():
        """列出所有分析模式"""
        from backend.agent_modes import get_mode_choices

        return ApiResponse(success=True, data={"modes": get_mode_choices()})

    # ============== 文件上传 API ==============

    @app.post("/api/files/upload", response_model=ApiResponse[FileUploadData])
    async def upload_file(file: UploadFile = File(...)):
        """上传文件（图片/文档）— 支持 multipart/form-data"""
        import hashlib
        from pathlib import Path

        raw_filename = file.filename or "upload.png"
        filename = Path(raw_filename).name.strip()
        filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._-")
        if not filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        suffix = Path(filename).suffix.lower()
        supported = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".webp",
            ".bmp",
            ".pdf",
            ".csv",
            ".xlsx",
        }
        if suffix not in supported:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {suffix}")

        content = await file.read()
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件大小超过 20MB 限制")

        file_hash = hashlib.sha256(content).hexdigest()[:16]

        from backend.project_paths import UPLOADS_DIR

        upload_dir = UPLOADS_DIR
        upload_dir.mkdir(parents=True, exist_ok=True)
        save_path = upload_dir / f"{file_hash}_{filename}"
        if not save_path.resolve().is_relative_to(upload_dir.resolve()):
            raise HTTPException(status_code=400, detail="Invalid filename")
        save_path.write_bytes(content)

        return ApiResponse(
            success=True,
            data=FileUploadData(
                filename=filename,
                size=len(content),
                path=filename,
                message="上传成功",
            ),
        )

    # ============== 研究任务模板 API ==============

    @app.get("/api/templates", response_model=ApiResponse[dict[str, Any]])
    async def list_templates():
        """列出研究任务模板"""
        from backend.runtime.task_templates import list_templates

        return ApiResponse(success=True, data={"templates": list_templates()})

    @app.get("/api/templates/{template_id}", response_model=ApiResponse[dict[str, Any]])
    async def get_template(template_id: str):
        """获取模板详情"""
        from backend.runtime.task_templates import get_template

        t = get_template(template_id)
        if not t:
            raise HTTPException(status_code=404, detail="模板不存在")
        return ApiResponse(
            success=True,
            data={
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "icon": t.icon,
                "mode": t.mode,
                "requires_stock": t.requires_stock,
                "system_prompt": t.system_prompt,
                "output_format": t.output_format,
                "steps": t.steps,
            },
        )

    # ============== Web 搜索 API ==============

    @app.get("/api/search", response_model=ApiResponse[SearchData])
    def web_search(query: str, max_results: int = 5):
        """联网搜索"""
        from backend.providers.web_search_provider import get_web_search_provider

        provider = get_web_search_provider()
        if not provider.is_available():
            raise HTTPException(
                status_code=503, detail="搜索服务未配置 (需要 TAVILY_API_KEY)"
            )

        results = provider.search(query, max_results)
        return ApiResponse(
            success=True,
            data=SearchData(
                query=query,
                results=[
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                        "score": r.score,
                    }
                    for r in results
                ],
                source="tavily",
            ),
        )

    # ============== 成本统计 API ==============

    @app.get("/api/costs", response_model=ApiResponse[dict[str, Any]])
    def get_costs(mode: Optional[str] = None):
        """获取 LLM 调用成本统计"""
        from backend.observability.cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        return ApiResponse(success=True, data=tracker.get_summary(mode=mode))

    # ============== 回测 API ==============

    @app.get("/api/backtest/stats", response_model=ApiResponse[dict[str, Any]])
    def get_backtest_stats(mode: Optional[str] = None):
        """获取后验验证统计"""
        from backend.archive.backtester import get_backtester

        bt = get_backtester()
        return ApiResponse(success=True, data=bt.get_performance_stats(mode=mode))

    @app.get("/api/backtest/agent-accuracy", response_model=ApiResponse[dict[str, Any]])
    def get_agent_accuracy():
        """按 Agent 统计准确率"""
        from backend.archive.backtester import get_backtester

        bt = get_backtester()
        return ApiResponse(success=True, data={"agents": bt.get_agent_accuracy()})

    @app.get("/api/backtest/pending", response_model=ApiResponse[dict[str, Any]])
    def get_pending_evaluations():
        """获取待评估的决策"""
        from backend.archive.backtester import get_backtester

        bt = get_backtester()
        return ApiResponse(success=True, data={"pending": bt.get_pending_evaluations()})

    # ============== 审计日志 API ==============

    @app.get("/api/audit", response_model=ApiResponse[dict[str, Any]])
    def get_audit_logs(limit: int = Query(50, ge=1, le=1000)):
        """获取审计日志"""
        from backend.storage.db import Database

        db = Database()
        conn = db.conn
        rows = conn.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return ApiResponse(
            success=True,
            data={
                "logs": [
                    {
                        "id": r[0],
                        "action": r[1],
                        "target_type": r[2],
                        "target_id": r[3],
                        "metadata": r[4],
                        "created_at": r[5],
                    }
                    for r in rows
                ]
            },
        )

else:
    app = None
