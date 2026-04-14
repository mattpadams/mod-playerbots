"""Admin API endpoints for managing LLM-elevated bots."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.bot_registry import BotRegistry
from memory.qdrant_store import QdrantStore
from personality.loader import list_profiles, reload_profile
from scheduler.cost_controller import CostController

router = APIRouter(prefix="/admin", tags=["admin"])

# These will be injected at app startup via init()
_registry: BotRegistry | None = None
_qdrant: QdrantStore | None = None
_cost: CostController | None = None
_supervisor = None


def init(registry: BotRegistry, qdrant: QdrantStore, cost: CostController, supervisor) -> None:
    global _registry, _qdrant, _cost, _supervisor
    _registry = registry
    _qdrant = qdrant
    _cost = cost
    _supervisor = supervisor


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


# -- Request/Response models ---------------------------------------------------


class ElevateRequest(BaseModel):
    name: str
    personality: str = "default"


class PersonalityUpdateRequest(BaseModel):
    personality: str


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
    """Hot-swap a bot's personality profile."""
    registry = _require_registry()
    profile = registry.get(guid)
    if not profile:
        raise HTTPException(status_code=404, detail="Bot not elevated")
    profile.personality = req.personality
    reload_profile(req.personality)
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
async def get_traces(limit: int = 50):
    """Get recent agent reasoning traces."""
    if _supervisor is None:
        return {"traces": []}
    traces = _supervisor.traces[-limit:]
    return {
        "traces": [
            {
                "bot_guid": t.bot_guid,
                "bot_name": t.bot_name,
                "event_type": t.event_type,
                "model": t.model,
                "tokens_in": t.tokens_in,
                "tokens_out": t.tokens_out,
                "latency_ms": round(t.latency_ms),
                "response_preview": t.response_preview,
            }
            for t in traces
        ]
    }
