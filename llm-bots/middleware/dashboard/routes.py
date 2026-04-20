"""Dashboard routes: pages, JSON API, and the SSE trace stream."""

from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

import dashboard.app as appmod
from api.models import (
    CostLimitRequest,
    ElevateRequest,
    ForceSayRequest,
    PersonalityUpdateRequest,
)
from core.config import settings
from core.trace_store import trace_row_to_dict
from game.events import AdminForceSayEvent
from personality.loader import list_profiles, reload_profile

logger = structlog.get_logger()

app = appmod.app
templates = appmod.templates


# -- Require helpers (match api/admin.py pattern) ------------------------------


def _require_registry():
    if appmod.registry is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.registry


def _require_qdrant():
    if appmod.qdrant is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.qdrant


def _require_cost():
    if appmod.cost is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.cost


def _require_supervisor():
    if appmod.supervisor is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.supervisor


def _require_bus():
    if appmod.event_bus is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.event_bus


def _require_trace_store():
    if appmod.trace_store is None:
        raise HTTPException(503, "Service not initialized")
    return appmod.trace_store


# -- Helpers -------------------------------------------------------------------


def _roster() -> list[dict]:
    if appmod.registry is None or appmod.supervisor is None:
        return []
    snaps = appmod.supervisor.last_snapshots
    out = []
    for profile in appmod.registry.all_elevated():
        snap = snaps.get(profile.guid)
        out.append(
            {
                "guid": profile.guid,
                "name": profile.name,
                "personality": profile.personality,
                "zone": (snap.zone if snap else "") or "—",
                "state": (snap.state if snap else "unknown"),
                "hp_pct": snap.hp_pct if snap else 0,
                "last_action": profile.last_llm_action or "—",
                "llm_calls": profile.total_llm_calls,
                "cost_usd": round(profile.total_cost_usd, 4),
                "degraded": appmod.registry.is_degraded(profile.guid),
            }
        )
    out.sort(key=lambda r: r["name"].lower())
    return out


def _cost_summary() -> dict:
    if appmod.cost is None:
        return {}
    m = appmod.cost.get_metrics()
    m["active_agents"] = appmod.registry.count if appmod.registry else 0
    m["max_agents"] = settings.max_active_agents
    return m


def _scale_summary() -> dict:
    """M7 scale/health surface for the dashboard."""
    out: dict = {
        "auto_elevation_enabled": settings.auto_elevation_enabled,
        "max_agents": settings.max_active_agents,
        "pinned": 0,
        "auto": 0,
        "degraded": 0,
        "budget_state": "normal",
        "global_backoff_active": False,
        "global_backoff_remaining_s": 0.0,
        "rate_limit_errors_total": 0,
    }
    if appmod.registry is not None:
        out["pinned"] = len(appmod.registry.all_pinned())
        out["auto"] = len(appmod.registry.all_auto_elevated())
        out["degraded"] = sum(
            1
            for p in appmod.registry.all_elevated()
            if appmod.registry.is_degraded(p.guid)
        )
    if appmod.cost is not None:
        m = appmod.cost.get_metrics()
        out["budget_state"] = m["budget_state"]
        out["global_backoff_active"] = m["global_backoff_active"]
        out["global_backoff_remaining_s"] = m["global_backoff_remaining_s"]
        out["rate_limit_errors_total"] = m["rate_limit_errors_total"]
    return out


# -- Pages (server-rendered HTML) ---------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def page_index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "roster": _roster(),
            "cost": _cost_summary(),
            "scale": _scale_summary(),
            "personalities": list_profiles(),
        },
    )


@app.get("/memories", response_class=HTMLResponse)
async def page_memories(
    request: Request,
    guid: int | None = None,
    q: str = "everything",
    limit: int = 20,
):
    memories: list[dict] = []
    bot_name = ""
    if guid is not None and appmod.qdrant is not None:
        profile = appmod.registry.get(guid) if appmod.registry else None
        bot_name = profile.name if profile else ""
        results = await appmod.qdrant.recall(bot_guid=guid, query=q, limit=limit)
        memories = [
            {
                "id": m.id,
                "type": m.memory_type.value,
                "content": m.content,
                "importance": m.importance,
                "related_players": m.related_players,
                "created_at": m.created_at.isoformat(),
            }
            for m in results
        ]
    return templates.TemplateResponse(
        request,
        "memories.html",
        {
            "roster": _roster(),
            "memories": memories,
            "guid": guid,
            "bot_name": bot_name,
            "query": q,
            "limit": limit,
        },
    )


# -- HTMX partial fragments ---------------------------------------------------


@app.get("/fragments/roster", response_class=HTMLResponse)
async def frag_roster(request: Request):
    return templates.TemplateResponse(
        request,
        "partials/roster_table.html",
        {"roster": _roster()},
    )


@app.get("/fragments/cost", response_class=HTMLResponse)
async def frag_cost(request: Request):
    return templates.TemplateResponse(
        request,
        "partials/cost_strip.html",
        {"cost": _cost_summary()},
    )


