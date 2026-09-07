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
    branches: Optional[dict[str, str]] = None,
    on_progress=None,
) -> dict:
    """Create a new isolated Praxis Lens environment with the given catalog services
    (e.g. ["edi", "mob"]).

    Always restores databases from the "baseline" snapshot. Optionally pass `branches` as a
    mapping of service name to branch (e.g. {"mob": "feature/my-fix"}) to have the execution
    service check out that branch for the given service(s) during environment creation.

    This call blocks internally — polling the execution service's job status on your behalf —
    until the environment is fully ready or provisioning fails, then returns the final result
    (including `environmentId` and the terminal `job` status/error). You never need to poll a
    `jobId` yourself; there is no separate poll-job tool because this one already waits.
    """
    result = await execution_client.create_environment(
        services=services,
        branches=branches,
        database_snapshot="baseline",
        repository=None,
        databases=None,
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
    """Rebuild a service's image from its current working tree (e.g. after code_edit changed
    source in a compiled language like Go/Java/Rust/C++, where an interpreter-less restart
    would keep running the stale binary). Blocks until the rebuild job completes, then you
    still need to call restart_service (or start_service) to actually run the new image —
    rebuild only recompiles/rebuilds, it does not restart the running container."""
    return await execution_client.rebuild_service(environment_id, service, on_progress=on_progress)


# @tool
# @instrumented("attach_repository")
# async def attach_repository(environment_id: str, url: str, commit: str, on_progress=None) -> dict:
#     """Clone/checkout a specific commit (or branch name) of a repository into the environment's
#     workspace. HTTPS URLs only. Use this when you need a specific commit checked out globally
#     for the environment rather than passing `branch` to start_service."""
#     return await execution_client.attach_repository(environment_id, url, commit, on_progress=on_progress)
