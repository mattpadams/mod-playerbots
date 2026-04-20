"""Admin API endpoints for managing LLM-elevated bots."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.models import (
    CostLimitRequest,
    ElevateRequest,
    ForceSayRequest,
    PersonalityUpdateRequest,
)
from core.bot_registry import BotRegistry
from core.event_bus import EventBus
from core.trace_store import TraceStore, trace_row_to_dict
from game.events import AdminForceSayEvent
from memory.qdrant_store import QdrantStore
from personality.loader import list_profiles, reload_profile
from scheduler.cost_controller import CostController

router = APIRouter(prefix="/admin", tags=["admin"])

# These will be injected at app startup via init()
_registry: BotRegistry | None = None
_qdrant: QdrantStore | None = None
_cost: CostController | None = None
_supervisor = None
_event_bus: EventBus | None = None
_trace_store: TraceStore | None = None


def init(
    registry: BotRegistry,
    qdrant: QdrantStore,
    cost: CostController,
    supervisor,
    event_bus: EventBus | None = None,
    trace_store: TraceStore | None = None,
) -> None:
    global _registry, _qdrant, _cost, _supervisor, _event_bus, _trace_store
    _registry = registry
    _qdrant = qdrant
    _cost = cost
    _supervisor = supervisor
    _event_bus = event_bus
    _trace_store = trace_store


def _require_registry() -> BotRegistry:
    if _registry is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _registry


def _require_qdrant() -> QdrantStore:
    if _qdrant is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _qdrant


def _require_cost() -> CostController:
    if _cost is None:
        raise HTTPException(status_code=503, detail="Service not initialized")
    return _cost


# -- Endpoints -----------------------------------------------------------------


@router.get("/bots")
async def list_bots():
    """List all elevated bots with their current status."""
    registry = _require_registry()
    bots = []
    for profile in registry.all_elevated():
        bots.append({
            "guid": profile.guid,
            "name": profile.name,
            "personality": profile.personality,
            "elevated_at": profile.elevated_at.isoformat(),
            "degraded": registry.is_degraded(profile.guid),
            "total_llm_calls": profile.total_llm_calls,
            "total_tokens_in": profile.total_tokens_in,
            "total_tokens_out": profile.total_tokens_out,
        })
    return {"bots": bots, "count": len(bots)}


@router.post("/bots/{guid}/elevate")
async def elevate_bot(guid: int, req: ElevateRequest):
    """Elevate a bot to LLM mode."""
    registry = _require_registry()
    if not registry.elevate(guid, req.name, req.personality):
        raise HTTPException(status_code=429, detail="At maximum agent capacity")
    return {"status": "elevated", "guid": guid, "name": req.name, "personality": req.personality}


@router.post("/bots/{guid}/demote")
async def demote_bot(guid: int):
    """Return a bot to rule-engine mode."""
    registry = _require_registry()
    if not registry.demote(guid):
        raise HTTPException(status_code=404, detail="Bot not elevated")
    return {"status": "demoted", "guid": guid}


@router.get("/bots/{guid}/memories")
async def get_bot_memories(guid: int, query: str = "everything", limit: int = 10):
    """Search a bot's long-term memory."""
    qdrant = _require_qdrant()
    memories = await qdrant.recall(bot_guid=guid, query=query, limit=limit)
    return {
        "guid": guid,
        "count": len(memories),
        "memories": [
            {
                "id": m.id,
                "type": m.memory_type.value,
                "content": m.content,
                "importance": m.importance,
                "related_players": m.related_players,
                "created_at": m.created_at.isoformat(),
            }
            for m in memories
        ],
    }


@router.delete("/bots/{guid}/memories")
async def clear_bot_memories(guid: int):
    """Delete all memories for a bot."""
    qdrant = _require_qdrant()
    qdrant.clear_bot_memories(guid)
    return {"status": "cleared", "guid": guid}


@router.post("/bots/{guid}/personality")
async def update_personality(guid: int, req: PersonalityUpdateRequest):
    """Hot-swap a bot's personality profile and refresh the live agent."""
    registry = _require_registry()
    profile = registry.get(guid)
    if not profile:
        raise HTTPException(status_code=404, detail="Bot not elevated")
    profile.personality = req.personality
    reload_profile(req.personality)
    if _supervisor is not None:
        agent = _supervisor.get_agent(guid)
        if agent is not None:
            agent.reload_system_prompt()
    return {"status": "updated", "guid": guid, "personality": req.personality}


@router.get("/personalities")
async def get_personalities():
    """List all available personality profiles."""
    return {"profiles": list_profiles()}


@router.get("/cost")
async def get_cost():
    """Get current API cost metrics."""
    cost = _require_cost()
    return cost.get_metrics()


@router.get("/traces")
async def get_traces(
    bot_guid: int | None = None,
    limit: int = 50,
    before_id: int | None = None,
):
    """Get recent agent reasoning traces from the durable trace log."""
    if _trace_store is None:
        return {"traces": []}
    rows = await _trace_store.recent(
        bot_guid=bot_guid, limit=limit, before_id=before_id
    )
    return {"traces": [trace_row_to_dict(r) for r in rows]}


@router.post("/cost/limit")
async def set_cost_limit(req: CostLimitRequest):
    """Adjust the hourly spend cap at runtime."""
    cost = _require_cost()
    cost.set_hourly_limit(req.hourly_limit_usd)
    return {"status": "updated", "hourly_limit_usd": cost.hourly_limit}


@router.post("/bots/{guid}/say")
async def force_bot_say(guid: int, req: ForceSayRequest):
    """Inject a synthetic admin-prompt event into the bus for this bot.

    The LLM will react to ``req.text`` as if it were top-priority chat.
    """
    registry = _require_registry()
    profile = registry.get(guid)
    if not profile:
        raise HTTPException(status_code=404, detail="Bot not elevated")
    if _event_bus is None:
        raise HTTPException(status_code=503, detail="Event bus not wired")
    await _event_bus.publish(
        AdminForceSayEvent(bot_guid=guid, bot_name=profile.name, text=req.text)
    )
    return {"status": "queued", "guid": guid, "text": req.text}
