"""Dashboard HTML routes for the v2 admin page.

The JSON work happens in ``api/routes/*.py``; this module only builds
Jinja contexts for the ``/admin`` page and its HTMX fragments. It reads
the same services via ``api.routes.deps`` so there is exactly one wiring
point.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Query, Request
from fastapi.responses import HTMLResponse

import dashboard.app as appmod
from api.routes import deps as v2_deps
from core.config import settings
from db.engine import session_factory
from personality.loader import list_profiles

logger = structlog.get_logger()

app = appmod.app
templates = appmod.templates


# -- Pages --------------------------------------------------------------------


@app.get("/admin", response_class=HTMLResponse)
async def page_admin(request: Request):
    return templates.TemplateResponse(
        request,
        "admin.html",
        {},
    )


# -- Fragments ----------------------------------------------------------------


def _llm_context() -> dict:
    return {
        "kill_switch": settings.llm_kill_switch,
        "model_override": settings.llm_model_override,
        "model_default": settings.model_default,
        "model_important": settings.model_important,
    }


@app.get("/fragments/admin/settings", response_class=HTMLResponse)
async def frag_admin_settings(request: Request):
    return templates.TemplateResponse(
        request,
        "partials/admin_settings.html",
        {"llm": _llm_context()},
    )


@app.get("/fragments/admin/status", response_class=HTMLResponse)
async def frag_admin_status(request: Request):
    registry = appmod.registry
    cost = appmod.cost
    supervisor = appmod.supervisor
    status: dict = {
        "llm": _llm_context() | {"provider": settings.llm_provider},
        "bots": {
            "elevated": registry.count if registry else 0,
            "pinned": len(registry.all_pinned()) if registry else 0,
            "auto": len(registry.all_auto_elevated()) if registry else 0,
            "degraded": (
                sum(
                    1
                    for p in registry.all_elevated()
                    if registry.is_degraded(p.guid)
                )
                if registry
                else 0
            ),
            "max_agents": settings.max_active_agents,
        },
        "scheduler": {
            "auto_elevation_enabled": settings.auto_elevation_enabled,
            "tick_seconds": settings.agent_tick_seconds,
            "subscribers": supervisor.trace_subscriber_count if supervisor else 0,
        },
        "cost": cost.get_metrics() if cost else {},
    }
    return templates.TemplateResponse(
        request, "partials/admin_status.html", {"status": status}
    )


@app.get("/fragments/admin/accounts", response_class=HTMLResponse)
async def frag_admin_accounts(request: Request):
    svc = v2_deps.get_account_service()
    rows = await svc.list_all()
    accounts = [
        {
            "id": r.id,
            "username": r.username,
            "owner_player_guid": r.owner_player_guid,
            "notes": r.notes or "",
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request, "partials/admin_accounts.html", {"accounts": accounts}
    )


@app.get("/fragments/admin/bots", response_class=HTMLResponse)
async def frag_admin_bots(request: Request):
    svc = v2_deps.get_bot_service()
    rows = await svc.list_all()
    bots = [
        {
            "character_guid": r.character_guid,
            "character_name": r.character_name,
            "account_id": r.account_id,
            "class_id": r.class_id,
            "race_id": r.race_id,
            "level": r.level,
            "personality_name": r.personality_name,
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request,
        "partials/admin_bots.html",
        {"bots": bots, "personalities": list_profiles()},
    )


@app.get("/fragments/admin/builds", response_class=HTMLResponse)
async def frag_admin_builds(request: Request):
    svc = v2_deps.get_build_service()
    rows = await svc.list_all()
    tpls = [
        {
            "id": r.id,
            "name": r.name,
            "class_id": r.class_id,
            "race_id": r.race_id,
            "spec_index": r.spec_index,
            "level": r.level,
            "gear_tier": r.gear_tier,
            "starting_zone": r.starting_zone,
            "personality": r.personality,
        }
        for r in rows
    ]
    return templates.TemplateResponse(
        request, "partials/admin_builds.html", {"templates": tpls}
    )


@app.get("/fragments/admin/personalities", response_class=HTMLResponse)
async def frag_admin_personalities(request: Request):
    svc = v2_deps.get_personality_service()
    names = await svc.list_all()
    db_names = names.get("db", [])
    yaml_only = sorted(set(names.get("yaml", [])) - set(db_names))
    return templates.TemplateResponse(
        request,
        "partials/admin_personalities.html",
        {"db_names": db_names, "yaml_only": yaml_only},
    )


@app.get("/fragments/admin/assignments", response_class=HTMLResponse)
async def frag_admin_assignments(
    request: Request,
    player_guid: int | None = Query(default=None),
):
    if player_guid is None:
        return templates.TemplateResponse(
            request,
            "partials/admin_assignments.html",
            {
                "player_guid": None,
                "assignments": [],
                "player_settings": None,
            },
        )
    asvc = v2_deps.get_assignment_service()
    rows = await asvc.list_for_player(player_guid)
    assignments = [
        {
            "bot_guid": r.bot_guid,
            "party_slot": r.party_slot,
            "slot_position": r.slot_position,
        }
        for r in rows
    ]
    ps_repo = v2_deps.get_player_settings_repo()
    async with session_factory()() as session:
        ps = await ps_repo.get(session, player_guid)
    player_settings = (
        {"bots_enabled": ps.bots_enabled, "llm_enabled": ps.llm_enabled}
        if ps is not None
        else {"bots_enabled": True, "llm_enabled": True}
    )
    return templates.TemplateResponse(
        request,
        "partials/admin_assignments.html",
        {
            "player_guid": player_guid,
            "assignments": assignments,
            "player_settings": player_settings,
        },
    )
