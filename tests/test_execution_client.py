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


def test_call_service_endpoint_submits_request_and_returns_response():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post("http://executor.test/environments/env-123/services/auth/request").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "targetUrl": "http://auth:4000/users/1",
                        "method": "GET",
                        "statusCode": 200,
                        "headers": {"content-type": "application/json"},
                        "body": {"id": 1},
                        "durationMs": 12,
                    },
                )
            )
            result = await client.call_service_endpoint("env-123", "auth", "/users/1")

        assert json.loads(route.calls[0].request.content) == {"endpoint": "/users/1", "method": "GET", "timeout": 30}
        assert result["statusCode"] == 200
        assert result["body"] == {"id": 1}

    asyncio.run(verify())


def test_call_service_endpoint_rejects_timeout_above_sixty_seconds():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        try:
            await client.call_service_endpoint("env-123", "auth", "/users/1", timeout=61)
        except ValueError as exc:
            assert "between 1 and 60" in str(exc)
        else:
            raise AssertionError("Expected a timeout validation error")

    asyncio.run(verify())


def test_rebuild_posts_no_body_and_preserves_terminal_job_progress():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test", timeout=1)
        with respx.mock(assert_all_called=True) as mock:
            submit = mock.post("http://executor.test/environments/env-123/services/edi/rebuild").mock(
                return_value=httpx.Response(202, json={"jobId": "job-123", "status": "queued"})
            )
            mock.get("http://executor.test/jobs/job-123").mock(
                return_value=httpx.Response(200, json={"status": "ready", "progress": ["building", "ready"]})
            )
            result = await client.rebuild_service("env-123", "edi")

        assert submit.calls[0].request.content == b""
        assert result["jobId"] == "job-123"
        assert result["job"]["status"] == "ready"
        assert result["job"]["progress"] == ["building", "ready"]

    asyncio.run(verify())


def test_rebuild_can_return_queued_without_polling():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/environments/env-123/services/edi/rebuild").mock(
                return_value=httpx.Response(202, json={"jobId": "job-123", "status": "queued"})
            )
            result = await client.rebuild_service("env-123", "edi", wait=False)

        assert result == {"jobId": "job-123", "status": "queued"}

    asyncio.run(verify())


def test_orchestrator_routes_use_sourceservice_destinationservice_pointsto_contract():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            put_route = mock.put("http://executor.test/environments/env-123/orchestrator/routes/mob/edi").mock(
                return_value=httpx.Response(
                    200,
                    json={"sourceService": "mob", "destinationService": "edi", "pointsTo": "mock-server", "updatedAt": "t"},
                )
            )
            bulk = mock.post("http://executor.test/environments/env-123/orchestrator/routes/bulk").mock(
                return_value=httpx.Response(200, json={"registered": [], "errors": []})
            )
            delete = mock.delete("http://executor.test/environments/env-123/orchestrator/routes/mob/edi").mock(
                return_value=httpx.Response(204)
            )
            aliases = mock.put("http://executor.test/environments/env-123/orchestrator/aliases").mock(
                return_value=httpx.Response(200, json={"aliases": {"api.example.com": "axis-api"}})
            )
            delete_alias = mock.delete("http://executor.test/environments/env-123/orchestrator/aliases/api.example.com").mock(
                return_value=httpx.Response(200, json={"aliases": {}})
            )

            set_result = await client.set_orchestrator_route("env-123", "mob", "edi", "mock-server")
            await client.bulk_set_orchestrator_routes(
                "env-123", [{"sourceService": "mob", "destinationService": "edi", "pointsTo": "mock-server"}]
            )
            await client.delete_orchestrator_route("env-123", "mob", "edi")
            await client.update_orchestrator_aliases("env-123", {"api.example.com": "axis-api"})
            await client.delete_orchestrator_alias("env-123", "api.example.com")

        assert json.loads(put_route.calls[0].request.content) == {"pointsTo": "mock-server"}
        assert set_result["pointsTo"] == "mock-server"
        assert json.loads(bulk.calls[0].request.content) == {
            "routes": [{"sourceService": "mob", "destinationService": "edi", "pointsTo": "mock-server"}]
        }
        assert delete.called
        assert json.loads(aliases.calls[0].request.content) == {"aliases": {"api.example.com": "axis-api"}}
        assert delete_alias.called

    asyncio.run(verify())


def test_set_orchestrator_route_rejects_url_as_points_to():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        try:
            await client.set_orchestrator_route("env-123", "mob", "edi", "http://mock-server")
        except ValueError as exc:
            assert "never a URL" in str(exc)
        else:
            raise AssertionError("Expected a points_to validation error")

    asyncio.run(verify())


def test_only_exact_route_not_found_is_expected():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.get("http://executor.test/environments/env-123/orchestrator/routes/mob/edi").mock(
                return_value=httpx.Response(404, json={"error": {"code": "ORCHESTRATOR_ROUTE_NOT_FOUND", "message": "not found"}})
            )
            result = await client.get_orchestrator_route("env-123", "mob", "edi")

        assert result == {"found": False, "route": None}

    asyncio.run(verify())


def test_route_lookup_does_not_suppress_transport_failure():
    from praxis_agent.clients.execution_client import ExecutionServiceError

    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.get("http://executor.test/environments/env-123/orchestrator/routes/mob/edi").mock(
                return_value=httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR", "message": "boom"}})
            )
            try:
                await client.get_orchestrator_route("env-123", "mob", "edi")
            except ExecutionServiceError as exc:
                assert exc.code == "INTERNAL_ERROR"
            else:
                raise AssertionError("Expected the unrelated error to propagate")

    asyncio.run(verify())


def test_aider_rejects_invalid_timeout():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test")
        for bad in (0, -1, 1_800_001):
            try:
                await client.code_ask("env-123", "edi", "explain this", timeout_ms=bad)
            except ValueError:
                continue
            raise AssertionError(f"Expected timeout_ms={bad} to be rejected")

    asyncio.run(verify())


def test_aider_transport_honors_timeout_budget():
    async def verify():
        client = ExecutionClient(base_url="http://executor.test", timeout=1)
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/environments/env-123/services/edi/code/edit").mock(
                return_value=httpx.Response(200, json={"diff": ""})
            )
            # A large timeout_ms should not raise even though the client's base timeout is tiny -
            # the transport budget must scale with the requested aider timeout.
            result = await client.code_edit("env-123", "edi", "fix the bug", timeout_ms=600_000)

        assert result == {"diff": ""}

    asyncio.run(verify())

