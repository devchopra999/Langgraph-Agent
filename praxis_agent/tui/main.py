"""Python TUI for the Praxis Lens agent.

Connects to a running session's SSE stream and renders a live-updating view of what the
agent is doing — matching the mockup from the architecture doc (checklist of completed
steps + current action).

Usage:
    python -m praxis_agent.tui.main --goal "Reproduce the intermittent EDI/Axis failure"
    python -m praxis_agent.tui.main --session-id session-abc123   # attach to an existing session
"""
from __future__ import annotations

import argparse
import json
import threading
import time

import requests
import sseclient
from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

MAX_LOG_LINES = 24


class TuiState:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.status = "starting"
        self.completed_steps: list[str] = []
        self.current_action: str = "Initializing..."
        self.error: str | None = None
        self.lock = threading.Lock()

    def add_line(self, line: str) -> None:
        with self.lock:
            self.completed_steps.append(line)
            if len(self.completed_steps) > MAX_LOG_LINES:
                self.completed_steps = self.completed_steps[-MAX_LOG_LINES:]

    def set_current(self, action: str) -> None:
        with self.lock:
            self.current_action = action


def _e(value) -> str:
    """Escape a dynamic value so it can't be misparsed as (invalid/unbalanced) rich markup.

    Tool/job error text (docker output, stack traces, file paths with brackets, etc.) is
    arbitrary and frequently contains "[...]" sequences. Passing that straight into an
    f-string that later goes through Text.from_markup() can raise rich.errors.MarkupError
    (e.g. on a stray "[/]" or a mismatched closing tag), which kills the render loop and
    leaves the TUI showing nothing but "Status: failed" with no detail.
    """
    return escape(str(value))


def _truncate(value, length: int = 200) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= length else text[: length - 3] + "..."


def _format_args(args: dict | None) -> str:
    """Render a tool's args compactly, e.g. " (service=mob, environment_id=env-123)"."""
    if not args:
        return ""
    parts = [f"{k}={_truncate(v, 60)}" for k, v in args.items()]
    return f" [dim]({_e(', '.join(parts))})[/]"


def _format_event(event_type: str, payload: dict) -> str | None:
    if event_type == "case_classified":
        return (
            f"[bold cyan]Classified case[/]: {_e(payload.get('case_type'))} "
            f"(workflow: {_e(payload.get('workflow'))}, scenario iteration: "
            f"{_e(payload.get('needs_scenario_iteration'))})"
        )
    if event_type == "hypothesis":
        return f"[bold yellow]Hypothesis[/]: {_e(payload.get('hypothesis'))}"
    if event_type == "agent_thought":
        stage = payload.get("stage")
        if stage == "acting":
            tools = ", ".join(payload.get("tools") or [])
            return f"[dim]\U0001F4AD {_e(payload.get('reason'))}[/] [dim](calling {_e(tools)})[/]"
        return f"[dim]\U0001F4AD {_e(payload.get('summary'))}[/]"
    if event_type == "tool_call_started":
        return None  # shown as "current action" instead, to avoid duplicate noisy lines
    if event_type == "tool_call_completed":
        args_str = _format_args(payload.get("args"))
        preview = _e(_truncate(payload.get("result_preview"), 200))
        return (
            f"[green]\u2713[/] {_e(payload.get('tool'))}{args_str} [dim]— {_e(payload.get('reason'))}[/]\n"
            f"    [dim]\u2192 {preview}[/]"
        )
    if event_type == "tool_call_failed":
        args_str = _format_args(payload.get("args"))
        return f"[red]\u2717[/] {_e(payload.get('tool'))}{args_str} — {_e(payload.get('error'))} [dim](reason: {_e(payload.get('reason'))})[/]"
    if event_type == "job_progress":
        return f"  [dim]... {_e(payload.get('step'))}[/]"
    if event_type == "skill_loaded":
        return f"[magenta]\U0001F4D6 loaded skill[/]: {_e(payload.get('name'))}"
    if event_type == "scenario_started":
        return f"[bold blue]\u25b6 scenario[/]: {_e(payload.get('scenario'))}"
    if event_type == "scenario_completed":
        passed = payload.get("passed")
        mark = "[green]PASS[/]" if passed else ("[red]FAIL[/]" if passed is False else "[yellow]?[/]")
        return f"  scenario result {mark}: {_e(payload.get('summary'))}"
    if event_type == "verify_result":
        confirmed = payload.get("confirmed")
        mark = "[green]confirmed[/]" if confirmed else "[red]denied[/]"
        return f"[bold]Verify[/]: {mark} — {_e(payload.get('reasoning'))}"
    if event_type == "escalation":
        return "[bold red]\u26a0 Escalating to you[/] — the agent couldn't confirm a fix within its iteration budget."
    if event_type == "run_completed":
        return f"[bold green]\u2714 Done[/]: {_e(payload.get('final_answer'))}"
    if event_type == "error":
        return f"[bold red]ERROR[/]: {_e(payload.get('error'))}"
    return f"{_e(event_type)}: {_e(json.dumps(payload)[:200])}"


