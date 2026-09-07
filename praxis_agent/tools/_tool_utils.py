"""Shared helpers for building LangChain @tool functions that talk to the execution service
or mock server, with consistent event-bus instrumentation and error handling.
"""
from __future__ import annotations

import functools
import inspect
import json
from typing import Any, Callable

from praxis_agent.agent.context import get_current_bus, get_current_reason
from praxis_agent.agent.events import EventType

MAX_RESULT_CHARS = 8000


def _summarize(value: Any) -> str:
    # Plain strings (e.g. load_skill's raw markdown body) are passed through as-is rather
    # than JSON-encoded — json.dumps would wrap them in quotes and escape every newline,
    # turning readable prose into a mangled one-line literal for no benefit. Everything else
    # (dicts/lists from the Execution Service etc.) still gets JSON-serialized so the LLM sees
    # structured data.
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except TypeError:
            text = str(value)
    if len(text) > MAX_RESULT_CHARS:
        return text[:MAX_RESULT_CHARS] + f"... <truncated {len(text) - MAX_RESULT_CHARS} chars>"
    return text


def instrumented(tool_name: str) -> Callable:
    """Wraps an async tool implementation so every call publishes started/completed/failed
    events to the current session's event bus (a no-op if no session context is set, e.g.
    during unit tests)."""

    def decorator(fn: Callable) -> Callable:
        original_sig = inspect.signature(fn)
        has_progress_param = "on_progress" in original_sig.parameters
        # Signature exposed to LangChain's @tool (and therefore the LLM) must NOT include
        # on_progress — it's internal plumbing, not something the model should ever set.
        public_params = [p for name, p in original_sig.parameters.items() if name != "on_progress"]
        public_sig = original_sig.replace(parameters=public_params)

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            bus = get_current_bus()
            call_args = {**kwargs}
            reason = get_current_reason() or "No explicit reasoning was given for this tool call."
            if bus:
                bus.publish(EventType.TOOL_CALL_STARTED, {"tool": tool_name, "args": call_args, "reason": reason})

            def on_progress(evt: dict):
                if bus:
                    bus.publish(EventType.JOB_PROGRESS, {"tool": tool_name, **evt})

            try:
                if has_progress_param:
                    result = await fn(*args, **kwargs, on_progress=on_progress)
                else:
                    result = await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — surfaced back to the LLM as a tool result
                # Preserve the full structured payload the client attached to the exception
                # (e.g. ExecutionServiceError.code/.details — the HTTP error body, or a failed/
                # timed-out job's last known status/progress — and MockServerError.details) so
                # the agent gets the same "what went wrong" detail on failure that it already
                # gets on success, instead of just a flattened message string.
                error_payload: dict[str, Any] = {
                    "error": True,
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
                code = getattr(exc, "code", None)
                if code:
                    error_payload["code"] = code
                details = getattr(exc, "details", None)
                if details:
                    error_payload["details"] = details
                error_summary = _summarize(error_payload)
                if bus:
                    bus.publish(
                        EventType.TOOL_CALL_FAILED,
                        {"tool": tool_name, "args": call_args, "error": str(exc), "reason": reason},
                    )
                return error_summary
            if bus:
                bus.publish(
                    EventType.TOOL_CALL_COMPLETED,
                    {"tool": tool_name, "args": call_args, "result_preview": _summarize(result)[:1000], "reason": reason},
                )
            return _summarize(result)

        wrapper.__signature__ = public_sig
        return wrapper

    return decorator
