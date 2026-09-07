"""Tools for inspecting and repointing traffic via the executor environment's orchestrator.

Routes only affect traffic that reaches the orchestrator. Discover caller HTTP configuration
and routing headers with code_ask; direct external calls may require a hostname alias/header
injector or supported base-URL configuration. HTTP aliases do not intercept HTTPS.
The symbolic `mock-server` target resolves to the GLOBAL server configured by MOCK_SERVER_URL;
never provision it. Read targets may be resolved URLs, while writes require symbolic names.
"""
from __future__ import annotations

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("get_orchestrator_status")
async def get_orchestrator_status(environment_id: str) -> dict:
    """Get this environment's orchestrator health plus its internal, host, and dashboard URLs.
    Reachability alone does not prove the caller uses it; inspect caller configuration and
    verify actual traffic before claiming a route intercepted a dependency."""
    return await execution_client.get_orchestrator_status(environment_id)


@tool
@instrumented("list_orchestrator_routes")
async def list_orchestrator_routes(environment_id: str) -> list[dict]:
    """List every currently-registered orchestrator route for this environment, each as
    {"sourceService": ..., "destinationService": ..., "pointsTo": ..., "updatedAt": ...}.
    `sourceService="*"` is a wildcard matching any caller. Read `pointsTo` values may be
    resolved URLs: do not blindly submit them as symbolic write values.
    Absence of an exact route does not establish absence of a wildcard/default fallback, or
    whether a caller sends traffic through the orchestrator at all."""
    return await execution_client.list_orchestrator_routes(environment_id)


@tool
@instrumented("get_orchestrator_route")
async def get_orchestrator_route(environment_id: str, source_service: str, destination_service: str) -> dict:
    """Get the single route currently registered for calls from `source_service` to
    `destination_service` (use source_service="*" for the wildcard). Only the executor's explicit
    ORCHESTRATOR_ROUTE_NOT_FOUND becomes {"found": false, "route": null}; unrelated errors
    remain errors. This is an exact lookup, not wildcard/default resolution. Record absence
    before adding an override so cleanup can delete it rather than create a new route."""
    return await execution_client.get_orchestrator_route(environment_id, source_service, destination_service)


@tool
@instrumented("set_orchestrator_route")
async def set_orchestrator_route(
    environment_id: str, source_service: str, destination_service: str, points_to: str
) -> dict:
    """Repoint calls from `source_service` to `destination_service` so they point to `points_to`,
    instantly and with zero downtime — no restart needed, effective on the very next request.
    ALWAYS call list_orchestrator_routes or get_orchestrator_route for this exact pair FIRST,
    for ANY routing change (not just mock testing) — you need the current/original `pointsTo`
    value on record before overwriting it, whether or not one is currently set. Use
    source_service="*" to catch every caller of `destination_service`, otherwise use the exact
    caller to preserve isolation.
    This supports in-environment redirection, A/B experiments, and routing a proxied external
    dependency to the Mock Server. Inspect the current route first and restore its original
    symbolic `pointsTo` value after the experiment, or delete an override that was previously
    absent. A read may return a resolved URL: discover its symbolic mapping before restoring it.
    `points_to` is always either the exact name of another catalog
    service (as provisioned in this environment) or the literal string "mock-server" — never a
    URL, version tag, or environment id. mock-server is the GLOBAL managed server, not an
    environment service. This only redirects already-proxied traffic; configure HTTP aliases
    or supported caller routing first when needed."""
    return await execution_client.set_orchestrator_route(environment_id, source_service, destination_service, points_to)


@tool
@instrumented("bulk_set_orchestrator_routes")
async def bulk_set_orchestrator_routes(environment_id: str, routes: list[dict]) -> dict:
    """Set several orchestrator routes in one call — each item is
    {"sourceService": ..., "destinationService": ..., "pointsTo": ...} (same semantics as
    set_orchestrator_route: `pointsTo` is always the exact name of another catalog service or
    the literal string "mock-server").
    ALWAYS call list_orchestrator_routes FIRST to record every affected pair's current `pointsTo`
    value before overwriting it, exactly as required for set_orchestrator_route.
    Use this instead of several set_orchestrator_route calls when repointing an entire scenario's
    worth of in-environment dependencies at once. Returns
    {"registered": [{"sourceService": ..., "destinationService": ..., "pointsTo": ...,
    "updatedAt": ...}, ...], "errors": [...]}."""
    return await execution_client.bulk_set_orchestrator_routes(environment_id, routes)


@tool
@instrumented("delete_orchestrator_route")
async def delete_orchestrator_route(environment_id: str, source_service: str, destination_service: str) -> dict:
    """Delete exactly one caller/destination override. Use to restore prior exact absence
    after a temporary owned experiment. Wildcard/default routes may still apply; this does
    not disable all traffic. Do not remove another experiment's route."""
    return await execution_client.delete_orchestrator_route(environment_id, source_service, destination_service)


@tool
@instrumented("update_orchestrator_aliases")
async def update_orchestrator_aliases(environment_id: str, aliases: dict[str, str]) -> dict:
    """Merge hostname-to-logical-destination mappings into the HTTP header injector, e.g.
    {"api.nexpay.example.com": "nexpay"}. The executor recreates the sidecar and DNS aliases;
    the injector stamps x-to-service and derives x-from-service from caller source IP.
    Configure the corresponding exact caller route with symbolic target mock-server to reach
    the GLOBAL managed mock. Not TLS interception: discover supported caller configuration and
    switch https:// to http:// plus restart if needed. Preserve unrelated mappings and restore
    prior owned values or delete newly introduced aliases after testing. Verify a real wrapper
    call reaches the intended mock; registering an alias alone is not traffic evidence."""
    return await execution_client.update_orchestrator_aliases(environment_id, aliases)


@tool
@instrumented("delete_orchestrator_alias")
async def delete_orchestrator_alias(environment_id: str, host: str) -> dict:
    """Stop intercepting one HTTP hostname (no scheme/path). Use only to remove an owned alias
    that was absent before the experiment; restore prior mappings with update_orchestrator_aliases
    instead. Other aliases and routes remain unchanged."""
    return await execution_client.delete_orchestrator_alias(environment_id, host)
