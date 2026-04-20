"""v2 admin settings router: model override + LLM kill switch."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from admin.settings_service import SettingsService
from api.models import KillSwitchRequest, ModelOverrideRequest
from api.routes.deps import get_settings_service
from core.config import settings

router = APIRouter(prefix="/api/v2/settings", tags=["admin-settings"])


@router.get("")
async def get_settings(
    svc: SettingsService = Depends(get_settings_service),
) -> dict:
    stored = await svc.get_all()
    return {
        "persisted": stored,
        "llm_kill_switch": settings.llm_kill_switch,
        "llm_model_override": settings.llm_model_override,
        "model_default": settings.model_default,
        "model_important": settings.model_important,
    }


@router.post("/kill-switch")
async def set_kill_switch(
    body: KillSwitchRequest,
    svc: SettingsService = Depends(get_settings_service),
) -> dict:
    await svc.set_kill_switch(body.enabled)
    return {"status": "ok", "enabled": body.enabled}


@router.post("/model-override")
async def set_model_override(
    body: ModelOverrideRequest,
    svc: SettingsService = Depends(get_settings_service),
) -> dict:
    await svc.set_model_override(body.model)
    return {"status": "ok", "model": body.model}
