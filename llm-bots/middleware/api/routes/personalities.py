"""v2 personality template CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.personality_service import PersonalityService
from api.models import PersonalityTemplateWrite
from api.routes.deps import get_personality_service

router = APIRouter(
    prefix="/api/v2/personalities", tags=["admin-personalities"]
)


@router.get("")
async def list_personalities(
    svc: PersonalityService = Depends(get_personality_service),
) -> dict:
    return await svc.list_all()


@router.get("/{name}")
async def get_personality(
    name: str,
    svc: PersonalityService = Depends(get_personality_service),
) -> dict:
    row = await svc.get(name)
    if row is None:
        raise HTTPException(404, f"No DB personality '{name}'")
    return {
        "name": row.name,
        "yaml_data": row.yaml_data,
        "updated_at": row.updated_at.isoformat(),
    }


@router.post("")
async def upsert_personality(
    body: PersonalityTemplateWrite,
    svc: PersonalityService = Depends(get_personality_service),
) -> dict:
    try:
        row = await svc.upsert(body.name, body.yaml_data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {
        "status": "ok",
        "name": row.name,
        "updated_at": row.updated_at.isoformat(),
    }


@router.delete("/{name}")
async def delete_personality(
    name: str,
    svc: PersonalityService = Depends(get_personality_service),
) -> dict:
    ok = await svc.delete(name)
    if not ok:
        raise HTTPException(404, f"No DB personality '{name}'")
    return {"status": "deleted", "name": name}
