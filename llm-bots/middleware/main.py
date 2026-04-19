"""FastAPI application — the LLM bot middleware entry point.

Per-bot agent sessions are created by the supervisor as bots are
elevated; tools live on per-bot in-process MCP servers built inside
each :class:`BotAgent`.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from bot_agents.agent_supervisor import AgentSupervisor
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
from scheduler.cost_controller import CostController

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),
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

    logger.info("app.starting",
                max_agents=settings.max_active_agents,
                provider=settings.llm_provider)

    game_client = GameClient()
    soap_client = SoapClient()
    executor = CommandExecutor(game_client, soap_client)
    registry = BotRegistry()
    event_bus = EventBus()
    cost_controller = CostController()

    qdrant = QdrantStore()
    memory_manager = MemoryManager(qdrant)

    provider = get_provider()
    logger.info("app.provider_ready", provider=settings.llm_provider)

    supervisor = AgentSupervisor(
        game_client=game_client,
        registry=registry,
        event_bus=event_bus,
        executor=executor,
        memory_manager=memory_manager,
        cost_controller=cost_controller,
        provider=provider,
        tick_interval=settings.agent_tick_seconds,
    )

    admin.init(registry, qdrant, cost_controller, supervisor)
    events.init(event_bus)

    _supervisor_task = asyncio.create_task(supervisor.start())
    logger.info("app.ready")

    yield

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
