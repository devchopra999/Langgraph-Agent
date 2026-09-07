---
name: mock-based-testing
tags: [mock, mock-server, fault-injection, contract-testing, dependency-testing, ekyc]
summary: Step-by-step playbook for using the real Mock Server API (MockedResponses +
  InnovationMock docs) to make a service's outbound dependency return different
  canned scenarios (success, error, malformed) without depending on the real third
  party.
---

# Mock-based testing playbook

Use this when you need to verify how a service behaves against a *dependency* it calls
over HTTP (e.g. a third-party API like Axis), without depending on that real third
party.

**The Mock Server is externally managed on its own domain, not provisioned by the executor.**
Never pass it to `create_environment`/`start_service`; manage its responses and APIs only through
the existing mock-server tools, none of which takes an `environment_id`. The executor's
orchestrator can nevertheless route an in-environment caller to its registered
`target="mock-server"` endpoint. This is the preferred path when the wrapper already calls its
dependency through the orchestrator: it applies on the next request with no restart.

The mock server stores two kinds of docs in MongoDB:
- **MockedResponses** ("Response" docs) — the actual JSON payload an endpoint serves.
- **InnovationMock** ("API" docs) — an `endpoint` + `method` bound to a Response doc via
  `conditions._id`.

## Steps

1. **Discover routing before changing anything.** Use `get_orchestrator_status` to confirm the
   environment orchestrator is healthy and `list_orchestrator_routes` to record the current
   targets. Use `code_ask` to identify the wrapper's dependency call, its logical destination,
   and whether it sends requests through `ORCHESTRATOR_URL` with `x-to-service`. Also inspect its
   current env with `get_service_env`. Never guess a destination name or overwrite a route without
   recording its original target.
2. **Create a response per scenario you want to test** with `create_mock_response`, e.g.:
   - `api_name="axisPaymentCallback", context="success", response={...200 body...}`
   - `api_name="axisPaymentCallback", context="failure", response={"error": "internal"}`
   - `api_name="axisPaymentCallback", context="malformed", response={...missing fields...}`
   Note the create call does **not** return the new doc's `_id` — immediately call
   `list_mock_responses` (or `get_mock_response` if you already know it) to find the
   `_id`s you'll need next.
3. **If this endpoint isn't registered with the mock server yet**, call `create_mock_api`
   with the target `endpoint`, `method`, `status_code`, and the `response_id` (Response
   doc `_id`) for your first scenario (usually "success"). This registers the endpoint,
   but **the mock server process exits ~5s later** so Gin can re-register routes at
   boot — it only comes back if a supervisor (Docker restart policy, systemd, etc.) is in
   place. Call `wait_for_mock_server_restart` right after to block until it's responsive
   again before doing anything else with it. If the endpoint is already registered,
   skip straight to step 5.
4. **Route the wrapper to the Mock Server.** If the wrapper uses the orchestrator, call
   `set_orchestrator_route` with the exact caller and logical destination:
   `set_orchestrator_route(environment_id, from_service="<wrapper>",
   to_service="<logical-dependency>", target="mock-server")`. This is caller-specific: it does
   not affect other services that call the same destination. Use `from_service="*"` only when
   the scenario intentionally covers every caller. The route is effective on the next proxied
   request; no restart is needed.

   If the wrapper does **not** use the orchestrator, use the dependency URL discovered in step 1:
   merge the external Mock Server domain with `update_service_env` (or update one key with
   `set_env_var`), then `restart_service`. Do not use a route as a substitute for a direct,
   hardcoded HTTP client that never calls the orchestrator.
5. **Sanity-check the mock is live** with `call_mock_endpoint` (same endpoint/method) and
   confirm it returns the expected scenario payload/status.
6. **Trigger the code path** via `execute_command` (e.g. curl the service's own endpoint
   that triggers the downstream call, or run whatever reproduces the transaction).
7. **Verify** via `get_logs` (look for the expected error handling / log lines),
   `query_database` (did the transaction land in the expected state — success/failed/
   retried), and optionally `get_service_metrics` if you're also checking for retry
   storms/CPU spikes.
8. **Switch to the next scenario — instantly, no restart:**
   - `update_mock_response(response_id, new_payload)` — overwrite the same Response doc
     in place (simplest if you don't need the old payload anymore), **or**
   - `create_mock_response(...)` for the new scenario, then
     `update_mock_api(api_id, endpoint, method, status_code, new_response_id)` to repoint
     `conditions._id` at it (keeps every scenario's payload around for later reuse).
   Repeat from step 5 for each scenario.
9. **Restore routing when needed.** Reapply the caller-specific target recorded in step 1 after
   the experiment. If the original path used an env value instead, merge that value back and
   restart the wrapper. Keep the mock data available unless the developer requests its removal.
10. Aggregate pass/fail per scenario before concluding whether the service handles the
   dependency's failure modes correctly.

## Response format
`create_mock_response` requires an object in its `response` field. Wrap arrays as
`{"data": [...]}` and strings as `{"message": "..."}`.
