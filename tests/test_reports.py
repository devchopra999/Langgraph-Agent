"""Focused tests for execution-trace report capture, redaction, and cancellation."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis_agent.agent.context import set_current_reason, set_current_session
from praxis_agent.agent.events import EventType, new_id, registry
from praxis_agent.agent.reports import write_report
from praxis_agent.config import settings
from praxis_agent.tools._tool_utils import instrumented


def test_reports_keep_full_private_result_and_redact_artifacts():
    async def verify():
        session_id = new_id("report-test")
        set_current_session(session_id)
        set_current_reason("Inspect the service configuration before choosing a scenario.")
        bus = registry.get_or_create(session_id)

        @instrumented("read_config")
        async def read_config():
            return {
                "safe_value": "available",
                "api_key": "should-not-persist",
                "nested": {"password": "also-secret", "message": "token=hidden"},
            }

        await read_config()
        public_event = bus.history()[-1]
        trace_event = bus.trace_history()[-1]
        assert "result" not in public_event["payload"]
        assert trace_event["payload"]["result"]["safe_value"] == "available"
        bus.publish(EventType.AGENT_THOUGHT, {"stage": "acting", "reason": "Use the configuration to plan the scenario."})

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(settings, "report_dir", temp_dir):
            artifacts = write_report(
                bus.trace_history(),
                session_id=session_id,
                goal="Investigate token=keep-secret",
                outcome="completed",
                started_at=bus.trace_history()[0]["ts"],
            )
            markdown = artifacts.markdown_path.read_text(encoding="utf-8")
            report = json.loads(artifacts.json_path.read_text(encoding="utf-8"))

        assert "available" in markdown
        assert "should-not-persist" not in markdown
        assert "also-secret" not in markdown
        assert "hidden" not in markdown
        assert "keep-secret" not in markdown
        assert "<redacted>" in markdown
        assert report["events"][-2]["payload"]["result"]["safe_value"] == "available"
        assert report["events"][-2]["payload"]["result"]["api_key"] == "<redacted>"
        assert "What happened next" in markdown

    asyncio.run(verify())


def test_stop_session_cancels_run_and_creates_partial_report():
    async def verify():
        import praxis_agent.agent.runner as runner

        session_id = new_id("stop-test")
        runner.sessions.create(session_id, "Inspect a slow service")
        runner.registry.get_or_create(session_id)
        task = asyncio.create_task(runner.start_session(session_id, "Inspect a slow service"))
        runner.sessions.set_task(session_id, task)

        async def slow_run(*_args, **_kwargs):
            await asyncio.sleep(60)

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(settings, "report_dir", temp_dir), patch.object(
            runner.praxis_graph, "ainvoke", new=AsyncMock(side_effect=slow_run)
        ):
            await asyncio.sleep(0)
            info = runner.stop_session(session_id)
            assert info is not None
            assert info.status == "stopping"
            await task
            assert info.status == "stopped"
            assert info.report is not None
            report = json.loads(info.report.json_path.read_text(encoding="utf-8"))

        assert report["outcome"] == "stopped"
        assert any(event["type"] == EventType.RUN_STOPPED for event in report["events"])

    asyncio.run(verify())
