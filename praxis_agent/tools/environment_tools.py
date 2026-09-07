"""Tools for creating/inspecting/tearing down environments and controlling service lifecycle.

These map 1:1 onto the execution service's environment/service endpoints. Async job polling
(create/start/stop/restart/attach_repository) is handled transparently inside the client —
the LLM just calls the tool and gets the final ready/failed result, while granular progress
still streams to the TUI via the event bus.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("create_environment")
async def create_environment(
    services: list[str],
    repository: Optional[dict[str, str]] = None,
    on_progress=None,
) -> dict:
    """Create a new isolated Praxis Lens environment with the given catalog services
    (e.g. ["edi", "mob"]).

    Optionally pass `repository` as {"url": "https://...", "commit": "..."} when the execution
    service should clone an exact repository revision into the environment workspace. Do not add
    external mock-server names or standalone database instances here; provision only executor
    catalog services needed for the experiment.

    This call blocks internally — polling the execution service's job status on your behalf —
    until the environment is fully ready or provisioning fails, then returns the final result
    (including `environmentId` and the terminal `job` status/error). You never need to poll a
    `jobId` yourself; there is no separate poll-job tool because this one already waits.
    """
    result = await execution_client.create_environment(
        services=services,
        repository=repository,
        on_progress=on_progress,
    )
    return result


@tool
@instrumented("get_environment")
async def get_environment(environment_id: str) -> dict:
    """Get the current status of an environment and every one of its services/containers."""
    return await execution_client.get_environment(environment_id)


@tool
@instrumented("delete_environment")
async def delete_environment(environment_id: str) -> dict:
    """Tear down an environment (docker compose down -v + workspace cleanup). Idempotent."""
    return await execution_client.delete_environment(environment_id)


@tool
@instrumented("get_service_endpoints")
async def get_service_endpoints(environment_id: str) -> dict:
    """Get the mapping of service name to its internal base URL (e.g. "auth" ->
    "http://auth:4000") for every service in the environment. A service that isn't currently
    running has a `null` value. Useful for discovering how services address each other or for
    building requests that target a specific service directly."""
    return await execution_client.get_service_endpoints(environment_id)


@tool
@instrumented("start_service")
async def start_service(environment_id: str, service: str, branch: Optional[str] = None, on_progress=None) -> dict:
    """Start a service inside an existing environment. Resolves and starts its dependencies automatically. Pass `branch` to build/start from a specific checked-out
    branch of the service's repo instead of the default alpine stand-in image. Blocks until
    the service is healthy or raises on failure/timeout."""
    return await execution_client.start_service(environment_id, service, branch=branch, on_progress=on_progress)


@tool
@instrumented("stop_service")
async def stop_service(environment_id: str, service: str, on_progress=None) -> dict:
    """Stop a single service without tearing down the rest of the environment."""
    return await execution_client.stop_service(environment_id, service, on_progress=on_progress)


@tool
@instrumented("restart_service")
async def restart_service(environment_id: str, service: str, on_progress=None) -> dict:
    """Restart a single service (e.g. to pick up a new secret, config/env var, or a rebuilt
    image after a code edit). Never recreates the rest of the environment."""
    return await execution_client.restart_service(environment_id, service, on_progress=on_progress)


@tool
@instrumented("rebuild_service")
async def rebuild_service(environment_id: str, service: str, on_progress=None) -> dict:
    """Build and deploy the existing edited service workspace without checking out a branch.
    POSTs /environments/:id/services/:service/rebuild with NO body, then polls the returned
    jobId until ready. Preserves job output/progress/errors; never falls back to start_service.
    Use after code_edit and targeted tests. After readiness, inspect the retained source diff
    and replay the original workload: a ready build alone does not prove the fix."""
    return await execution_client.rebuild_service(environment_id, service, on_progress=on_progress)


# @tool
# @instrumented("attach_repository")
# async def attach_repository(environment_id: str, url: str, commit: str, on_progress=None) -> dict:
#     """Clone/checkout a specific commit (or branch name) of a repository into the environment's
#     workspace. HTTPS URLs only. Use this when you need a specific commit checked out globally
#     for the environment rather than passing `branch` to start_service."""
#     return await execution_client.attach_repository(environment_id, url, commit, on_progress=on_progress)
