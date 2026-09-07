"""Async HTTP client for the real Mock Server API (Go/Gin + MongoDB).

The mock server stores two kinds of documents:
  - **MockedResponses** ("Response" docs) — hold the JSON payload (`response` field)
    that gets returned to callers, plus metadata (`api_name`, `context`, `type`,
    `response_id`, `stage`).
  - **InnovationMock** ("API" docs) — define an `endpoint` + `method` and point at
    the MockedResponses doc to serve via `conditions._id`.

Real endpoints implemented here:
  1. POST /response                -> create a MockedResponses doc
  2. GET  /response                 -> list all responses, grouped by api_name
  3. GET  /response/:id             -> fetch one response doc
  4. PUT  /response/:id             -> update a response's payload in place
  5. POST /api/                     -> register a new mock API (restarts the server!)
  6. GET  /api                      -> list all mock API definitions
  7. GET  /api/:id                  -> fetch one mock API definition
  8. PUT  /api/:id                  -> update a mock API (e.g. repoint conditions._id)
  9. (generic) call whatever endpoint/method was registered via POST /api/
  10. POST /e-kyc/stage              -> upsert eKYC stage for an applicationReferenceId
  11. GET  /gateway/api/neo-banking/biometric-casa/onboarding/v1/app-status/detailed/app-ref-id/:id
      -> detailed enquiry lookup, keyed off the stage set above
  12. POST /branchUpdation/          -> record a branch switch (infra ops)
  13. POST /branchUpdation/promote/  -> record a branch promotion (infra ops)
  14. POST /deploy/                  -> trigger/toggle a mock server deployment

Important operational note: `POST /api/` registers a brand-new route, but Gin only
binds routes once at boot from DB data (see main.go), so the server process calls
`os.Exit(0)` five seconds after responding. The new route only comes alive once a
supervisor (Docker restart policy, systemd, etc.) brings the process back up.
Switching which response an *existing* endpoint returns (`PUT /response/:id` or
`PUT /api/:id`) is live instantly and needs no restart.

The base URL is intentionally not required at import time — `configure()` (also
exposed as a tool) can set or change it at runtime once the mock-server URL is known.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

import httpx

from praxis_agent.api_call_log import log_api_call
from praxis_agent.config import settings


class MockServerError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


class MockServerNotConfiguredError(MockServerError):
    pass


class MockServerClient:
    def __init__(self, base_url: str | None = None, timeout: float = 15.0):
        self._base_url = (base_url or settings.mock_server_url or "").rstrip("/")
        self._timeout = timeout

    def configure(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> Any:
        if not self._base_url:
            raise MockServerNotConfiguredError(
                "Mock server URL is not configured yet. Set the MOCK_SERVER_URL env var."
            )
        url = f"{self._base_url}{path}"
        started = time.monotonic()
        status_code: int | None = None
        response_body: Any = None
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
                resp = await client.request(method, url, json=json, params=params)
            status_code = resp.status_code
            if resp.status_code >= 400:
                try:
                    response_body = resp.json()
                    raise MockServerError(f"HTTP {resp.status_code}", details=response_body)
                except ValueError:
                    error = f"HTTP {resp.status_code}: {resp.text}"
                    raise MockServerError(error)
            if resp.status_code == 204 or not resp.content:
                response_body = {}
                return {}
            try:
                response_body = resp.json()
            except ValueError:
                response_body = resp.text
            return response_body
        except MockServerError as exc:
            error = error or str(exc)
            raise
        finally:
            log_api_call(
                client="mock_server",
                method=method,
                url=url,
                request_body=json,
                status_code=status_code,
                response_body=response_body,
                error=error,
                duration_ms=(time.monotonic() - started) * 1000,
            )

    # ------------------------------------------------------------------ #
    # MockedResponses ("Response" docs) — the JSON payload an endpoint serves
    # ------------------------------------------------------------------ #
    async def create_response(
        self,
        api_name: str,
        response: Any,
        *,
        context: str | None = None,
        type: str | None = None,
        response_id: int | None = None,
        stage: str | None = None,
    ) -> dict:
        """POST /response — create a MockedResponses doc. Does NOT return the new
        doc's _id; call list_responses()/get_response(id) afterward to find it."""
        payload: dict[str, Any] = {"api_name": api_name, "response": response}
        if context is not None:
            payload["context"] = context
        if type is not None:
            payload["type"] = type
        if response_id is not None:
            payload["response_id"] = response_id
        if stage is not None:
            payload["stage"] = stage
        return await self._request("POST", "/response", json=payload)

    async def list_responses(self) -> Any:
        """GET /response — list every response, grouped by api_name."""
        return await self._request("GET", "/response")

    async def get_response(self, response_id: str) -> dict:
        """GET /response/:id — fetch one response doc's full detail."""
        return await self._request("GET", f"/response/{response_id}")

    async def update_response(self, response_id: str, response: Any) -> dict:
        """PUT /response/:id — overwrite the payload of an existing response doc in
        place. Any endpoint currently pointing at this doc will serve the new
        payload instantly, no restart required."""
        return await self._request(
            "PUT", f"/response/{response_id}", json={"_id": response_id, "response": response}
        )

    # ------------------------------------------------------------------ #
    # InnovationMock ("API" docs) — endpoint + method -> response doc binding
    # ------------------------------------------------------------------ #
    async def create_api(self, endpoint: str, method: str, status_code: int, condition_id: str) -> dict:
        """POST /api/ — register a brand-new mock endpoint bound to a response doc
        (via conditions._id). The mock server calls os.Exit(0) five seconds later
        so the new route can be re-registered at boot; it only comes back if the
        process is supervised (Docker restart policy, systemd, etc.)."""
        return await self._request(
            "POST",
            "/api/",
            json={
                "endpoint": endpoint,
                "method": method.upper(),
                "statusCode": status_code,
                "conditions": {"_id": condition_id},
            },
        )

    async def list_apis(self) -> Any:
        """GET /api — list all registered mock API definitions."""
        return await self._request("GET", "/api")

    async def get_api(self, api_id: str) -> dict:
        """GET /api/:id — fetch one mock API definition."""
        return await self._request("GET", f"/api/{api_id}")

    async def update_api(
        self,
        api_id: str,
        endpoint: str,
        method: str,
        status_code: int,
        condition_id: str,
    ) -> dict:
        """PUT /api/:id — update an existing mock API definition, typically to
        repoint conditions._id at a different response doc. Takes effect
        instantly, no restart required."""
        return await self._request(
            "PUT",
            f"/api/{api_id}",
            json={
                "_id": api_id,
                "endpoint": endpoint,
                "method": method.upper(),
                "statusCode": status_code,
                "conditions": {"_id": condition_id},
            },
        )

    async def wait_for_restart(
        self,
        *,
        timeout_sec: float = 30.0,
        poll_interval_sec: float = 1.0,
        initial_delay_sec: float = 5.0,
        on_progress: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """Poll GET /api until the mock server responds again after a create_api()
        call, which kills the process ~5s later. Waits initial_delay_sec first
        (the process is still alive/exiting during that window), then polls until
        it responds or timeout_sec elapses."""
        if on_progress:
            on_progress({"status": "waiting_for_shutdown", "delay_sec": initial_delay_sec})
        await asyncio.sleep(initial_delay_sec)
        deadline = time.monotonic() + timeout_sec
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                await self._request("GET", "/api", timeout=3.0)
                if on_progress:
                    on_progress({"status": "back_up"})
                return {"restarted": True}
            except Exception as exc:  # noqa: BLE001 — expected while the process is down
                last_error = str(exc)
                if on_progress:
                    on_progress({"status": "still_down", "detail": last_error})
                await asyncio.sleep(poll_interval_sec)
        raise MockServerError(
            f"Mock server did not come back up within {timeout_sec}s of restarting.",
            details={"last_error": last_error},
        )

    # ------------------------------------------------------------------ #
    # Dynamically-registered mock endpoints — the routes created via create_api()
    # ------------------------------------------------------------------ #
    async def call_mock_endpoint(
        self,
        endpoint: str,
        method: str = "GET",
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> Any:
        """Call a mock endpoint that was previously registered via create_api()
        (e.g. GET /mock/user/profile). Returns the currently-linked response's
        payload with its configured status code."""
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        return await self._request(method.upper(), endpoint, json=json, params=params)

    # ------------------------------------------------------------------ #
    # eKYC stage domain (special-cased)
    # ------------------------------------------------------------------ #
    async def upsert_ekyc_stage(self, application_reference_id: str, stage: str) -> dict:
        """POST /e-kyc/stage — set the current stage for an applicationReferenceId,
        used by the detailed-enquiry gateway endpoint below to pick the right
        MockedResponses doc (api_name: "detailedEnquiry", matching stage)."""
        return await self._request(
            "POST",
            "/e-kyc/stage",
            json={"applicationReferenceId": application_reference_id, "stage": stage},
        )

    async def get_ekyc_detailed_enquiry(self, application_reference_id: str) -> Any:
        """GET /gateway/api/neo-banking/biometric-casa/onboarding/v1/app-status/detailed/app-ref-id/:id
        — returns the MockedResponses doc for api_name "detailedEnquiry" whose
        stage matches whatever was last set via upsert_ekyc_stage()."""
        return await self._request(
            "GET",
            f"/gateway/api/neo-banking/biometric-casa/onboarding/v1/app-status/detailed/app-ref-id/{application_reference_id}",
        )

    # ------------------------------------------------------------------ #
    # Branch / deployment ops (infra-oriented, not response mocking)
    # ------------------------------------------------------------------ #
    async def update_branch_info(
        self, domain: str, switched_by: str, service: str, current_branch: str
    ) -> dict:
        """POST /branchUpdation/ — record which branch a service on a given
        mock-server domain/host is currently running."""
        return await self._request(
            "POST",
            "/branchUpdation/",
            json={
                "domain": domain,
                "switched_by": switched_by,
                "service": service,
                "current_branch": current_branch,
            },
        )

    async def promote_branch(self, domain: str, branch: str) -> dict:
        """POST /branchUpdation/promote/ — record a branch promotion for a
        mock-server domain/host."""
        return await self._request(
            "POST", "/branchUpdation/promote/", json={"domain": domain, "branch": branch}
        )

    async def deploy_mock_server(self, enable: bool, server_ip: str) -> dict:
        """POST /deploy/ — trigger or toggle a mock server deployment on the given
        server IP."""
        return await self._request(
            "POST", "/deploy/", json={"enable": enable, "serverIp": server_ip}
        )


mock_server_client = MockServerClient()
