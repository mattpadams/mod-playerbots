"""v2 managed-bot CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.bot_service import BotService, BotServiceError
from api.models import BotCreateRequest, PersonalityUpdateRequest
from api.routes.deps import get_bot_service
from db.models import ManagedBot

router = APIRouter(prefix="/api/v2/bots", tags=["admin-bots"])


def _to_dict(row: ManagedBot) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "character_guid": row.character_guid,
        "character_name": row.character_name,
        "class_id": row.class_id,
        "race_id": row.race_id,
        "level": row.level,
        "build_template_id": row.build_template_id,
        "personality_name": row.personality_name,
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
async def list_bots(
    account_id: int | None = None,
    svc: BotService = Depends(get_bot_service),
) -> dict:
    rows = (
        await svc.list_for_account(account_id)
        if account_id is not None
        else await svc.list_all()
    )
    return {"bots": [_to_dict(r) for r in rows]}


@router.post("")
async def create_bot(
    body: BotCreateRequest,
    svc: BotService = Depends(get_bot_service),
) -> dict:
    try:
        row = await svc.create(
            account_username=body.account_username,
            account_id=body.account_id,
            character_name=body.character_name,
            class_id=body.class_id,
            race_id=body.race_id,
            level=body.level,
            build_template_id=body.build_template_id,
            personality_name=body.personality_name,
        )
    except BotServiceError as exc:
        raise HTTPException(400, str(exc))
    return _to_dict(row)


@router.patch("/{character_guid}/personality")
async def set_bot_personality(
    character_guid: int,
    body: PersonalityUpdateRequest,
    svc: BotService = Depends(get_bot_service),
) -> dict:
    ok = await svc.set_personality(character_guid, body.personality)
    if not ok:
        raise HTTPException(404, "Bot not found")
    return {
        "status": "updated",
        "character_guid": character_guid,
        "personality": body.personality,
    }


@router.delete("/{character_guid}")
async def delete_bot(
    character_guid: int,
    svc: BotService = Depends(get_bot_service),
) -> dict:
    ok = await svc.delete(character_guid)
    if not ok:
        raise HTTPException(404, "Bot not found")
    return {"status": "deleted", "character_guid": character_guid}
