"""Observability dashboard — Milestone 6.

Runs as a second FastAPI app on a separate port from the main /admin
and /events API.  Shares all in-process state (supervisor, registry,
qdrant, cost_controller, event_bus) with the main app via ``init()``.
"""
