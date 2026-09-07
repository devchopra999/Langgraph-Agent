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

1. **Discover and validate.** Inspect the runtime-selected branch's endpoint, auth, payload,
   pagination, data volume, and dependencies. Prepare isolated representative fixtures and
   confirm a valid response with `call_service_endpoint` before load. Record container identity,
   readiness, resource limits, restart count, and the expected workload; do not measure a stream
   of authentication failures as the intended operation.
2. **Measure an idle baseline.** After any documented warmup, sample
   `get_service_metrics` and, when useful, `get_environment_metrics` to distinguish application
   growth from database/neighbor activity. Record sample timestamps and actual units.
   Metrics windows are bounded (maximum duration 120 seconds, minimum interval 1 second);
   use successive windows for a longer profile, noting gaps.
3. **Overlap workload and sampling.** Run `run_load_test` and the metrics sampler as independent
   concurrent executor operations. Start sampling before or with load and retain both timelines.
   Waiting for load to finish and then sampling is **not** a load-phase measurement. Verify the
   returned timestamps actually overlap; if orchestration did not overlap them, repeat a valid
   measured trial or report that limitation. Use discovered method, headers/body, bounded hits
   and concurrency, and per-request timeout (maximum 60 seconds). Preserve completed request
   counts, success/failure status distribution, latency, and workload duration.
4. **Measure cooldown and repeat.** After load stops, keep sampling through a bounded cooldown
   with no intentional workload. Repeat comparable baseline/load/cooldown cycles, recording
   completed operations and retained memory after each cycle. Compare growth per successful
   operation and post-cooldown levels; distinguish transient allocation, cache warmup/plateaus,
   allocator high-water marks, legitimate dataset growth, and container restarts/OOMs.
   Adjust later bounded workloads based on observed signal and safety, not a fixed attempt cap.
5. **Correlate memory with code.** Rising container RSS or `memoryUsageBytes` alone does not
   prove a leak. Use `get_logs` for GC, pool exhaustion, and OOM/restart evidence, and `code_ask`
   to inspect the exercised branch path for retained references, unbounded caches/collections,
   listeners, timers, or unclosed resources. Use existing runtime heap/allocation diagnostics
   when available and safe; do not fabricate them. Report inconclusive if retained growth and
   a causal code path cannot be distinguished from normal retention with available evidence.
6. **Verify only authorized fixes.** Check-only requests stop at evidence and diagnosis,
   without `code_edit`. If a fix was explicitly requested, make the targeted change and run
   existing tests, then `rebuild_service`, check readiness, and repeat the same measured workload
   and cooldown with fresh equivalent fixtures, matching warmup and resource settings.
   Do not claim an improvement from fewer successful operations, an intervening restart, or
   a single lower RSS snapshot.
7. **Report the comparison.** Include baseline/load/cooldown timestamps and demonstrated
   overlap, workload outcomes, retained-memory trends, logs and code evidence, and any missing
   diagnostics or confounders. State whether the leak was reproduced and whether replay verified
   a requested fix, rather than equating successful tool execution with success.
