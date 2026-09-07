---
name: production-issue-repro
tags: [reproduction, repro, incident, hotfix, configuration]
summary: Playbook for reproducing a reported production bug in an isolated environment, gathering
  evidence, and verifying an explicitly requested fix.
---

# Production issue reproduction playbook

Use this for "reproduce this reported bug" or "quick hotfix testing" requests.

## Steps

1. **Scope and isolate.** Select the minimal executor catalog application services and use
   `create_environment`. Provisioning, requests, fixtures, commands, and edits belong in that
   isolated environment, never real production or host-side service access. Do not request the
   global Mock Server or standalone databases. Select branches from runtime input/discovery,
   not incident labels or demo defaults; use `start_service(..., branch=...)` for initial checkout.
2. **Discover adaptively.** Inspect readiness, exact internal endpoints, app env, and
   service-owned database inventory. Use `code_ask` to discover the selected branch's endpoint
   methods, schemas, authentication/signing, dependencies, and existing test commands.
   Playbook endpoint tables are hints, not authoritative contracts. Start discovered application
   dependencies as needed. Observe each prerequisite result before constructing dependent calls;
   do not guess tokens, fixture IDs, table names, or payloads.
3. **Isolate external dependencies.** Follow `mock-based-testing` and `orchestrator-routing`.
   Not every service uses the
   orchestrator: fintech callers can make direct HTTP calls. Discover the actual client path.
   A caller-specific `target="mock-server"` routes only proxied traffic to the authoritative
   global server; direct clients require supported alias/configuration setup and proof of routing.
4. **Prepare a trial.** Separate one-time checkout/routing from repeatable fixture setup.
   Prefer `call_service_endpoint` for isolated auth and fixture APIs; use controlled database
   seeding only against discovered service-owned databases when needed. Record valid credentials,
   preconditions, unique fixture handles, database baselines, and explicit failure predicates.
   Validate a serial control before using load or concurrency.
5. **Trigger and observe.** Use `call_service_endpoint`, `run_load_test`, or
   `execute_concurrent_requests` as appropriate; use bounded executor commands for other triggers.
   Preserve response bodies/statuses, timestamps, exit codes, logs, DB changes, and relevant
   overlapping metrics even when the request fails. An application 500 can reproduce the defect;
   a tool success alone cannot prove it. Reconcile uncertain non-idempotent outcomes before retry.
6. **Confirm and diagnose.** Compare evidence with the reported symptom before editing.
   Pin the actual failing scenario and baseline independently of later controls. Correlate
   runtime evidence with the branch code via `code_ask`; do not assume a predetermined cause.
   Refine setup or hypotheses when observations differ, preserving what each trial establishes.
7. **Respect intent.** Check/test/reproduce-only requests do not authorize source edits.
   For an explicitly requested fix, use `code_edit` for the demonstrated cause and relevant
   regression tests, then run the repository's discovered targeted tests through the executor.
   No additional approval is needed for already authorized isolated remediation.
8. **Rebuild edited source.** Use `rebuild_service`: the executor API is
   `POST /environments/:id/services/:service/rebuild` with **no request body**, followed by
   polling the returned job. Check readiness and that edited behavior is deployed. Never use
   `start_service(branch=...)` after edits: a checkout can discard them. `restart_service` is
   appropriate for supported env-only changes, not a substitute for a source rebuild.
9. **Replay comparably.** Re-run the pinned failing workload with fresh equivalent fixtures or
   a safely reset isolated baseline: same semantics, balances, sizes, concurrency, and assertions,
   but new user/payment/reference IDs where old ones were consumed. Do not replay checkout or
   mistake a previously completed payment's no-op for a fix. Include adjacent regression controls.
10. **Assess honestly.** Compare original failure predicates, logs, database invariants, and
    resource evidence before/after. A successful edit/build is not verification. Continue with
    evidence-based next actions rather than an arbitrary scenario/remediation budget; keep every
    request, load burst, command, and poll bounded. Recover discoverable prerequisites autonomously.
    If no safe progress remains, report the genuine blocker or inconclusive result, not success
    or a request for permission for "one more attempt." Retain the environment, source diff,
    and evidence; restore owned temporary routing/mock/env mutations and report cleanup failures.
