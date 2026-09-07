"""Per-session event bus used to stream live progress to the SSE endpoint / TUI.

Every meaningful thing the agent does (a thought, a tool call, a skill load, a scenario
iteration, the final answer) is published here as a small structured dict. The FastAPI SSE
endpoint simply subscribes to a session's queue and forwards everything it receives.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class EventBus:
    """One instance per session. Supports multiple subscribers (e.g. TUI + logs)."""

    session_id: str
    _subscribers: list[asyncio.Queue] = field(default_factory=list)
    _history: list[dict[str, Any]] = field(default_factory=list)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for evt in self._history:
            q.put_nowait(evt)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> dict:
        event = {
            "type": event_type,
            "sessionId": self.session_id,
            "ts": time.time(),
            "payload": payload or {},
        }
        self._history.append(event)
        for q in list(self._subscribers):
            q.put_nowait(event)
        return event


class EventBusRegistry:
    """Process-wide registry of event buses keyed by session_id."""

    def __init__(self) -> None:
        self._buses: dict[str, EventBus] = {}

    def get_or_create(self, session_id: str) -> EventBus:
        if session_id not in self._buses:
            self._buses[session_id] = EventBus(session_id=session_id)
        return self._buses[session_id]

    def get(self, session_id: str) -> EventBus | None:
        return self._buses.get(session_id)


registry = EventBusRegistry()


# Event type constants — keep the vocabulary small and consistent across the graph/tools.
class EventType:
    AGENT_THOUGHT = "agent_thought"
    CASE_CLASSIFIED = "case_classified"
    HYPOTHESIS = "hypothesis"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"
    JOB_PROGRESS = "job_progress"
    SKILL_LOADED = "skill_loaded"
    SCENARIO_STARTED = "scenario_started"
    SCENARIO_COMPLETED = "scenario_completed"
    VERIFY_RESULT = "verify_result"
    ESCALATION = "escalation"
    RUN_COMPLETED = "run_completed"
    ERROR = "error"
