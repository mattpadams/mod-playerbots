"""v2 player-to-bot assignment + per-player settings router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.assignment_service import (
    AssignmentService,
    CandidateBot,
    TOTAL_BOTS_PER_PLAYER,
)
from api.models import AssignmentPlanRequest, PlayerSettingsRequest
from api.routes.deps import (
    get_assignment_service,
    get_player_settings_repo,
)
from db.engine import session_factory
from db.repos.player_settings_repo import PlayerSettingsRepo

router = APIRouter(prefix="/api/v2/players", tags=["admin-players"])


def _assignment_to_dict(a) -> dict:
    return {
        "bot_guid": a.bot_guid,
        "party_slot": a.party_slot,
        "slot_position": a.slot_position,
        "assigned_at": a.assigned_at.isoformat(),
    }


@router.get("/{player_guid}/assignments")
async def list_assignments(
    player_guid: int,
    svc: AssignmentService = Depends(get_assignment_service),
) -> dict:
    rows = await svc.list_for_player(player_guid)
    return {
        "player_guid": player_guid,
        "assignments": [_assignment_to_dict(r) for r in rows],
    }


@router.post("/{player_guid}/assignments")
async def plan_assignments(
    player_guid: int,
    body: AssignmentPlanRequest,
    svc: AssignmentService = Depends(get_assignment_service),
) -> dict:
    if len(body.candidates) > TOTAL_BOTS_PER_PLAYER:
        raise HTTPException(
            400,
            f"Too many candidates (max {TOTAL_BOTS_PER_PLAYER})",
        )
    plan = svc.plan(
        player_guid=player_guid,
        player_starting_zone=body.starting_zone,
        candidates=[
            CandidateBot(guid=c.guid, starting_zone=c.starting_zone)
            for c in body.candidates
        ],
    )
    n = await svc.replace_for_player(player_guid, plan)
    return {
        "player_guid": player_guid,
        "assigned": n,
        "target": TOTAL_BOTS_PER_PLAYER,
    }


@router.delete("/{player_guid}/assignments")
async def clear_assignments(
    player_guid: int,
    svc: AssignmentService = Depends(get_assignment_service),
) -> dict:
    n = await svc.clear(player_guid)
    return {"player_guid": player_guid, "removed": n}


@router.delete("/{player_guid}/assignments/{bot_guid}")
async def unassign_one(
    player_guid: int,
    bot_guid: int,
    svc: AssignmentService = Depends(get_assignment_service),
) -> dict:
    ok = await svc.unassign_one(player_guid, bot_guid)
    if not ok:
        raise HTTPException(404, "Assignment not found")
    return {
        "status": "removed",
        "player_guid": player_guid,
        "bot_guid": bot_guid,
    }


@router.get("/{player_guid}/settings")
async def get_player_settings(
    player_guid: int,
    repo: PlayerSettingsRepo = Depends(get_player_settings_repo),
) -> dict:
    async with session_factory()() as session:
        row = await repo.get(session, player_guid)
    if row is None:
        return {
            "player_guid": player_guid,
            "bots_enabled": True,
            "llm_enabled": True,
            "exists": False,
        }
    return {
        "player_guid": player_guid,
        "bots_enabled": row.bots_enabled,
        "llm_enabled": row.llm_enabled,
        "updated_at": row.updated_at.isoformat(),
        "exists": True,
    }


@router.put("/{player_guid}/settings")
async def set_player_settings(
    player_guid: int,
    body: PlayerSettingsRequest,
    repo: PlayerSettingsRepo = Depends(get_player_settings_repo),
) -> dict:
    async with session_factory()() as session:
        row = await repo.upsert(
            session,
            player_guid=player_guid,
            bots_enabled=body.bots_enabled,
            llm_enabled=body.llm_enabled,
        )
    return {
        "player_guid": row.player_guid,
        "bots_enabled": row.bots_enabled,
        "llm_enabled": row.llm_enabled,
    }
