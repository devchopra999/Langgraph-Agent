---
name: concurrency-testing
tags: [concurrency, race-condition, load, sql, locking]
summary: How to design and run a concurrency test against a service — finding the relevant
  SQL/queries, writing a small script, and executing it in parallel via execute_command.
---

# Concurrency testing playbook

Use this when the bug/hypothesis involves a race condition, double-processing, lost update,
or lock contention under concurrent requests.

## Steps

1. **Find the relevant code path and queries.** Use `code_ask` (e.g. "what SQL queries run
   when this endpoint is called, and are they wrapped in a transaction?") to understand the
   read-modify-write sequence and whether row locking (`SELECT ... FOR UPDATE`), unique
   constraints, or optimistic locking (version column) is used.
2. **Capture baseline state.** Use `query_database` to snapshot the relevant rows before the
   test (e.g. an account balance, an idempotency key table, an inventory count).
3. **Write a small concurrency script.** There is no dedicated "run N parallel requests" tool
   — compose one from `execute_command`: generate a short script (e.g. python with
   `concurrent.futures.ThreadPoolExecutor`, or a bash loop backgrounding curl calls with `&`
   and `wait`) that fires the same request N times in parallel against the service's own
   HTTP endpoint from inside its container (or a suitable client container). Pass it as the
   argv list to `execute_command`, e.g.
   `["python3", "-c", "<script text>"]` or write it to a temp file first with a `sh -c`-free
   argv sequence.
4. **Vary concurrency level across iterations** (e.g. 2, 10, 50 parallel requests) if the
   first level doesn't reproduce the race — this is a natural fit for the scenario-iteration
   loop (`run_scenario_loop`) rather than one-shot.
5. **Re-query the database** after each run and diff against the expected serial-equivalent
   result (e.g. balance decremented exactly once per valid request, no duplicate rows for the
   same idempotency key).
6. **Check logs** for exceptions, deadlock errors, or retry logic firing.
7. If a race is confirmed, use `code_ask`/`code_edit` to add the missing lock/transaction/
   unique-constraint handling, then rebuild (`start_service` with the branch) and re-run the
   same concurrency script to verify the fix holds under the same load.
