"""Runs the Praxis Lens graph for a session in the background and tracks session status,
including LangGraph's human-in-the-loop interrupt/resume flow for the escalate node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from praxis_agent.agent.context import set_current_session
from praxis_agent.agent.events import EventType, registry
from praxis_agent.agent.graph import praxis_graph

SessionStatus = Literal["running", "waiting_input", "completed", "failed"]


@dataclass
class SessionInfo:
    status: SessionStatus = "running"
    goal: str = ""
    error: str | None = None


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}

    def create(self, session_id: str, goal: str) -> SessionInfo:
        info = SessionInfo(status="running", goal=goal)
        self._sessions[session_id] = info
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)


sessions = SessionRegistry()


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


async def _is_waiting_for_input(session_id: str) -> bool:
    snapshot = await praxis_graph.aget_state(_config(session_id))
    return bool(snapshot.next) and any(getattr(t, "interrupts", None) for t in snapshot.tasks)


async def start_session(session_id: str, goal: str) -> None:
    set_current_session(session_id)
    bus = registry.get_or_create(session_id)
    info = sessions.create(session_id, goal)
    try:
        await praxis_graph.ainvoke(
            {"goal": goal, "session_id": session_id, "messages": []},
            config=_config(session_id),
        )
        info.status = "waiting_input" if await _is_waiting_for_input(session_id) else "completed"
    except Exception as exc:  # noqa: BLE001
        info.status = "failed"
        info.error = str(exc)
        bus.publish(EventType.ERROR, {"error": str(exc)})


async def send_message(session_id: str, text: str) -> None:
    set_current_session(session_id)
    bus = registry.get_or_create(session_id)
    info = sessions.get(session_id) or sessions.create(session_id, text)
    info.status = "running"
    try:
        if await _is_waiting_for_input(session_id):
            await praxis_graph.ainvoke(Command(resume=text), config=_config(session_id))
        else:
            await praxis_graph.ainvoke(
                {"messages": [HumanMessage(content=text)], "goal": text},
                config=_config(session_id),
            )
        info.status = "waiting_input" if await _is_waiting_for_input(session_id) else "completed"
    except Exception as exc:  # noqa: BLE001
        info.status = "failed"
        info.error = str(exc)
        bus.publish(EventType.ERROR, {"error": str(exc)})
