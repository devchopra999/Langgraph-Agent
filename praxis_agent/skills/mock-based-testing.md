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
`pointsTo="mock-server"` endpoint. This is the preferred path when the wrapper already calls its
dependency through the orchestrator: it applies on the next request with no restart.

The mock server stores two kinds of docs in MongoDB:
- **MockedResponses** ("Response" docs) — the actual JSON payload an endpoint serves.
- **InnovationMock** ("API" docs) — an `endpoint` + `method` bound to a Response doc via
  `conditions._id`.

## Steps

1. **Retain the contract and discover the wrapper.** Preserve supplied contract text and the
   runtime-selected branch. Use `code_ask` and app env discovery to identify the wrapper operation,
   dependency URL/path/method, request/response schema, authentication/signing, and downstream
   effects. Construct a coverage matrix: case, exact dependency status/body, valid wrapper request,
   expected wrapper status/body and DB effects, and evidence required. Derive expectations from
   the contract, not from current buggy behavior. Separate exploratory out-of-contract cases.
   Do not guess missing credentials, signature algorithms, response envelopes, or expected errors.
2. **Discover routing before changing anything.** Follow the `orchestrator-routing` skill's
   discovery step (`get_orchestrator_status`, then `list_orchestrator_routes`/
   `get_orchestrator_route`) and relevant env values. There is no read tool for aliases;
   `update_orchestrator_aliases` merges rather than replaces, so record only the hostnames you
   introduce so they can be deleted afterward with `delete_orchestrator_alias`.
   Not every service is orchestrated: fintech clients can call dependencies directly. Inspect
   code/config for the actual path and headers before assuming a route intercepts traffic.
3. **Check shared global ownership.** List existing mock APIs/responses before creation; match
   exact path/method and inspect response bindings. Record API ID, status, response ID and payload,
   conditions, and other supported fields needed for restoration. Never overwrite/delete an
   unrelated binding or shared response document. Reuse compatible state unchanged; change only
   owned or explicitly coordinated state, recording restoration data first. Caller-specific
   routing does not isolate a globally shared mock path. If ownership or concurrent use conflicts,
   report a genuine blocker rather than changing the contractual path or disrupting other users.
4. **Create an exact response for each representable case.** Use `create_mock_response` with a
   uniquely identifiable owned `api_name`/`context` and the contract JSON object in `response`.
   The create call does **not** return the new doc's `_id`: immediately inspect
   `list_mock_responses` (or `get_mock_response` for a known ID), using actual returned shapes
   and metadata to resolve the exact new document. Do not assume the newest/first list entry
   belongs to this run. Preserve exact types, fields, nesting, nulls, and omissions.
5. **Register or select the API binding.** For an absent path/method, use `create_mock_api`
   with exact `endpoint`, `method`, `status_code`, and `response_id`. Discover its API ID using
   the actual returned/listed API records, not a guessed ID. **New registration causes the mock
   process to exit about five seconds later** so Gin can register routes at boot. Recovery
   requires its existing supervisor (Docker restart policy, systemd, etc.).
   Call `wait_for_mock_server_restart` immediately after creation; an early successful health
   response before the delayed exit is not sufficient. The wait requires two health observations
   spanning the roughly five-second boundary, or an observed outage followed by recovery.
   Retain its `restartObserved` boolean and `endpointVerificationRequired` result: health alone
   does not prove a new route was registered. Check the actual mocked endpoint's exact status/body
   with `call_mock_endpoint` before the wrapper trial, even if no outage was observed.
   If recovery or endpoint verification fails, report infrastructure
   blockage; never provision another mock server. Existing compatible bindings need no registration.
