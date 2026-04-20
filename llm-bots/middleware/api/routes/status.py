"""v2 status router: aggregate AI system health for the admin dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.routes.deps import get_cost, get_registry, get_supervisor
from core.bot_registry import BotRegistry
from core.config import settings
from scheduler.cost_controller import CostController

router = APIRouter(prefix="/api/v2/status", tags=["admin-status"])


@router.get("")
async def get_status(
    registry: BotRegistry = Depends(get_registry),
    supervisor=Depends(get_supervisor),
    cost: CostController = Depends(get_cost),
) -> dict:
    cost_metrics = cost.get_metrics()
    return {
        "llm": {
            "kill_switch": settings.llm_kill_switch,
            "model_override": settings.llm_model_override,
            "model_default": settings.model_default,
            "model_important": settings.model_important,
            "provider": settings.llm_provider,
        },
        "bots": {
            "elevated": registry.count,
            "pinned": len(registry.all_pinned()),
            "auto": len(registry.all_auto_elevated()),
            "degraded": sum(
                1 for p in registry.all_elevated() if registry.is_degraded(p.guid)
            ),
            "max_agents": settings.max_active_agents,
        },
        "scheduler": {
            "auto_elevation_enabled": settings.auto_elevation_enabled,
            "tick_seconds": settings.agent_tick_seconds,
            "subscribers": supervisor.trace_subscriber_count,
        },
        "cost": cost_metrics,
    }
