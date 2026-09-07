"""Tools for inspecting and repointing in-environment service traffic via the orchestrator.

Routes apply only to services inside the executor environment. The external Mock Server is not
an orchestrator target; point services at it through their documented env/config setting and
restart them instead. Route changes take effect on the next proxied request.
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
    request. Use from_service="*" to catch every caller of `to_service`. This is appropriate for
    in-environment service redirection or A/B experiments; use service env/config for an
    external dependency such as the Mock Server. `target` must be a valid HTTP-catalogued
    service name. To point back at the real service later, call this again with the original
    target — there is no separate revert/delete tool."""
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
