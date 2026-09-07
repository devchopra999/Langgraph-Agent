"""Deterministic Markdown and JSON execution-trace reports."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from praxis_agent.config import settings

_SENSITIVE_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|credential|password|passwd|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_INLINE_SECRET = re.compile(
    r"(?im)\b(api[_-]?key|authorization|cookie|credential|password|passwd|private[_-]?key|secret|token)"
    r"\s*([:=])\s*([^\s,;]+)"
)


@dataclass(frozen=True)
class ReportArtifacts:
    markdown_path: Path
    json_path: Path


def _redact(value: Any, *, sensitive: bool = False) -> Any:
    if sensitive:
        return "<redacted>"
    if isinstance(value, dict):
        return {str(key): _redact(item, sensitive=bool(_SENSITIVE_KEY.search(str(key)))) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _INLINE_SECRET.sub(r"\1\2<redacted>", value)
    return value


def _timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _json(value: Any, *, indent: int | None = 2) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, indent=indent, sort_keys=indent is not None)


def _event_description(event: dict[str, Any]) -> str:
    event_type = event["type"]
    payload = event["payload"]
    if event_type == "agent_thought":
        return payload.get("reason") or payload.get("summary") or "Agent planning update."
    if event_type == "case_classified":
        return f"Classified as {payload.get('case_type')} using {payload.get('workflow')}."
    if event_type == "hypothesis":
        return f"Hypothesis: {payload.get('hypothesis')}"
    if event_type == "scenario_started":
        return f"Started scenario: {payload.get('scenario', {}).get('name', 'unnamed')}"
    if event_type == "scenario_completed":
        return f"Scenario outcome: {payload.get('summary')}"
    if event_type == "verify_result":
        return f"Assessment: {payload.get('reasoning')}"
    if event_type == "escalation":
        return "Paused for developer input."
    if event_type == "run_completed":
        return f"Completed: {payload.get('final_answer')}"
    if event_type == "run_stopped":
        return "Stopped by the TUI user."
    if event_type == "error":
        return f"Run failed: {payload.get('error')}"
    return event_type.replace("_", " ").capitalize()


def _next_action(events: list[dict[str, Any]], index: int) -> str | None:
    for event in events[index + 1 :]:
        if event["type"] == "tool_call_started":
            return f"Called `{event['payload'].get('tool')}` next."
        if event["type"] in {
            "agent_thought",
            "case_classified",
            "hypothesis",
            "scenario_started",
            "scenario_completed",
            "verify_result",
            "escalation",
            "run_completed",
            "run_stopped",
            "error",
        }:
            return _event_description(event)
    return None


def render_markdown(trace: list[dict[str, Any]], *, session_id: str, goal: str, outcome: str, started_at: float) -> str:
    events = _redact(trace)
    finished_at = events[-1]["ts"] if events else started_at
    duration = max(0, finished_at - started_at)
    lines = [
        "# Praxis Lens execution report",
        "",
        f"- **Session:** `{session_id}`",
        f"- **Outcome:** {outcome}",
        f"- **Goal:** {_redact(goal)}",
        f"- **Started:** {_timestamp(started_at)}",
        f"- **Finished:** {_timestamp(finished_at)}",
        f"- **Duration:** {duration:.1f}s",
        "",
        "## Timeline",
    ]
    for index, event in enumerate(events):
        event_type = event["type"]
        payload = event["payload"]
        lines.extend(["", f"### {_timestamp(event['ts'])} - {event_type.replace('_', ' ').title()}"])
        if event_type == "tool_call_started":
            lines.extend(
                [
                    f"**Why:** {payload.get('reason')}",
                    f"**Action:** `{payload.get('tool')}`",
                    "```json",
                    _json(payload.get("args", {})),
                    "```",
                ]
            )
        elif event_type == "tool_call_completed":
            lines.extend(
                [
                    f"**Tool:** `{payload.get('tool')}`",
                    "**Response:**",
                    "```json",
                    _json(payload.get("result")),
                    "```",
                ]
            )
            next_action = _next_action(events, index)
            if next_action:
                lines.append(f"**What happened next:** {next_action}")
        elif event_type == "tool_call_failed":
            lines.extend(
                [
                    f"**Tool:** `{payload.get('tool')}`",
                    "**Error:**",
                    "```json",
                    _json(payload.get("error")),
                    "```",
                ]
            )
            next_action = _next_action(events, index)
            if next_action:
                lines.append(f"**What happened next:** {next_action}")
        else:
            lines.append(_event_description(event))
    return "\n".join(lines) + "\n"


def write_report(
    trace: list[dict[str, Any]], *, session_id: str, goal: str, outcome: str, started_at: float
) -> ReportArtifacts:
    report_dir = Path(settings.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = f"{session_id}-{suffix}"
    redacted_trace = _redact(trace)
    markdown_path = report_dir / f"{stem}.md"
    json_path = report_dir / f"{stem}.json"
    markdown_path.write_text(
        render_markdown(trace, session_id=session_id, goal=goal, outcome=outcome, started_at=started_at),
        encoding="utf-8",
    )
    json_path.write_text(
        _json(
            {
                "session_id": session_id,
                "goal": _redact(goal),
                "outcome": outcome,
                "started_at": _timestamp(started_at),
                "events": redacted_trace,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return ReportArtifacts(markdown_path=markdown_path, json_path=json_path)
