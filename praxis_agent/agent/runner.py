"""Runs the Praxis Lens graph for a session in the background and tracks session status,
including LangGraph's human-in-the-loop interrupt/resume flow for the escalate node.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from praxis_agent.agent.context import set_current_session
from praxis_agent.agent.events import EventType, registry
from praxis_agent.agent.graph import praxis_graph
from praxis_agent.agent.reports import ReportArtifacts, write_report

SessionStatus = Literal["running", "stopping", "waiting_input", "completed", "stopped", "failed"]


@dataclass
class SessionInfo:
    status: SessionStatus = "running"
    goal: str = ""
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    task: asyncio.Task | None = None
    report: ReportArtifacts | None = None
    report_finalized: bool = False


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}

    def create(self, session_id: str, goal: str) -> SessionInfo:
        info = SessionInfo(status="running", goal=goal)
        self._sessions[session_id] = info
        return info

    def get(self, session_id: str) -> SessionInfo | None:
        return self._sessions.get(session_id)

    def set_task(self, session_id: str, task: asyncio.Task) -> None:
        self._sessions[session_id].task = task

    def clear_task(self, session_id: str, task: asyncio.Task | None) -> None:
        info = self._sessions.get(session_id)
        if info and info.task is task:
            info.task = None


sessions = SessionRegistry()


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


async def _is_waiting_for_input(session_id: str) -> bool:
    snapshot = await praxis_graph.aget_state(_config(session_id))
    return bool(snapshot.next) and any(getattr(t, "interrupts", None) for t in snapshot.tasks)


def finalize_report(session_id: str, *, outcome: str, force: bool = False) -> ReportArtifacts | None:
    info = sessions.get(session_id)
    if info is None or (info.report_finalized and not force):
        return info.report if info else None

    bus = registry.get_or_create(session_id)
    report = write_report(
        bus.trace_history(),
        session_id=session_id,
        goal=info.goal,
        outcome=outcome,
        started_at=info.started_at,
    )
    info.report = report
    info.report_finalized = True
    bus.publish(
        EventType.REPORT_READY,
        {"outcome": outcome, "markdown_file": report.markdown_path.name, "json_file": report.json_path.name},
    )
    return report


def stop_session(session_id: str) -> SessionInfo | None:
    """Cancel an active run, or explicitly close a session paused for human input."""
    info = sessions.get(session_id)
    if info is None:
        return None
    if info.status == "waiting_input":
        set_current_session(session_id)
        info.status = "stopped"
        registry.get_or_create(session_id).publish(EventType.RUN_STOPPED, {"reason": "Stopped by TUI user."})
        finalize_report(session_id, outcome="stopped", force=True)
        return info
    if info.status == "running" and info.task and not info.task.done():
        info.status = "stopping"
        info.task.cancel()
    return info


async def start_session(session_id: str, goal: str) -> None:
    set_current_session(session_id)
    bus = registry.get_or_create(session_id)
    info = sessions.get(session_id) or sessions.create(session_id, goal)
    task = asyncio.current_task()
    try:
        await praxis_graph.ainvoke(
            {"goal": goal, "session_id": session_id, "messages": []},
            config=_config(session_id),
        )
        info.status = "waiting_input" if await _is_waiting_for_input(session_id) else "completed"
        finalize_report(session_id, outcome=info.status)
    except asyncio.CancelledError:
        info.status = "stopped"
        bus.publish(EventType.RUN_STOPPED, {"reason": "Stopped by TUI user."})
        finalize_report(session_id, outcome="stopped")
    except Exception as exc:  # noqa: BLE001
        info.status = "failed"
        info.error = str(exc)
        bus.publish(EventType.ERROR, {"error": str(exc)})
        finalize_report(session_id, outcome="failed")
    finally:
        sessions.clear_task(session_id, task)


async def send_message(session_id: str, text: str) -> None:
    set_current_session(session_id)
    bus = registry.get_or_create(session_id)
    info = sessions.get(session_id) or sessions.create(session_id, text)
    info.status = "running"
    info.error = None
    info.report_finalized = False
    task = asyncio.current_task()
    try:
        if await _is_waiting_for_input(session_id):
            await praxis_graph.ainvoke(Command(resume=text), config=_config(session_id))
        else:
            await praxis_graph.ainvoke(
                {"messages": [HumanMessage(content=text)], "goal": text},
                config=_config(session_id),
            )
        info.status = "waiting_input" if await _is_waiting_for_input(session_id) else "completed"
        finalize_report(session_id, outcome=info.status)
    except asyncio.CancelledError:
        info.status = "stopped"
        bus.publish(EventType.RUN_STOPPED, {"reason": "Stopped by TUI user."})
        finalize_report(session_id, outcome="stopped")
    except Exception as exc:  # noqa: BLE001
        info.status = "failed"
        info.error = str(exc)
        bus.publish(EventType.ERROR, {"error": str(exc)})
        finalize_report(session_id, outcome="failed")
    finally:
        sessions.clear_task(session_id, task)