@app.get("/fragments/scale", response_class=HTMLResponse)
async def frag_scale(request: Request):
    return templates.TemplateResponse(
        request,
        "partials/scale_strip.html",
        {"scale": _scale_summary()},
    )


# -- JSON API (mirrors /admin/* for dashboard-local use) ----------------------


@app.get("/api/roster")
async def api_roster():
    return {"roster": _roster()}


@app.get("/api/cost")
async def api_cost():
    return _cost_summary()


@app.get("/api/scale")
async def api_scale():
    return _scale_summary()


@app.post("/api/auto-elevation/enable")
async def api_auto_elevation_enable():
    settings.auto_elevation_enabled = True
    logger.info("dashboard.auto_elevation_enabled")
    return {"status": "enabled"}


@app.post("/api/auto-elevation/disable")
async def api_auto_elevation_disable():
    settings.auto_elevation_enabled = False
    logger.info("dashboard.auto_elevation_disabled")
    return {"status": "disabled"}


@app.get("/api/traces")
async def api_traces(
    bot_guid: int | None = None,
    limit: int = Query(default=100, le=500),
    before_id: int | None = None,
):
    store = _require_trace_store()
    rows = await store.recent(
        bot_guid=bot_guid, limit=limit, before_id=before_id
    )
    return {"traces": [trace_row_to_dict(r) for r in rows]}


@app.get("/api/personalities")
async def api_personalities():
    return {"profiles": list_profiles()}


@app.post("/api/bots/{guid}/elevate")
async def api_elevate(guid: int, body: ElevateRequest):
    reg = _require_registry()
    if not reg.elevate(guid, body.name, body.personality):
        raise HTTPException(429, "At max agent capacity")
    logger.info(
        "dashboard.elevate", guid=guid, name=body.name, personality=body.personality
    )
    return {"status": "elevated", "guid": guid}


@app.post("/api/bots/{guid}/demote")
async def api_demote(guid: int):
    reg = _require_registry()
    if not reg.demote(guid):
        raise HTTPException(404, "Bot not elevated")
    logger.info("dashboard.demote", guid=guid)
    return {"status": "demoted", "guid": guid}


@app.post("/api/bots/{guid}/personality")
async def api_personality(guid: int, body: PersonalityUpdateRequest):
    reg = _require_registry()
    profile = reg.get(guid)
    if not profile:
        raise HTTPException(404, "Bot not elevated")
    profile.personality = body.personality
    reload_profile(body.personality)
    sup = appmod.supervisor
    if sup is not None:
        agent = sup.get_agent(guid)
        if agent is not None:
            agent.reload_system_prompt()
    logger.info("dashboard.personality_swap", guid=guid, personality=body.personality)
    return {"status": "updated", "guid": guid, "personality": body.personality}


@app.delete("/api/bots/{guid}/memories")
async def api_clear_memories(guid: int):
    qdrant = _require_qdrant()
    qdrant.clear_bot_memories(guid)
    logger.info("dashboard.memories_cleared", guid=guid)
    return {"status": "cleared", "guid": guid}


@app.post("/api/bots/{guid}/say")
async def api_force_say(guid: int, body: ForceSayRequest):
    reg = _require_registry()
    bus = _require_bus()
    profile = reg.get(guid)
    if not profile:
        raise HTTPException(404, "Bot not elevated")
    await bus.publish(
        AdminForceSayEvent(bot_guid=guid, bot_name=profile.name, text=body.text)
    )
    logger.info("dashboard.force_say", guid=guid, text=body.text)
    return {"status": "queued"}


@app.post("/api/cost/limit")
async def api_cost_limit(body: CostLimitRequest):
    cost = _require_cost()
    cost.set_hourly_limit(body.hourly_limit_usd)
    logger.info("dashboard.cost_limit_updated", limit_usd=cost.hourly_limit)
    return {"status": "updated", "hourly_limit_usd": cost.hourly_limit}


# -- SSE trace stream ---------------------------------------------------------


def _trace_to_sse_dict(trace) -> dict:
    """Convert an AgentTrace into the same dict shape as TraceStore rows."""
    return {
        "bot_guid": trace.bot_guid,
        "bot_name": trace.bot_name,
        "event_type": trace.event_type,
        "model": trace.model,
        "tokens_in": trace.tokens_in,
        "tokens_out": trace.tokens_out,
        "cost_usd": round(trace.cost_usd, 6),
        "tool_calls": list(trace.tool_calls),
        "latency_ms": round(trace.latency_ms),
        "response_preview": trace.response_preview,
    }


@app.get("/api/traces/stream")
async def api_trace_stream(bot_guid: int | None = None):
    """Server-Sent Events stream of completed agent traces."""
    sup = _require_supervisor()
    queue = sup.subscribe_traces()

    async def gen():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    trace = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if bot_guid is not None and trace.bot_guid != bot_guid:
                    continue
                yield (
                    "event: trace\n"
                    f"data: {json.dumps(_trace_to_sse_dict(trace))}\n\n"
                )
        finally:
            sup.unsubscribe_traces(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/healthz")
async def healthz():
    sup = appmod.supervisor
    return {
        "ok": True,
        "subscribers": sup.trace_subscriber_count if sup else 0,
    }