def render(state: TuiState) -> Panel:
    lines = [Text.from_markup(f"[bold]Session:[/] {state.session_id}   [bold]Status:[/] {state.status}")]
    lines.append(Text(""))
    for step in state.completed_steps:
        try:
            lines.append(Text.from_markup(step))
        except Exception:  # noqa: BLE001 - never let a bad line crash the whole TUI
            lines.append(Text(step))
    body = Group(*lines)
    footer = Spinner("dots", text=f" {state.current_action}") if state.status == "running" else Text(state.current_action)
    return Panel(Group(body, Text(""), footer), title="Praxis Lens", border_style="cyan")


def stream_events(base_url: str, state: TuiState) -> None:
    url = f"{base_url}/sessions/{state.session_id}/events"
    while True:
        try:
            resp = requests.get(url, stream=True, headers={"Accept": "text/event-stream"})
            client = sseclient.SSEClient(resp)
            for sse_event in client.events():
                try:
                    event = json.loads(sse_event.data)
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                payload = event.get("payload", {})
                if event_type == "tool_call_started":
                    reason = payload.get("reason")
                    args_str = _format_args(payload.get("args"))
                    action = f"Running {payload.get('tool')}{args_str}..."
                    if reason:
                        action += f" ({reason})"
                    state.set_current(action)
                line = _format_event(event_type, payload)
                if line:
                    state.add_line(line)
                if event_type == "run_completed":
                    state.status = "completed"
                    state.set_current("Done.")
                if event_type == "escalation":
                    state.status = "waiting_input"
                    state.set_current("Waiting for your input (reply via the API /message endpoint)...")
                if event_type == "error":
                    state.status = "failed"
                    state.set_current(f"Failed: {payload.get('error', 'unknown error')}")
            return
        except requests.exceptions.RequestException:
            time.sleep(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Praxis Lens TUI")
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--goal", default=None, help="Start a new session with this goal")
    parser.add_argument("--session-id", default=None, help="Attach to an existing session id")
    args = parser.parse_args()

    if args.session_id:
        session_id = args.session_id
    elif args.goal:
        resp = requests.post(f"{args.server}/sessions", json={"goal": args.goal})
        resp.raise_for_status()
        session_id = resp.json()["sessionId"]
    else:
        parser.error("Provide either --goal (new session) or --session-id (attach)")
        return

    state = TuiState(session_id)
    state.status = "running"
    thread = threading.Thread(target=stream_events, args=(args.server, state), daemon=True)
    thread.start()

    with Live(render(state), refresh_per_second=8) as live:
        while thread.is_alive():
            live.update(render(state))
            time.sleep(0.15)
        live.update(render(state))


if __name__ == "__main__":
    main()
