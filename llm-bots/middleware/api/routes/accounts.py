"""v2 managed-account CRUD router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from admin.account_service import AccountService, AccountServiceError
from api.models import AccountCreateRequest
from api.routes.deps import get_account_service
from db.models import ManagedAccount

router = APIRouter(prefix="/api/v2/accounts", tags=["admin-accounts"])


def _to_dict(row: ManagedAccount) -> dict:
    return {
        "id": row.id,
        "username": row.username,
        "owner_player_guid": row.owner_player_guid,
        "notes": row.notes or "",
        "created_at": row.created_at.isoformat(),
    }


@router.get("")
async def list_accounts(
    player_guid: int | None = None,
    svc: AccountService = Depends(get_account_service),
) -> dict:
    rows = (
        await svc.list_for_player(player_guid)
        if player_guid is not None
        else await svc.list_all()
    )
    return {"accounts": [_to_dict(r) for r in rows]}


@router.post("")
async def create_account(
    body: AccountCreateRequest,
    svc: AccountService = Depends(get_account_service),
) -> dict:
    try:
        row = await svc.create(
            username=body.username,
            password=body.password,
            owner_player_guid=body.owner_player_guid,
            notes=body.notes,
        )
    except AccountServiceError as exc:
        raise HTTPException(400, str(exc))
    return _to_dict(row)


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    svc: AccountService = Depends(get_account_service),
) -> dict:
    try:
        ok = await svc.delete(account_id)
    except AccountServiceError as exc:
        raise HTTPException(502, str(exc))
    if not ok:
        raise HTTPException(404, "Account not found")
    return {"status": "deleted", "id": account_id}
