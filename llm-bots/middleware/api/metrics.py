"""Prometheus metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

router = APIRouter(tags=["metrics"])

# -- Metric definitions --------------------------------------------------------

llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["bot_guid", "event_type", "model"],
)

llm_latency_seconds = Histogram(
    "llm_latency_seconds",
    "LLM call latency in seconds",
    ["model"],
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens used",
    ["direction"],  # "input" or "output"
)

active_agents_gauge = Gauge(
    "active_agents",
    "Number of currently elevated bot agents",
)

memory_operations_total = Counter(
    "memory_operations_total",
    "Total memory store/recall operations",
    ["operation"],  # "store" or "recall"
)


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus scrape endpoint."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
