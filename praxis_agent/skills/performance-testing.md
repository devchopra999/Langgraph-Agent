---
name: performance-testing
tags: [performance, metrics, cpu, memory, bottleneck, soak]
summary: How to interpret get_service_metrics/get_environment_metrics time series to find
  CPU/memory bottlenecks or leaks under load.
---

# Performance testing playbook

Use this when the goal is to find a bottleneck, verify a fix reduces resource usage, or
detect a memory leak.

## Steps

1. **Establish load.** Use `run_load_test` for bounded concurrent requests to a discovered
   service-relative endpoint. Set the request method, headers/body, hit count, and per-request
   timeout (maximum 60 seconds). Its completed result records success/failure counts,
   status-code distribution, and latency min/max/average; repeat the same request after a fix for
   a comparable result.
2. **Sample metrics across the whole environment**, not just one service —
   `get_environment_metrics(environment_id, duration=50, interval=5)` (max duration 120s,
   min interval 1s per call; call it multiple times back-to-back for a longer soak profile)
   so you can compare services directly, e.g. "app CPU climbed from 12% to 98% while the
   database stayed under 40% — the app itself is the bottleneck, not the DB."
3. **For a suspected memory leak**, run several back-to-back sampling windows over a longer
   period and look for `memoryUsageBytes` that keeps climbing and never plateaus/drops,
   rather than one that rises then stabilizes under steady load (normal).
4. **Correlate with logs** (`get_logs`) for GC pauses, thread pool exhaustion, or connection
   pool warnings around the same time window.
5. **After an explicitly requested code fix** (`code_edit` + documented `start_service` or
   `restart_service`), repeat the exact same load + sampling window and compare the new time
   series against the earlier one to confirm the improvement, rather than eyeballing a single
   snapshot.
6. end the scenario with a summary of the before/after metrics and logs, and whether the fix
   improved the bottleneck or leak.
