"""Async HTTP client for the Praxis Lens Execution Service.

One method per documented endpoint (see the execution service README). Long-running
operations that return a `jobId` are wrapped with `_run_job`, which polls `GET /jobs/:id`
until the job reaches a terminal state, optionally emitting progress through `on_progress`
so the caller (a LangGraph tool) can forward granular updates to the SSE event bus.

This module never runs Docker/git/shell commands itself — it is a thin, typed wrapper
around the execution service's HTTP API, which is the only thing allowed to touch the
Docker Engine, per Praxis Lens's security model.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

import httpx

from praxis_agent.api_call_log import log_api_call
from praxis_agent.config import settings

ProgressCallback = Optional[Callable[[dict[str, Any]], None]]


class ExecutionServiceError(RuntimeError):
    """Raised when the execution service returns an error payload or a job fails/times out."""

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class JobTimeoutError(ExecutionServiceError):
    pass


class JobFailedError(ExecutionServiceError):
    pass


class ExecutionClient:
    def __init__(self, base_url: str | None = None, timeout: float = 300.0):
        self.base_url = (base_url or settings.execution_service_url).rstrip("/")
        self._timeout = timeout

    # ------------------------------------------------------------------ #
    # low-level request helper
    # ------------------------------------------------------------------ #
    async def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None, timeout: float | None = None
    ) -> Any:
        url = f"{self.base_url}{path}"
        started = time.monotonic()
        status_code: int | None = None
        response_body: Any = None
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=timeout if timeout is not None else self._timeout) as client:
                resp = await client.request(method, url, json=json, params=params)
            status_code = resp.status_code
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    response_body = body
                    err = body.get("error", {})
                    raise ExecutionServiceError(
                        err.get("message", f"HTTP {resp.status_code}"),
                        code=err.get("code"),
                        details=err,
                    )
                except ValueError:
                    error = f"HTTP {resp.status_code}: {resp.text}"
                    raise ExecutionServiceError(error)
            if resp.status_code == 204 or not resp.content:
                response_body = {}
                return {}
            response_body = resp.json()
            return response_body
        except ExecutionServiceError as exc:
            error = error or str(exc)
            raise
        finally:
            log_api_call(
                client="execution_service",
                method=method,
                url=url,
                request_body=json,
                params=params,
                status_code=status_code,
                response_body=response_body,
                error=error,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    # ------------------------------------------------------------------ #
    # job polling
    # ------------------------------------------------------------------ #
    async def get_job(self, job_id: str) -> dict:
        return await self._request("GET", f"/jobs/{job_id}")

    async def _run_job(
        self,
        job_id: str,
        *,
        on_progress: ProgressCallback = None,
        timeout_sec: float | None = None,
        poll_interval_sec: float | None = None,
    ) -> dict:
        timeout_sec = timeout_sec if timeout_sec is not None else settings.job_poll_timeout_sec
        poll_interval_sec = poll_interval_sec if poll_interval_sec is not None else settings.job_poll_interval_sec
        deadline = time.monotonic() + timeout_sec
        seen_progress = 0
        last_job: dict = {}
        while True:
            last_job = await self.get_job(job_id)
            progress = last_job.get("progress") or []
            if on_progress and len(progress) > seen_progress:
                for line in progress[seen_progress:]:
                    on_progress({"jobId": job_id, "step": line})
                seen_progress = len(progress)
            status = last_job.get("status")
            if status == "ready":
                return last_job
            if status == "failed":
                raise JobFailedError(
                    last_job.get("error") or f"Job {job_id} failed",
                    details=last_job,
                )
            if status == "timeout":
                raise JobTimeoutError(
                    f"Job {job_id} timed out on the execution service",
                    details=last_job,
                )
            if time.monotonic() > deadline:
                raise JobTimeoutError(
                    f"Timed out client-side waiting for job {job_id} (status={status})",
                    details=last_job,
                )
            await asyncio.sleep(poll_interval_sec)

    # ------------------------------------------------------------------ #
    # environments
    # ------------------------------------------------------------------ #
    async def create_environment(
        self,
        services: list[str],
        repository: dict[str, str] | None = None,
        *,
        on_progress: ProgressCallback = None,
        wait: bool = True,
    ) -> dict:
        body: dict[str, Any] = {"services": services}
        if repository:
            body["repository"] = repository
        created = await self._request("POST", "/environments", json=body)
        if not wait:
            return created
        # Provisioning several services from scratch (image pulls/builds) can take longer than
        # a single service start/stop/restart, so this gets its own longer timeout.
        job = await self._run_job(
            created["jobId"],
            on_progress=on_progress,
            timeout_sec=settings.job_poll_timeout_sec_create_environment,
        )
        return {**created, "job": job}

    async def get_environment(self, environment_id: str) -> dict:
        return await self._request("GET", f"/environments/{environment_id}")

    async def delete_environment(self, environment_id: str) -> dict:
        return await self._request("DELETE", f"/environments/{environment_id}")

    # ------------------------------------------------------------------ #
    # services lifecycle
    # ------------------------------------------------------------------ #
    async def start_service(
        self,
        environment_id: str,
        service: str,
        branch: str | None = None,
        *,
        on_progress: ProgressCallback = None,
        wait: bool = True,
    ) -> dict:
        body = {"branch": branch} if branch else {}
        started = await self._request("POST", f"/environments/{environment_id}/services/{service}/start", json=body)
        if not wait:
            return started
        job = await self._run_job(started["jobId"], on_progress=on_progress)
        return {**started, "job": job}

    async def stop_service(self, environment_id: str, service: str, *, on_progress: ProgressCallback = None, wait: bool = True) -> dict:
        stopped = await self._request("POST", f"/environments/{environment_id}/services/{service}/stop")
        if not wait:
            return stopped
        job = await self._run_job(stopped["jobId"], on_progress=on_progress)
        return {**stopped, "job": job}

    async def restart_service(self, environment_id: str, service: str, *, on_progress: ProgressCallback = None, wait: bool = True) -> dict:
        restarted = await self._request("POST", f"/environments/{environment_id}/services/{service}/restart")
        if not wait:
            return restarted
        job = await self._run_job(restarted["jobId"], on_progress=on_progress)
        return {**restarted, "job": job}

    async def rebuild_service(self, environment_id: str, service: str, *, on_progress: ProgressCallback = None, wait: bool = True) -> dict:
        # Unlike restart, this rebuilds the image from the current checkout first, so it picks
        # up in-place source edits (e.g. from aider) for compiled-language services.
        rebuilt = await self._request("POST", f"/environments/{environment_id}/services/{service}/rebuild")
        if not wait:
            return rebuilt
        job = await self._run_job(rebuilt["jobId"], on_progress=on_progress)
        return {**rebuilt, "job": job}

    # ------------------------------------------------------------------ #
    # repository
    # ------------------------------------------------------------------ #
    async def attach_repository(
        self,
        environment_id: str,
        url: str,
        commit: str,
        *,
        on_progress: ProgressCallback = None,
        wait: bool = True,
    ) -> dict:
        queued = await self._request(
            "POST", f"/environments/{environment_id}/repository", json={"url": url, "commit": commit}
        )
        if not wait:
            return queued
        job = await self._run_job(queued["jobId"], on_progress=on_progress)
        return {**queued, "job": job}

    # ------------------------------------------------------------------ #
    # inspection
    # ------------------------------------------------------------------ #
    async def get_logs(self, environment_id: str, service: str, tail: int | None = None, since: str | None = None) -> dict:
        params = {}
        if tail is not None:
            params["tail"] = tail
        if since is not None:
            params["since"] = since
        return await self._request("GET", f"/environments/{environment_id}/services/{service}/logs", params=params)

    async def get_service_endpoints(self, environment_id: str) -> dict:
        return await self._request("GET", f"/environments/{environment_id}/service-endpoints")

    async def call_service_endpoint(
        self,
        environment_id: str,
        service: str,
        endpoint: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: Any = None,
        timeout: int = 30,
    ) -> dict:
        if timeout < 1 or timeout > 60:
            raise ValueError("call_service_endpoint timeout must be between 1 and 60 seconds")
        payload: dict[str, Any] = {"endpoint": endpoint, "method": method}
        if headers is not None:
            payload["headers"] = headers
        if body is not None:
            payload["body"] = body
        payload["timeout"] = timeout
        return await self._request(
            "POST", f"/environments/{environment_id}/services/{service}/request", json=payload
        )

    async def get_service_env(self, environment_id: str, service: str) -> dict:
        return await self._request("GET", f"/environments/{environment_id}/services/{service}/env")

    async def update_service_env(self, environment_id: str, service: str, env: dict[str, str]) -> dict:
        return await self._request(
            "PUT", f"/environments/{environment_id}/services/{service}/env", json={"env": env}
        )

    async def query_database(self, environment_id: str, service: str, query: str) -> dict:
        return await self._request(
            "POST", f"/environments/{environment_id}/services/{service}/query", json={"query": query}
        )

    async def execute_command(self, environment_id: str, service: str, command: list[str], timeout: int | None = None) -> dict:
        body: dict[str, Any] = {"service": service, "command": command}
        if timeout is not None:
            body["timeout"] = timeout
        return await self._request("POST", f"/environments/{environment_id}/execute", json=body)

    async def get_service_metrics(
        self, environment_id: str, service: str, duration: int | None = None, interval: int | None = None
    ) -> dict:
        params = {}
        if duration is not None:
            params["duration"] = duration
        if interval is not None:
            params["interval"] = interval
        return await self._request(
            "GET", f"/environments/{environment_id}/services/{service}/metrics", params=params
        )

    async def get_environment_metrics(
        self,
        environment_id: str,
        services: list[str] | None = None,
        duration: int | None = None,
        interval: int | None = None,
    ) -> dict:
        params: dict[str, Any] = {}
        if services:
            params["services"] = ",".join(services)
        if duration is not None:
            params["duration"] = duration
        if interval is not None:
            params["interval"] = interval
        return await self._request("GET", f"/environments/{environment_id}/metrics", params=params)

    async def run_load_test(
        self,
        environment_id: str,
        service: str,
        endpoint: str,
        method: str,
        headers: dict[str, str],
        body: dict[str, Any],
        hit_count: int,
        timeout: int,
        *,
        on_progress: ProgressCallback = None,
    ) -> dict:
        if timeout > 60:
            raise ValueError("Load-test per-request timeout cannot exceed 60 seconds")
        queued = await self._request(
            "POST",
            f"/environments/{environment_id}/services/{service}/load-test",
            json={
                "endpoint": endpoint,
                "method": method,
                "headers": headers,
                "body": body,
                "hitCount": hit_count,
                "timeout": timeout,
            },
        )
        job = await self._run_job(queued["jobId"], on_progress=on_progress)
        return {**queued, "job": job}

    # ------------------------------------------------------------------ #
    # config (the endpoint writes a per-service env file that takes effect on restart)
    # ------------------------------------------------------------------ #
    async def set_config(self, environment_id: str, service: str, key: str, value: str) -> dict:
        return await self._request(
            "POST",
            f"/environments/{environment_id}/services/{service}/config",
            json={"key": key, "value": value},
        )

    # convenience alias so tool docstrings can talk about "env vars" explicitly
    async def set_env_var(self, environment_id: str, service: str, key: str, value: str) -> dict:
        return await self.set_config(environment_id, service, key, value)

    # ------------------------------------------------------------------ #
    # orchestrator dynamic routing (zero-downtime service repointing, e.g. redirecting a
    # dependency to another in-environment service or A/B-testing two versions of a service — no
    # restart involved, takes effect on the very next request)
    # ------------------------------------------------------------------ #
    async def get_orchestrator_status(self, environment_id: str) -> dict:
        return await self._request("GET", f"/environments/{environment_id}/orchestrator")

    async def list_orchestrator_routes(self, environment_id: str) -> list[dict]:
        return await self._request("GET", f"/environments/{environment_id}/orchestrator/routes")

    async def get_orchestrator_route(self, environment_id: str, source_service: str, destination_service: str) -> dict:
        # Exact (sourceService, destinationService) lookup only, no wildcard fallback. Only the
        # executor's explicit ORCHESTRATOR_ROUTE_NOT_FOUND is shimmed to {"found": False, "route":
        # None} so callers can check absence without exception handling; unrelated errors propagate.
        try:
            return await self._request(
                "GET", f"/environments/{environment_id}/orchestrator/routes/{source_service}/{destination_service}"
            )
        except ExecutionServiceError as exc:
            if exc.code == "ORCHESTRATOR_ROUTE_NOT_FOUND":
                return {"found": False, "route": None}
            raise

    @staticmethod
    def _validate_points_to(points_to: str) -> None:
        if not points_to or not points_to.strip():
            raise ValueError("points_to must be a non-empty catalog service name")
        if "://" in points_to:
            raise ValueError('points_to must be a catalog service name (e.g. "mock-server"), never a URL')

    async def set_orchestrator_route(
        self, environment_id: str, source_service: str, destination_service: str, points_to: str
    ) -> dict:
        self._validate_points_to(points_to)
        return await self._request(
            "PUT",
            f"/environments/{environment_id}/orchestrator/routes/{source_service}/{destination_service}",
            json={"pointsTo": points_to},
        )

    async def bulk_set_orchestrator_routes(self, environment_id: str, routes: list[dict]) -> dict:
        for route in routes:
            self._validate_points_to(route.get("pointsTo", ""))
        return await self._request(
            "POST", f"/environments/{environment_id}/orchestrator/routes/bulk", json={"routes": routes}
        )

    async def delete_orchestrator_route(self, environment_id: str, source_service: str, destination_service: str) -> dict:
        return await self._request(
            "DELETE", f"/environments/{environment_id}/orchestrator/routes/{source_service}/{destination_service}"
        )

    async def update_orchestrator_aliases(self, environment_id: str, aliases: dict[str, str]) -> dict:
        return await self._request(
            "PUT", f"/environments/{environment_id}/orchestrator/aliases", json={"aliases": aliases}
        )

    async def delete_orchestrator_alias(self, environment_id: str, host: str) -> dict:
        return await self._request("DELETE", f"/environments/{environment_id}/orchestrator/aliases/{host}")

    # ------------------------------------------------------------------ #
    # code (aider)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_aider_timeout(timeout_ms: int) -> None:
        if timeout_ms < 1 or timeout_ms > 1_800_000:
            raise ValueError("timeout_ms must be between 1 and 1,800,000 (30 minutes)")

    async def code_ask(self, environment_id: str, service: str, prompt: str, timeout_ms: int | None = None) -> dict:
        body: dict[str, Any] = {"prompt": prompt}
        if timeout_ms is not None:
            self._validate_aider_timeout(timeout_ms)
            body["timeoutMs"] = timeout_ms
        # Give the HTTP transport enough headroom to outlast the executor's own aider timeout
        # (plus a fixed buffer for round-trip/queueing) rather than the client's fixed default,
        # since aider prompts can legitimately run for many minutes.
        transport_timeout = max(self._timeout, (timeout_ms or 300_000) / 1000 + 30)
        return await self._request(
            "POST", f"/environments/{environment_id}/services/{service}/code/ask", json=body, timeout=transport_timeout
        )

    async def code_edit(self, environment_id: str, service: str, prompt: str, timeout_ms: int | None = None) -> dict:
        body: dict[str, Any] = {"prompt": prompt}
        if timeout_ms is not None:
            self._validate_aider_timeout(timeout_ms)
            body["timeoutMs"] = timeout_ms
        transport_timeout = max(self._timeout, (timeout_ms or 300_000) / 1000 + 30)
        return await self._request(
            "POST", f"/environments/{environment_id}/services/{service}/code/edit", json=body, timeout=transport_timeout
        )


# Module-level singleton — stateless aside from base_url, safe to share.
execution_client = ExecutionClient()
