---
name: fintech-notifications
tags: [fintech, notifications, events, memory-leak, performance, service-domain]
summary: Notification service discovery and retrieval memory experiments with overlapping
  workload sampling, cooldown, and code-correlated retained-memory evidence.
---

# fintech-notifications

Node.js/Express service backed by MySQL (Sequelize). Default port: `4004`.

## Notification retrieval memory investigation

1. Discover the requested read path and its dependencies with `code_ask`. Create a valid user
   and a controlled representative notification dataset through supported APIs; record user ID,
   notification count/size, pagination, and baseline DB state. Verify the retrieval response with
   `call_service_endpoint`; an empty or invalid-user fast path may not exercise the reported issue.
2. Follow `performance-testing` for timestamped idle baseline, **overlapping load and metrics**,
   and post-load cooldown. Repeatedly exercise the discovered read endpoint with fixed dataset
   size and equivalent request parameters. Use bounded `run_load_test` bursts and record actual
   successful requests, not just intended hit count.
3. Compare post-cooldown retained memory across repeated cycles, controlling warmup, cache state,
   container restarts, pagination, and dataset growth. Correlate available runtime diagnostics and
   logs with the read path's object lifetime: retained query results, caches, listeners, timers,
   or other references are hypotheses to inspect, not an assumed bug. Container RSS alone cannot
   confirm a leak.
4. For check-only requests, report evidence and uncertainty without source edits. For a requested
   fix, make the demonstrated targeted change, run existing tests, and `rebuild_service`; confirm
   readiness and replay matched baseline/load/cooldown trials with fresh equivalent fixtures.
   Verify response correctness as well as memory behavior so returning less data or bypassing
   work does not masquerade as a fix.

## Endpoints

Treat these routes/auth labels as hints: use the runtime-selected branch to discover the actual
method, authentication, response shape, pagination, and user fixture requirements. Keep all
fixture creation and workload traffic inside the isolated executor environment.

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Liveness check |
| GET | `/health/ready` | none | Readiness check (verifies DB connectivity) |
| POST | `/notifications` | none (internal, service-to-service) | Create a notification; called by fintech-ledger/fintech-payments |
| GET | `/notification/api/v1/user/:userId` | none | List notifications for a user |
| GET | `/notification/api/v1/user/:userId/unread-count` | none | Get a user's unread notification count |
| PATCH | `/notification/api/v1/:id/read` | none | Mark a notification as read |
