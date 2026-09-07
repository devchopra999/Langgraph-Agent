"""Tools for repository-aware code Q&A and editing via aider, proxied through the
execution service (the agent never touches git/the filesystem directly)."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("code_ask")
async def code_ask(environment_id: str, service: str, prompt: str, timeout_ms: Optional[int] = None) -> dict:
    """Ask a read-only question about a service's checked-out repository (e.g. "where is the
    Axis API called and how is its response handled?"). Never modifies files — safe to call
    at any time. Requires the service to already have a repo checked out (started with a
    `branch`, or via attach_repository)."""
    return await execution_client.code_ask(environment_id, service, prompt, timeout_ms=timeout_ms)


@tool
@instrumented("code_edit")
async def code_edit(environment_id: str, service: str, prompt: str, timeout_ms: Optional[int] = None) -> dict:
    """Ask aider to make a code change in a service's repository (e.g. "add a null check
    before calling axisClient.fetch()"). Returns a diff and the list of changed files. Only
    touches the working tree — no commit is made. You must pick up the new code yourself
    afterward: for interpreted/hot-reloading services, restart_service is enough; for
    compiled-language services (Go/Java/Rust/C++/etc.) a plain restart keeps running the
    stale binary/artifact, so call rebuild_service first, then restart_service."""
    return await execution_client.code_edit(environment_id, service, prompt, timeout_ms=timeout_ms)
