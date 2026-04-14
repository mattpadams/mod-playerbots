"""FastAPI application — the LLM bot middleware entry point.

Creates the shared tool server once at startup and passes it to the
Claude provider.  All bot agents share the same tool definitions.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from bot_agents.agent_supervisor import AgentSupervisor
from bot_agents.tool_server import ToolServer
from api import admin, events, metrics
from core.bot_registry import BotRegistry
from core.command_executor import CommandExecutor
from core.config import settings
from core.event_bus import EventBus
from core.game_client import GameClient
from core.soap_client import SoapClient
from memory.memory_manager import MemoryManager
from memory.qdrant_store import QdrantStore
from providers import get_provider
from providers.claude import ClaudeProvider
from scheduler.cost_controller import CostController

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global game_client, soap_client, executor, registry, event_bus
    global qdrant, memory_manager, cost_controller, supervisor, _supervisor_task

    logger.info(
        "app.starting",
        max_agents=settings.max_active_agents,
        provider=settings.llm_provider,
    )

    # Initialize core services
    game_client = GameClient()
    soap_client = SoapClient()
    executor = CommandExecutor(game_client, soap_client)
    registry = BotRegistry()
    event_bus = EventBus()
    cost_controller = CostController()

    # Initialize memory
    qdrant = QdrantStore()
    memory_manager = MemoryManager(qdrant)

    # Build the persistent tool server (shared across all bots)
    tool_server = ToolServer(executor=executor, memory_manager=memory_manager)
    logger.info("app.tool_server_ready", tool_count=len(tool_server.tools))

    # Initialize LLM provider and register tools
    provider = get_provider()
    if isinstance(provider, ClaudeProvider):
        provider.init_tools(tool_server.tools, tool_server.tool_names)
    logger.info("app.provider_ready", provider=settings.llm_provider)

    # Initialize supervisor
    supervisor = AgentSupervisor(
        game_client=game_client,
        registry=registry,
        event_bus=event_bus,
        memory_manager=memory_manager,
        cost_controller=cost_controller,
        provider=provider,
        tick_interval=settings.agent_tick_seconds,
    )

    # Wire up API modules
    admin.init(registry, qdrant, cost_controller, supervisor)
    events.init(event_bus)

    # Start the supervisor loop
    _supervisor_task = asyncio.create_task(supervisor.start())
    logger.info("app.ready")

    yield

    # Shutdown
    logger.info("app.shutting_down")
    await supervisor.stop()
    if _supervisor_task:
        _supervisor_task.cancel()
        try:
            await _supervisor_task
        except asyncio.CancelledError:
            pass
    await game_client.close()
    await soap_client.close()
    logger.info("app.shutdown_complete")


app = FastAPI(
    title="AzerothCore LLM Bot Middleware",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(admin.router)
app.include_router(events.router)
app.include_router(metrics.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "elevated_bots": registry.count if registry else 0,
        "cost": cost_controller.get_metrics() if cost_controller else {},
    }
