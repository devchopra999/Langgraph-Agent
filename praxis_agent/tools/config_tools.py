"""Tools for mutating a running environment's configuration: Vault secrets and per-service
config/env vars.

Note: the execution service does not (yet) expose a dedicated "set env var" endpoint. Per
the project owner, the existing `/config` endpoint already writes a per-service env file
that's sourced on the next restart — so `set_env_var` below is implemented as a thin,
clearly-named alias over `set_config` rather than inventing a new HTTP call.
"""
from __future__ import annotations

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("set_secret")
async def set_secret(environment_id: str, service: str, path: str, key: str, value: str) -> dict:
    """Write a Vault secret for this environment only (e.g. path="secret/edi/axis", key="url",
    value="http://mock-server:3000" to redirect a service's outbound dependency to the mock
    server). Existing keys at the same path are preserved. Restart the service afterward for
    it to pick up the new secret."""
    return await execution_client.set_secret(environment_id, service, path, key, value)


@tool
@instrumented("set_env_var")
async def set_env_var(environment_id: str, service: str, key: str, value: str) -> dict:
    """Set a per-environment config/env var for a service (e.g. redirecting a service's
    AXIS_URL env var to the mock server, or toggling LOG_LEVEL=debug). Takes effect on the
    service's next restart — call restart_service afterward."""
    return await execution_client.set_env_var(environment_id, service, key, value)
