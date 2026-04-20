"""FastAPI sub-app hosting the observability dashboard UI + JSON API."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.routes.accounts import router as v2_accounts_router
from api.routes.assignments import router as v2_assignments_router
from api.routes.bots import router as v2_bots_router
from api.routes.builds import router as v2_builds_router
from api.routes.personalities import router as v2_personalities_router
from api.routes.settings import router as v2_settings_router
from api.routes.status import router as v2_status_router
from core.bot_registry import BotRegistry
from core.event_bus import EventBus
from core.trace_store import TraceStore
from memory.qdrant_store import QdrantStore
from scheduler.cost_controller import CostController

_BASE_DIR = Path(__file__).resolve().parent

# Module-level shared state — populated by init() during main lifespan
registry: BotRegistry | None = None
qdrant: QdrantStore | None = None
cost: CostController | None = None
supervisor = None
event_bus: EventBus | None = None
trace_store: TraceStore | None = None


def init(
    *,
    registry_: BotRegistry,
    qdrant_: QdrantStore,
    cost_: CostController,
    supervisor_,
    event_bus_: EventBus,
    trace_store_: TraceStore,
) -> None:
    global registry, qdrant, cost, supervisor, event_bus, trace_store
    registry = registry_
    qdrant = qdrant_
    cost = cost_
    supervisor = supervisor_
    event_bus = event_bus_
    trace_store = trace_store_


templates = Jinja2Templates(directory=_BASE_DIR / "templates")

app = FastAPI(title="AzerothCore LLM Bot Dashboard", version="0.1.0")
app.mount(
    "/static",
    StaticFiles(directory=_BASE_DIR / "static"),
    name="static",
)

# v2 admin API — mounted on the dashboard too so the HTMX admin page
# reaches the same routes without a cross-origin hop. deps.init() still
# wires services once from main.py; both apps share the same registry.
app.include_router(v2_settings_router)
app.include_router(v2_status_router)
app.include_router(v2_personalities_router)
app.include_router(v2_builds_router)
app.include_router(v2_accounts_router)
app.include_router(v2_bots_router)
app.include_router(v2_assignments_router)

# Register routes at import time (routes module reads shared globals lazily)
from dashboard import routes  # noqa: E402,F401 — side-effect import
from dashboard import admin_routes  # noqa: E402,F401 — side-effect import
