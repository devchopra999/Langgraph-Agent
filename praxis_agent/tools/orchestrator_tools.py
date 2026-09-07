"""Tools for dynamically repointing service-to-service traffic via the orchestrator's routing
table, with zero downtime and no restart/rebuild involved.

This is the preferred alternative to `set_env_var`/`set_secret` + `restart_service` whenever
you just need to redirect calls a service makes (e.g. `checkout -> inventory`, or the
catch-all `* -> payments`) to a different catalog service — most commonly the mock server for
scenario-based testing, but also useful for A/B testing between two versions of a real
service (e.g. `inventory` vs `inventory-v2`). The change takes effect on the very next
request; there is no route-delete tool, so plan repointing as a value you set to whatever you
want the default to be rather than something you need to revert.
"""
from __future__ import annotations

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


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
    (`target`), instantly and with zero downtime — no restart/rebuild needed, effective on the
    very next request. The most common use is redirecting a real dependency to the mock
    server for scenario-based testing, e.g. set_orchestrator_route(environment_id,
    from_service="checkout", to_service="payments", target="mock-payments"); use
    from_service="*" to catch every caller of `to_service`. Also useful for A/B testing two
    versions of a real service (target="inventory-v2"). `target` must be one of the
    HTTP-catalogued service names — you get a VALIDATION_ERROR listing the valid names if you
    get it wrong. To point back at the real service later, just call this again with the
    original target — there is no separate revert/delete tool."""
    return await execution_client.set_orchestrator_route(environment_id, from_service, to_service, target)


@tool
@instrumented("bulk_set_orchestrator_routes")
async def bulk_set_orchestrator_routes(environment_id: str, routes: list[dict]) -> dict:
    """Set several orchestrator routes in one call — each item is
    {"from": ..., "to": ..., "target": ...} (same semantics as set_orchestrator_route). Use
    this instead of several set_orchestrator_route calls when repointing an entire scenario's
    worth of dependencies at once (e.g. multiple services -> mock server) so the change lands
    atomically. Returns {"registered": [...]} with each route resolved to its target URL."""
    return await execution_client.bulk_set_orchestrator_routes(environment_id, routes)
