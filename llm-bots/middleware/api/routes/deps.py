"""Service registry for the v2 admin routers.

``main.py`` wires concrete services in during lifespan; routers call the
``get_*_service`` accessors in their ``Depends(...)`` declarations.
"""

from __future__ import annotations

from fastapi import HTTPException

from admin.account_service import AccountService
from admin.assignment_service import AssignmentService
from admin.bot_service import BotService
from admin.build_service import BuildService
from admin.personality_service import PersonalityService
from admin.settings_service import SettingsService
from bot_agents.agent_supervisor import AgentSupervisor
from core.bot_registry import BotRegistry
from db.repos.player_settings_repo import PlayerSettingsRepo
from scheduler.cost_controller import CostController

_settings_svc: SettingsService | None = None
_personality_svc: PersonalityService | None = None
_build_svc: BuildService | None = None
_account_svc: AccountService | None = None
_bot_svc: BotService | None = None
_assignment_svc: AssignmentService | None = None
_player_settings_repo: PlayerSettingsRepo | None = None
_registry: BotRegistry | None = None
_supervisor: AgentSupervisor | None = None
_cost: CostController | None = None


def init(
    *,
    settings_svc: SettingsService,
    personality_svc: PersonalityService,
    build_svc: BuildService,
    account_svc: AccountService,
    bot_svc: BotService,
    assignment_svc: AssignmentService,
    player_settings_repo: PlayerSettingsRepo,
    registry: BotRegistry,
    supervisor: AgentSupervisor,
    cost: CostController,
) -> None:
    global _settings_svc, _personality_svc, _build_svc
    global _account_svc, _bot_svc, _assignment_svc
    global _player_settings_repo, _registry, _supervisor, _cost
    _settings_svc = settings_svc
    _personality_svc = personality_svc
    _build_svc = build_svc
    _account_svc = account_svc
    _bot_svc = bot_svc
    _assignment_svc = assignment_svc
    _player_settings_repo = player_settings_repo
    _registry = registry
    _supervisor = supervisor
    _cost = cost


def _require(svc, name: str):
    if svc is None:
        raise HTTPException(
            status_code=503,
            detail=f"Service '{name}' not initialized",
        )
    return svc


def get_settings_service() -> SettingsService:
    return _require(_settings_svc, "settings")


def get_personality_service() -> PersonalityService:
    return _require(_personality_svc, "personality")


def get_build_service() -> BuildService:
    return _require(_build_svc, "build")


def get_account_service() -> AccountService:
    return _require(_account_svc, "account")


def get_bot_service() -> BotService:
    return _require(_bot_svc, "bot")


def get_assignment_service() -> AssignmentService:
    return _require(_assignment_svc, "assignment")


def get_player_settings_repo() -> PlayerSettingsRepo:
    return _require(_player_settings_repo, "player_settings_repo")


def get_registry() -> BotRegistry:
    return _require(_registry, "registry")


def get_supervisor() -> AgentSupervisor:
    return _require(_supervisor, "supervisor")


def get_cost() -> CostController:
    return _require(_cost, "cost")
