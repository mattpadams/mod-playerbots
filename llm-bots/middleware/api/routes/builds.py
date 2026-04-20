"""v2 build template CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.build_service import BuildService
from api.models import BuildTemplateWriteBody
from api.routes.deps import get_build_service
from db.models import BuildTemplate
from db.repos.build_repo import BuildTemplateWrite

router = APIRouter(prefix="/api/v2/builds", tags=["admin-builds"])


def _to_dict(row: BuildTemplate) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "class_id": row.class_id,
        "race_id": row.race_id,
        "spec_index": row.spec_index,
        "level": row.level,
        "gear_tier": row.gear_tier,
        "starting_zone": row.starting_zone,
        "personality": row.personality,
        "notes": row.notes or "",
        "updated_at": row.updated_at.isoformat(),
    }


def _from_body(body: BuildTemplateWriteBody) -> BuildTemplateWrite:
    return BuildTemplateWrite(
        name=body.name,
        class_id=body.class_id,
        race_id=body.race_id,
        spec_index=body.spec_index,
        level=body.level,
        gear_tier=body.gear_tier,
        starting_zone=body.starting_zone,
        personality=body.personality,
        notes=body.notes,
    )


@router.get("")
async def list_builds(
    svc: BuildService = Depends(get_build_service),
) -> dict:
    rows = await svc.list_all()
    return {"templates": [_to_dict(r) for r in rows]}


@router.get("/{template_id}")
async def get_build(
    template_id: int,
    svc: BuildService = Depends(get_build_service),
) -> dict:
    row = await svc.get(template_id)
    if row is None:
        raise HTTPException(404, "Build template not found")
    return _to_dict(row)


@router.post("")
async def create_build(
    body: BuildTemplateWriteBody,
    svc: BuildService = Depends(get_build_service),
) -> dict:
    try:
        row = await svc.create(_from_body(body))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _to_dict(row)


@router.put("/{template_id}")
async def update_build(
    template_id: int,
    body: BuildTemplateWriteBody,
    svc: BuildService = Depends(get_build_service),
) -> dict:
    try:
        row = await svc.update(template_id, _from_body(body))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if row is None:
        raise HTTPException(404, "Build template not found")
    return _to_dict(row)


@router.delete("/{template_id}")
async def delete_build(
    template_id: int,
    svc: BuildService = Depends(get_build_service),
) -> dict:
    ok = await svc.delete(template_id)
    if not ok:
        raise HTTPException(404, "Build template not found")
    return {"status": "deleted", "id": template_id}