6. **Route the isolated caller to the SAME global mock.** For an already-proxied caller, use
   `set_orchestrator_route(environment_id, source_service="<discovered-caller>",
   destination_service="<discovered-logical-dependency>", points_to="mock-server")`.
   The executor resolves this symbolic value to the authoritative global `MOCK_SERVER_URL`;
   never substitute an in-environment mock instance or invent a write value from a resolved URL.
   Prefer the exact caller route; wildcard changes require intentionally scoped coverage.
   For a direct HTTP hostname caller, use
   `update_orchestrator_aliases(environment_id, aliases={"<discovered-hostname>":
   "<discovered-logical-dependency>"})` for the documented hostname/header injector, and use
   the same exact mock route. Preserve unrelated mappings according to the update API's semantics;
   inspect its returned `aliases` to verify the effective mapping.
   Do not assume route registration alone intercepts direct calls. For HTTPS, an HTTP alias is
   not TLS interception: use a discovered, supported isolated base-URL/scheme configuration and
   restart if needed, then prove the configured path uses the proxy. If no supported configuration
   exists, report the limitation; a check-only task does not authorize client source edits.
7. **Sanity-check and prove delivery.** Use `call_mock_endpoint` with the exact method/path to
   verify status and unmodified body. Before the measured wrapper trigger, ensure no real
   third-party traffic can escape the isolated setup. Prepare valid auth/signatures and fresh
   fixture IDs, then use `call_service_endpoint` for the actual wrapper operation. Demonstrate
   that this call reached the configured global mock using available request evidence or a
   uniquely identifiable, contract-valid response. A direct mock probe alone proves neither
   interception nor wrapper behavior; treat unproven routing as inconclusive.
8. **Verify each case, then switch safely.** Preserve wrapper responses, logs, and pre/post
   service-owned DB evidence, including downstream side effects and failure handling.
   On owned state, `update_mock_api(api_id, endpoint, method, status_code, new_response_id)`
   switches the response/status without a restart. `update_mock_response` is appropriate only
   for an owned, unshared response with its old payload recorded. Do not mutate a response used
   by unrelated bindings. Sanity-check each switch before repeating the wrapper trial with fresh
   equivalent fixtures; avoid consumed payment references masking the code path.
9. **Restore supported mutations; retain new mock definitions.** Restore existing coordinated
   binding/status changes only through `update_mock_api`; restore an owned existing response
   payload with `update_mock_response` when applicable. Restore alias entries and env values
   exactly; restart after env restoration when required. Restore
   an existing route using a valid symbolic mapping, not a blindly copied resolved URL.
   If no exact override existed, use `delete_orchestrator_route` to remove only the introduced
   override and expose the original fallback. Use
   `delete_orchestrator_alias(environment_id, host="<introduced-hostname>")` only for introduced
   owned aliases; otherwise restore their original mappings with `update_orchestrator_aliases`.
   There is **no documented or implemented global mock DELETE API** for API or response
   definitions. Retain newly created definitions and report their owned IDs, methods, and paths;
   never invent delete calls or claim all mocks were removed. If removal is required, report the
   unsupported operation rather than deleting records through another channel. Preserve unrelated
   records. Re-read relevant state to verify supported restoration and report cleanup failures
   separately from intentionally retained new definitions.
10. **Report actual coverage.** Show expected/actual wrapper results and side effects per case,
    evidence of mock delivery, and passed/failed/unsupported/blocked cases separately. Cover all
    supplied representable cases, refining trials from evidence rather than an arbitrary scenario
    cap. A check-only task must not edit source; requested fixes follow `production-issue-repro`,
    including `rebuild_service` and comparable replay. Never claim all contract cases passed
    when required cases could not be represented or routing remained unproven.

## Supported response format and explicit limits

The known management API supports a JSON **object** body and configured HTTP status.
`create_mock_response` requires an object in `response`. Do **not** wrap a required top-level
array as `{"data": [...]}` or string as `{"message": "..."}`: that changes the contract.
Top-level arrays, strings, other primitives, raw/invalid JSON, and empty/non-JSON bodies are
unsupported unless the actual API explicitly supports them. Missing or wrong-typed fields inside
an object can represent contract-supported malformed-body cases; invalid JSON transport cannot.
Do not fabricate response-header, delay, timeout, disconnect, or raw-body options. If a case
depends on those capabilities, mark it unsupported with the missing capability rather than
substituting a different status/body and claiming equivalent coverage. Only extend coverage
after verifying real documented support.
