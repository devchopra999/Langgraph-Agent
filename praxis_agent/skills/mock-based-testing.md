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

**The Mock Server is a standalone service on its own domain, not part of a Praxis Lens
environment.** Never pass it to `create_environment`/`start_service` and never make it an
orchestrator route target. Use the existing `create_mock_response`/`create_mock_api`/
`call_mock_endpoint` tools directly; none takes an `environment_id`. The executor environment is
only for the wrapper or service under test. Point that service at the external Mock Server through
its own discovered env/config setting, then restart it.

The mock server stores two kinds of docs in MongoDB:
- **MockedResponses** ("Response" docs) — the actual JSON payload an endpoint serves.
- **InnovationMock** ("API" docs) — an `endpoint` + `method` bound to a Response doc via
  `conditions._id`.

## Steps

1. **Identify the dependency call site.** Use `code_ask` on the service to find where the
   outbound call is made and what env var / config / Vault path controls its base URL.
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
4. **Point the service at the external Mock Server.** Use `get_service_env` and `code_ask` to
   find the wrapper's dependency URL setting, then merge its configured Mock Server domain with
   `update_service_env` (or update one key with `set_env_var`). Restart the wrapper service so
   it picks up the change. This is configuration, not an orchestrator-route operation.
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
9. Aggregate pass/fail per scenario before concluding whether the service handles the
    dependency's failure modes correctly.

## Response format
1. **`create_mock_response`** you must send an object in it's response key, mock server doesn't work with arrays or strings. If you need to return an array, wrap it in an object like `{"data": [...]}`. If you need to return a string, wrap it in an object like `{"message": "..."}`.
