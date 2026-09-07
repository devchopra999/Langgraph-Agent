"""Contextvars used to thread the current session's event bus through tool calls without
having to pass it explicitly through every LangChain @tool function signature (tool schemas
are inspected by the LLM, so keeping them free of infrastructure plumbing matters)."""
from __future__ import annotations

import contextvars

from praxis_agent.agent.events import EventBus, registry

_current_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "praxis_current_session_id", default=None
)

# The one-sentence "why am I doing this" explanation the LLM gave alongside its most recent
# tool call(s). Threaded through the same contextvars mechanism as the event bus so that the
# `instrumented` tool wrapper (in praxis_agent.tools._tool_utils) can attach it to every
# tool_call_started/completed/failed event without changing every tool's signature.
_current_action_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "praxis_current_action_reason", default=None
)


def set_current_session(session_id: str) -> None:
    _current_session_id.set(session_id)


def get_current_session_id() -> str | None:
    return _current_session_id.get()


def get_current_bus() -> EventBus | None:
    session_id = get_current_session_id()
    if not session_id:
        return None
    return registry.get_or_create(session_id)


def set_current_reason(reason: str | None) -> None:
    _current_action_reason.set(reason)


def get_current_reason() -> str | None:
    return _current_action_reason.get()
