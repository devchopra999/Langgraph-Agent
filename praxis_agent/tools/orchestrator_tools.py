"""Tools for inspecting and repointing traffic via the executor environment's orchestrator.

Routes identify in-environment callers/destinations. Their targets can be another environment
service or the executor's registered `mock-server` target, even though that Mock Server is managed
externally through its own tools. Route changes take effect on the next proxied request.
"""
from __future__ import annotations

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("get_orchestrator_status")
async def get_orchestrator_status(environment_id: str) -> dict:
    """Get this environment's orchestrator health plus its internal, host, and dashboard URLs.
    Use this during discovery before inspecting or changing in-environment routes."""
    return await execution_client.get_orchestrator_status(environment_id)


@tool
@instrumented("list_orchestrator_routes")
async def list_orchestrator_routes(environment_id: str) -> list[dict]:
    """List every currently-registered orchestrator route for this environment, each as
    {"from": ..., "to": ..., "target": <resolved docker-network URL>}. `from="*"` is a
    catch-all matching any caller. Use this to see current traffic pointings before deciding
    what to change."""
    return await execution_client.list_orchestrator_routes(environment_id)


@tool
@instrumented("get_orchestrator_route")
async def get_orchestrator_route(environment_id: str, from_service: str, to_service: str) -> dict:
    """Get the single route currently registered for calls from `from_service` to
    `to_service` (use from_service="*" for the catch-all). Returns a 404-shaped error with a
    hint if no route is registered for that pair yet — meaning calls still go to `to_service`'s
    default target."""
    return await execution_client.get_orchestrator_route(environment_id, from_service, to_service)


@tool
@instrumented("set_orchestrator_route")
async def set_orchestrator_route(environment_id: str, from_service: str, to_service: str, target: str) -> dict:
    """Repoint calls from `from_service` to `to_service` at a different catalog service
    (`target`), instantly and with zero downtime — no restart needed, effective on the very next
    request. Use from_service="*" to catch every caller of `to_service`, otherwise use the exact
    caller to preserve isolation. This supports in-environment redirection, A/B experiments, and
    routing a proxied external dependency to `target="mock-server"`. Inspect the current route
    first and restore its original target after the experiment. `target` must be a valid executor
    route target."""
    return await execution_client.set_orchestrator_route(environment_id, from_service, to_service, target)


@tool
@instrumented("bulk_set_orchestrator_routes")
async def bulk_set_orchestrator_routes(environment_id: str, routes: list[dict]) -> dict:
    """Set several orchestrator routes in one call — each item is
    {"from": ..., "to": ..., "target": ...} (same semantics as set_orchestrator_route). Use
    this instead of several set_orchestrator_route calls when repointing an entire scenario's
    worth of in-environment dependencies at once so the change lands atomically. Returns
    {"registered": [...]} with each route resolved to its target URL."""
    return await execution_client.bulk_set_orchestrator_routes(environment_id, routes)
