"""Shared Pydantic request models used by both /admin/* and the dashboard.

Defining these in one place prevents silent drift between the two
entry points.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ElevateRequest(BaseModel):
    name: str
    personality: str = "default"


class PersonalityUpdateRequest(BaseModel):
    personality: str


class CostLimitRequest(BaseModel):
    hourly_limit_usd: float


class ForceSayRequest(BaseModel):
    text: str


# --- v2 admin models -------------------------------------------------------


class KillSwitchRequest(BaseModel):
    enabled: bool


class ModelOverrideRequest(BaseModel):
    model: str = ""


class PersonalityTemplateWrite(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    yaml_data: str


class BuildTemplateWriteBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    class_id: int
    race_id: int
    spec_index: int = 0
    level: int = Field(1, ge=1, le=80)
    gear_tier: str = "starter"
    starting_zone: str = ""
    personality: str = "default"
    notes: str | None = None


class AccountCreateRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1)
    owner_player_guid: int | None = None
    notes: str | None = None


class BotCreateRequest(BaseModel):
    account_id: int
    account_username: str
    character_name: str = Field(..., min_length=2, max_length=12)
    class_id: int
    race_id: int
    level: int = Field(1, ge=1, le=80)
    build_template_id: int | None = None
    personality_name: str = "default"


class AssignmentCandidate(BaseModel):
    guid: int
    starting_zone: str = ""


class AssignmentPlanRequest(BaseModel):
    starting_zone: str = ""
    candidates: list[AssignmentCandidate]


class PlayerSettingsRequest(BaseModel):
    bots_enabled: bool = True
    llm_enabled: bool = True
