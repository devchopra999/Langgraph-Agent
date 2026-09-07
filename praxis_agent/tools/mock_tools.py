"""Tools for coordinating with the real Mock Server: creating/switching MockedResponses
docs, registering/updating InnovationMock API definitions, calling the live mock
endpoints, and driving the eKYC/branch/deploy ops endpoints.

Typical loop for a brand-new mocked endpoint:
  create_mock_response (grab api_name/context to identify it) -> list_mock_responses or
  get_mock_response (to find the new doc's _id, since create doesn't return it) ->
  create_mock_api (registers endpoint+method, points conditions._id at that response doc;
  this restarts the mock server process ~5s later) -> wait_for_mock_server_restart ->
  call_mock_endpoint to exercise it -> update_service_env/set_env_var + restart_service on the
  dependent service to point it at the mock server -> execute_command/get_logs/
  query_database to verify behavior.

To switch which response an *already-registered* endpoint returns (no restart needed):
  either update_mock_response (same doc, new payload) or create_mock_response +
  update_mock_api (repoint conditions._id at the new doc).
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from praxis_agent.clients.mock_server_client import mock_server_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("create_mock_response")
async def create_mock_response(
    api_name: str,
    response: Any,
    context: Optional[str] = None,
    type: Optional[str] = None,
    response_id: Optional[int] = None,
    stage: Optional[str] = None,
) -> dict:
    """Create a MockedResponses doc (POST /response) — the JSON payload that a mock endpoint
    will serve. `api_name` groups related responses (e.g. "getUserProfile"); `context`
    typically distinguishes scenarios under that api_name (e.g. "success"/"failure").
    `response` is the actual JSON body to return. Only returns {"isSuccessful": true} — the
    new doc's _id is NOT returned, so call list_mock_responses() or search by api_name
    afterward to find it before using it in create_mock_api/update_mock_api."""
    return await mock_server_client.create_response(
        api_name, response, context=context, type=type, response_id=response_id, stage=stage
    )


@tool
@instrumented("list_mock_responses")
async def list_mock_responses() -> Any:
    """List every MockedResponses doc (GET /response), grouped by api_name. Use this to
    discover an existing response's _id before wiring it into create_mock_api/update_mock_api,
    or to check what scenarios already exist for an api_name before creating duplicates."""
    return await mock_server_client.list_responses()


@tool
@instrumented("get_mock_response")
async def get_mock_response(response_id: str) -> dict:
    """Get the full detail (api_name, context, response payload, etc.) of one MockedResponses
    doc by id (GET /response/:id)."""
    return await mock_server_client.get_response(response_id)


@tool
@instrumented("update_mock_response")
async def update_mock_response(response_id: str, response: Any) -> dict:
    """Overwrite the JSON payload of an existing MockedResponses doc in place
    (PUT /response/:id). Any mock endpoint whose conditions._id points at this doc will start
    serving the new payload instantly — no server restart needed. This is the fastest way to
    switch an already-registered endpoint's behavior (e.g. success -> error) when you don't
    need to keep the old payload around."""
    return await mock_server_client.update_response(response_id, response)


@tool
@instrumented("create_mock_api")
async def create_mock_api(endpoint: str, method: str, status_code: int, response_id: str) -> dict:
    """Register a brand-new mock API (POST /api/): binds `endpoint` + `method` to the
    MockedResponses doc identified by `response_id` (used as conditions._id), returned with
    `status_code` when called. WARNING: the mock server process calls os.Exit(0) five seconds
    after this responds, since Gin only registers routes once at boot — the new endpoint only
    becomes callable once a supervisor (Docker restart policy, systemd, etc.) restarts the
    process. Call wait_for_mock_server_restart() right after this to block until it's back up
    before calling call_mock_endpoint()."""
    return await mock_server_client.create_api(endpoint, method, status_code, response_id)


@tool
@instrumented("list_mock_apis")
async def list_mock_apis() -> Any:
    """List all registered mock API definitions (GET /api) — endpoint, method, statusCode,
    and the response doc (conditions._id) each is currently wired to."""
    return await mock_server_client.list_apis()


@tool
@instrumented("get_mock_api")
async def get_mock_api(api_id: str) -> dict:
    """Get one mock API definition by id (GET /api/:id)."""
    return await mock_server_client.get_api(api_id)


@tool
@instrumented("update_mock_api")
async def update_mock_api(
    api_id: str, endpoint: str, method: str, status_code: int, response_id: str
) -> dict:
    """Update an existing mock API definition (PUT /api/:id), typically to repoint
    conditions._id at a different MockedResponses doc (e.g. one created via
    create_mock_response for a new scenario). Must resend the full definition
    (endpoint/method/status_code), not just the changed field. Takes effect instantly — no
    server restart required, unlike create_mock_api."""
    return await mock_server_client.update_api(api_id, endpoint, method, status_code, response_id)


@tool
@instrumented("wait_for_mock_server_restart")
async def wait_for_mock_server_restart(
    timeout_sec: float = 30.0, on_progress=None
) -> dict:
    """Block until the mock server is responsive again after a create_mock_api() call, which
    kills the process ~5s later for its new route to take effect on reboot. Call this
    immediately after create_mock_api() and before calling the newly-registered endpoint.
    Raises if the server doesn't come back within timeout_sec (e.g. no restart supervisor is
    configured)."""
    return await mock_server_client.wait_for_restart(timeout_sec=timeout_sec, on_progress=on_progress)


@tool
@instrumented("call_mock_endpoint")
async def call_mock_endpoint(
    endpoint: str, method: str = "GET", body: Optional[dict] = None, params: Optional[dict] = None
) -> Any:
    """Call a mock endpoint previously registered via create_mock_api (e.g. GET
    /mock/user/profile). Returns whatever payload/status the endpoint's currently-linked
    MockedResponses doc is configured with — use this to verify a scenario is live, or as the
    "dependency" a service under test should be pointed at."""
    return await mock_server_client.call_mock_endpoint(endpoint, method, json=body, params=params)


@tool
@instrumented("upsert_ekyc_stage")
async def upsert_ekyc_stage(application_reference_id: str, stage: str) -> dict:
    """Set the current eKYC stage for an applicationReferenceId (POST /e-kyc/stage). Later
    calls to get_ekyc_detailed_enquiry() for the same applicationReferenceId will resolve to
    whichever MockedResponses doc (api_name: "detailedEnquiry") matches this stage."""
    return await mock_server_client.upsert_ekyc_stage(application_reference_id, stage)


@tool
@instrumented("get_ekyc_detailed_enquiry")
async def get_ekyc_detailed_enquiry(application_reference_id: str) -> Any:
    """Look up the detailed-enquiry status for an applicationReferenceId (GET
    /gateway/api/neo-banking/biometric-casa/onboarding/v1/app-status/detailed/app-ref-id/:id).
    Returns the MockedResponses doc (api_name: "detailedEnquiry") whose stage matches whatever
    was last set via upsert_ekyc_stage() for this applicationReferenceId."""
    return await mock_server_client.get_ekyc_detailed_enquiry(application_reference_id)


@tool
@instrumented("update_mock_branch_info")
async def update_mock_branch_info(
    domain: str, switched_by: str, service: str, current_branch: str
) -> dict:
    """Record which branch a service on a given mock-server domain/host is currently running
    (POST /branchUpdation/) — infra bookkeeping, not response mocking."""
    return await mock_server_client.update_branch_info(domain, switched_by, service, current_branch)


@tool
@instrumented("promote_mock_branch")
async def promote_mock_branch(domain: str, branch: str) -> dict:
    """Record a branch promotion for a mock-server domain/host (POST /branchUpdation/promote/)
    — infra bookkeeping, not response mocking."""
    return await mock_server_client.promote_branch(domain, branch)


@tool
@instrumented("deploy_mock_server")
async def deploy_mock_server(enable: bool, server_ip: str) -> dict:
    """Trigger or toggle a mock server deployment on the given server IP
    (POST /deploy/) — infra ops, not response mocking."""
    return await mock_server_client.deploy_mock_server(enable, server_ip)
