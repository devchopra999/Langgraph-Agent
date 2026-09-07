"""Focused contract tests for the supported executor endpoints."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import respx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis_agent.clients.execution_client import ExecutionClient


def test_create_environment_serializes_only_supported_inputs():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post("http://executor.test/environments").mock(
                return_value=httpx.Response(202, json={"environmentId": "env-123", "jobId": "job-123"})
            )
            result = await client.create_environment(
                ["edi"],
                repository={"url": "https://github.com/example/edi.git", "commit": "abc123"},
                wait=False,
            )

        assert result["environmentId"] == "env-123"
        assert json.loads(route.calls[0].request.content) == {
            "services": ["edi"],
            "repository": {"url": "https://github.com/example/edi.git", "commit": "abc123"},
        }

    asyncio.run(verify())
    client = ExecutionClient(base_url="http://executor.test")
    assert not hasattr(client, "rebuild_service")
    assert not hasattr(client, "set_secret")


def test_service_env_and_orchestrator_status_endpoints():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            get_env = mock.get("http://executor.test/environments/env-123/services/edi/env").mock(
                return_value=httpx.Response(200, json={"service": "edi", "env": {"AXIS_URL": "https://axis.example"}})
            )
            put_env = mock.put("http://executor.test/environments/env-123/services/edi/env").mock(
                return_value=httpx.Response(200, json={"service": "edi", "env": {"AXIS_URL": "https://mock.example"}})
            )
            orchestrator = mock.get("http://executor.test/environments/env-123/orchestrator").mock(
                return_value=httpx.Response(200, json={"healthy": True, "internalUrl": "http://orchestrator:8000"})
            )

            current_env = await client.get_service_env("env-123", "edi")
            updated_env = await client.update_service_env("env-123", "edi", {"AXIS_URL": "https://mock.example"})
            status = await client.get_orchestrator_status("env-123")

        assert current_env["env"]["AXIS_URL"] == "https://axis.example"
        assert updated_env["env"]["AXIS_URL"] == "https://mock.example"
        assert status["healthy"] is True
        assert json.loads(put_env.calls[0].request.content) == {"env": {"AXIS_URL": "https://mock.example"}}
        assert get_env.called
        assert orchestrator.called

    asyncio.run(verify())


def test_run_load_test_submits_request_and_returns_terminal_job():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test", timeout=1)
        with respx.mock(assert_all_called=True) as mock:
            submit = mock.post("http://executor.test/environments/env-123/services/auth/load-test").mock(
                return_value=httpx.Response(202, json={"jobId": "job-123", "status": "queued"})
            )
            poll = mock.get("http://executor.test/jobs/job-123").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "targetUrl": "http://auth:4000/health",
                        "method": "GET",
                        "hitCount": 20,
                        "completed": 20,
                        "missing": 0,
                        "succeeded": 20,
                        "failed": 0,
                        "statusCodes": {"200": 20},
                        "latencyMs": {"min": 3, "max": 41, "avg": 12},
                    },
                )
            )
            result = await client.run_load_test(
                "env-123",
                "auth",
                "/health",
                "GET",
                {},
                {},
                20,
                10,
            )

        assert json.loads(submit.calls[0].request.content) == {
            "endpoint": "/health",
            "method": "GET",
            "headers": {},
            "body": {},
            "hitCount": 20,
            "timeout": 10,
        }
        assert result["jobId"] == "job-123"
        assert result["job"]["status"] == "ready"
        assert result["job"]["latencyMs"] == {"min": 3, "max": 41, "avg": 12}
        assert poll.called

    asyncio.run(verify())


def test_run_load_test_rejects_per_request_timeout_above_sixty_seconds():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        try:
            await client.run_load_test("env-123", "auth", "/health", "GET", {}, {}, 20, 61)
        except ValueError as exc:
            assert str(exc) == "Load-test per-request timeout cannot exceed 60 seconds"
        else:
            raise AssertionError("Expected a timeout validation error")

    asyncio.run(verify())
