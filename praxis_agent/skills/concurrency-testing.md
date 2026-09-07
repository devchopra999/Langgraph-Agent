---
name: concurrency-testing
tags: [concurrency, race-condition, load, sql, locking]
summary: Reusable synchronized concurrency experiments with discovered valid fixtures,
  mixed payloads, database invariants, and comparable regression trials.
---

# Concurrency testing playbook

Use this when the bug/hypothesis involves a race condition, double-processing, lost update,
or lock contention under concurrent requests.

## Steps

1. **Discover the selected branch.** Use `code_ask` to identify endpoint methods, payloads,
   auth/signing, transaction boundaries, SQL lock acquisition, uniqueness constraints, retry
   behavior, and downstream side effects. Do not infer the defect or fix from a scenario label.
   All setup, mutation, and traffic must stay in the isolated executor environment.
2. **Prepare valid fixtures and a serial control.** Create authenticated users, sufficiently
   funded wallets, pending payments, or other prerequisites using discovered service APIs.
   Validate a representative request using `call_service_endpoint`. Auth/validation failures
   are not evidence of the target race. Snapshot relevant rows with `query_database` and define
   serial-equivalent invariants, including effects in downstream service-owned databases.
3. **Choose the trigger.** Use `run_load_test` for identical concurrent payloads when its
   aggregate evidence is sufficient. Use `execute_concurrent_requests` for mixed requests,
   such as opposite-direction transfers, or synchronized per-request evidence. It uses a
   bounded Python harness in the executor toolbox, not the local host. Discover tool argument
   schemas before calling. Its request list contains
   `{service, endpoint, method, headers, body}` entries; top-level arguments are
   `environment_id`, `requests`, `concurrency` (default 2), `rounds` (default 1), and `timeout`
   (default 10 seconds). Supply discovered service-relative endpoints and actual auth/payloads.
   If composing an executor harness is necessary, use argv
   `["python3", "-c", "<script text>"]`, never shell strings or background shell loops.
4. **Bound and synchronize.** Use explicit worker, request, round, per-request timeout, and
   overall execution bounds. The harness allows at most 32 workers, 100 request entries,
   100 rounds, 1,000 total requests, and a 240-second worst-case workload; these are per-operation
   safety limits, not a total investigation budget. Synchronize starts for each burst; a barrier
   must not wait for more participants than the available workers. Retain request identity, payload identity,
   start/end timestamps, status/body, latency, and transport errors. Verify overlap, not merely
   that requests were submitted together. Adapt subsequent bounded rounds to evidence and
   service capacity; there is no arbitrary total scenario/attempt budget.
5. **Collect evidence even on failures.** Compare DB changes with the expected serial result
   after in-flight work settles within a bounded observation window. Collect logs and available
   lock/deadlock evidence. A 500 alone does not establish deadlock; 2xx responses alone do not
   establish correct accounting. Reconcile uncertain side effects before retries.
6. **Replay the actual regression.** Pin the failing request mix and invariants. For an
   explicitly requested fix only, diagnose and edit the demonstrated cause, run existing
   targeted tests, then `rebuild_service` and check readiness. Replay unchanged workload
   semantics against fresh equivalent fixtures, plus serial and validation controls.
   Do not restart the original branch or reuse exhausted state as apparent verification.
   A check-only request must not edit source. Report reproduced, verified, inconclusive, or
   blocked based on evidence, including cleanup failures.

## Domain experiments

- **Opposite-direction transfers:** follow `fintech-ledger`. Include A-to-B and B-to-A in
  the same synchronized burst, with correct credentials per direction. Assert conserved funds,
  correct paired entries, and bounded progress, not just an absence of HTTP errors.
- **Duplicate payment callbacks:** follow `fintech-payments`. Reuse the same discovered
  payment/provider reference *within* a burst and sequential redelivery, but create a fresh
  equivalent payment for each independent before/after trial. Verify one logical success
  and one ledger credit across services; a unique local row is not sufficient.
