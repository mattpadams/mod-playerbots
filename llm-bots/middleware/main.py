"""FastAPI application — the LLM bot middleware entry point.

Creates the shared tool server once at startup and passes it to the
Claude provider.  All bot agents share the same tool definitions.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI

from admin.account_service import AccountService
from admin.assignment_service import AssignmentService
from admin.bot_service import BotService
from admin.build_service import BuildService
from admin.personality_service import PersonalityService
from admin.settings_service import SettingsService
from bot_agents.agent_supervisor import AgentSupervisor
from bot_agents.tool_server import ToolServer
from api import admin as admin_api, events, metrics
from api.routes import deps as v2_deps
from api.routes.accounts import router as v2_accounts_router
from api.routes.assignments import router as v2_assignments_router
from api.routes.bots import router as v2_bots_router
from api.routes.builds import router as v2_builds_router
from api.routes.personalities import router as v2_personalities_router
from api.routes.settings import router as v2_settings_router
from api.routes.status import router as v2_status_router
from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.config import settings
from core.db_client import DbClient
from core.event_bus import EventBus
from core.game_client import GameClient
from core.soap_client import SoapClient
from core.trace_store import TraceStore
from dashboard import app as dashboard_module
from db import migrator as db_migrator
from db.engine import close_engine as close_llmbots_engine
from db.repos.account_repo import AccountRepo
from db.repos.assignment_repo import AssignmentRepo
from db.repos.bot_repo import BotRepo
from db.repos.build_repo import BuildRepo
from db.repos.personality_repo import PersonalityRepo
from db.repos.player_settings_repo import PlayerSettingsRepo
from db.repos.settings_repo import SettingsRepo
from memory.memory_manager import MemoryManager
from memory.qdrant_store import QdrantStore
from providers import get_provider
from providers.claude import ClaudeProvider
from scheduler.auto_elevator import AutoElevator
from scheduler.cost_controller import CostController
from scheduler.party_logoff_checker import PartyLogoffChecker
from scheduler.proximity_scanner import ProximityScanner

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
)

logger = structlog.get_logger()

# Shared instances — created in lifespan
game_client: GameClient
soap_client: SoapClient
executor: CommandExecutor
registry: BotRegistry
event_bus: EventBus
qdrant: QdrantStore
memory_manager: MemoryManager
cost_controller: CostController
supervisor: AgentSupervisor

_supervisor_task: asyncio.Task | None = None
_dashboard_task: asyncio.Task | None = None
_dashboard_server: uvicorn.Server | None = None
_party_logoff_checker: PartyLogoffChecker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global game_client, soap_client, executor, registry, event_bus
    global qdrant, memory_manager, cost_controller, supervisor, _supervisor_task
    global _dashboard_task, _dashboard_server, _party_logoff_checker

    logger.info(
        "app.starting",
        max_agents=settings.max_active_agents,
        provider=settings.llm_provider,
    )

    # Bootstrap the middleware-owned database and apply migrations first
    # so every downstream service can assume its schema exists.
    await db_migrator.run()

    # Initialize core services
    game_client = GameClient()
    soap_client = SoapClient()
    executor = CommandExecutor(game_client, soap_client)
    registry = BotRegistry()
    event_bus = EventBus()
    cost_controller = CostController()
    db_client = DbClient()
    proximity_scanner = ProximityScanner(db_client)
    auto_elevator = AutoElevator(registry=registry, scanner=proximity_scanner)

    # Initialize memory
    qdrant = QdrantStore()
    memory_manager = MemoryManager(qdrant)

    # Build the persistent tool server (shared across all bots)
    tool_server = ToolServer(
        executor=executor,
        memory_manager=memory_manager,
        registry=registry,
    )
    logger.info("app.tool_server_ready", tool_count=len(tool_server.tools))

    # Initialize LLM provider and register tools
    provider = get_provider()
    if isinstance(provider, ClaudeProvider):
        provider.init_tools(tool_server.tools, tool_server.tool_names)
    logger.info("app.provider_ready", provider=settings.llm_provider)

    # Durable trace log for the observability dashboard (Milestone 6)
    trace_store = TraceStore(path=settings.trace_db_path)

    # Initialize supervisor (pass executor so the party coordinator can
    # dispatch pass-roll / auto-vendor commands without the LLM)
    supervisor = AgentSupervisor(
        game_client=game_client,
        registry=registry,
        event_bus=event_bus,
        memory_manager=memory_manager,
        cost_controller=cost_controller,
        provider=provider,
        tick_interval=settings.agent_tick_seconds,
        trace_store=trace_store,
        command_executor=executor,
        auto_elevator=auto_elevator,
    )

    # Wire up API modules
    admin_api.init(
        registry,
        qdrant,
        cost_controller,
        supervisor,
        event_bus=event_bus,
        trace_store=trace_store,
    )
    events.init(event_bus, party=supervisor.party_coordinator)
    dashboard_module.init(
        registry_=registry,
        qdrant_=qdrant,
        cost_=cost_controller,
        supervisor_=supervisor,
        event_bus_=event_bus,
        trace_store_=trace_store,
    )

    # v2 admin API: instantiate repos + services, hydrate DB-backed
    # runtime settings, and register the routers with the FastAPI app.
    settings_repo = SettingsRepo()
    personality_repo = PersonalityRepo()
    build_repo = BuildRepo()
    account_repo = AccountRepo()
    bot_repo = BotRepo()
    assignment_repo = AssignmentRepo()
    player_settings_repo = PlayerSettingsRepo()

    settings_svc = SettingsService(settings_repo)
    personality_svc = PersonalityService(personality_repo)
    build_svc = BuildService(build_repo)
    account_svc = AccountService(
        account_repo, soap_client, bot_repo=bot_repo, registry=registry
    )
    bot_svc = BotService(
        bot_repo,
        soap_client,
        registry=registry,
        db_client=db_client,
        supervisor=supervisor,
    )
    assignment_svc = AssignmentService(assignment_repo)

    await settings_svc.hydrate()
    await personality_svc.hydrate()

    v2_deps.init(
        settings_svc=settings_svc,
        personality_svc=personality_svc,
        build_svc=build_svc,
        account_svc=account_svc,
        bot_svc=bot_svc,
        assignment_svc=assignment_svc,
        player_settings_repo=player_settings_repo,
        registry=registry,
        supervisor=supervisor,
        cost=cost_controller,
    )

    # Party logoff checker — enforces the "main party + capped-avg" rule
    # every tick of its own cadence (separate from the supervisor loop so
    # offline players don't starve the scheduler).
    _party_logoff_checker = PartyLogoffChecker(
        assignment_repo=assignment_repo,
        player_settings_repo=player_settings_repo,
        bot_repo=bot_repo,
        db_client=db_client,
        soap=soap_client,
    )
    await _party_logoff_checker.start()

    # Start the proximity scanner before the supervisor so the very
    # first tick has fresh-ish data.
    await proximity_scanner.start()

    # Start the supervisor loop
    _supervisor_task = asyncio.create_task(supervisor.start())

    # Start the dashboard on a separate port (same process — shared state)
    dashboard_config = uvicorn.Config(
        dashboard_module.app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
        access_log=False,
    )
    _dashboard_server = uvicorn.Server(dashboard_config)
    _dashboard_task = asyncio.create_task(_dashboard_server.serve())
    logger.info(
        "app.dashboard_ready",
        url=f"http://{settings.dashboard_host}:{settings.dashboard_port}/",
    )

    logger.info("app.ready")

    yield

    # Shutdown
    logger.info("app.shutting_down")
    if _party_logoff_checker is not None:
        await _party_logoff_checker.stop()
    await proximity_scanner.stop()
    await supervisor.stop()
    if _dashboard_server is not None:
        _dashboard_server.should_exit = True
        try:
            # Gracefully close open connections (SSE clients etc.)
            await asyncio.wait_for(_dashboard_server.shutdown(), timeout=5.0)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            pass
    if _dashboard_task:
        try:
            await asyncio.wait_for(_dashboard_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _dashboard_task.cancel()
    if _supervisor_task:
        _supervisor_task.cancel()
        try:
            await _supervisor_task
        except asyncio.CancelledError:
            pass
    await game_client.close()
    await soap_client.close()
    await db_client.close()
    await close_llmbots_engine()
    logger.info("app.shutdown_complete")


app = FastAPI(
    title="AzerothCore LLM Bot Middleware",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(admin_api.router)
app.include_router(events.router)
app.include_router(metrics.router)

# v2 admin API
app.include_router(v2_settings_router)
app.include_router(v2_status_router)
app.include_router(v2_personalities_router)
app.include_router(v2_builds_router)
app.include_router(v2_accounts_router)
app.include_router(v2_bots_router)
app.include_router(v2_assignments_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "elevated_bots": registry.count if registry else 0,
        "cost": cost_controller.get_metrics() if cost_controller else {},
    }
