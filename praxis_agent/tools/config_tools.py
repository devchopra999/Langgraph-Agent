"""Tools for reading and mutating a running environment's per-service configuration.

The executor supports reading and merging a service's complete env file, plus a single-key
`/config` compatibility endpoint. Changes take effect after the service is restarted.
"""
from __future__ import annotations

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("get_service_env")
async def get_service_env(environment_id: str, service: str) -> dict:
    """Get the full per-service env file currently configured for a service. Inspect this
    before changing an integration URL or feature flag so existing values are preserved."""
    return await execution_client.get_service_env(environment_id, service)


@tool
@instrumented("update_service_env")
async def update_service_env(environment_id: str, service: str, env: dict[str, str]) -> dict:
    """Merge one or more values into a service's env file, preserving unspecified keys.
    Use this to point a service at an external mock-server URL or change multiple related
    settings. Restart the service afterward for the changes to take effect."""
    return await execution_client.update_service_env(environment_id, service, env)


@tool
@instrumented("set_env_var")
async def set_env_var(environment_id: str, service: str, key: str, value: str) -> dict:
    """Set a per-environment config/env var for a service (e.g. redirecting a service's
    AXIS_URL env var to an external Mock Server, or toggling LOG_LEVEL=debug). Takes effect on the
    service's next restart — call restart_service afterward."""
    return await execution_client.set_env_var(environment_id, service, key, value)
