---
name: production-issue-repro
tags: [reproduction, repro, incident, hotfix, snapshot, vault]
summary: Playbook for reproducing a reported production bug in an isolated environment using
  a database snapshot, Vault config, and (if relevant) a mocked dependency — then verifying a
  fix removes the failure.
---

# Production issue reproduction playbook

Use this for "reproduce this reported bug" or "quick hotfix testing" requests.

## Steps

1. **Scope the services.** From the bug description, decide the minimal set of catalog
   services needed (don't start everything — start time and noise both matter). Check
   dependencies: `mob`/`edi` need `vault` (auto-resolved by `start_service`/`create_environment`).
2. **Create the environment** with `create_environment`, restoring the closest-matching
   `database_snapshot` (or per-service `databases` with snapshots) so the data conditions that
   trigger the bug are present — an empty database frequently fails to reproduce
   state-dependent bugs.
3. **If the bug involves an external dependency** (e.g. a third-party API returning something
   unexpected), see the `mock-based-testing` skill — mock the dependency rather than hitting
   the real one.
4. **Attach the relevant repo/branch/commit.** If the developer already has a fix branch or a
   specific commit that reproduces the issue, use `start_service(..., branch=...)` or
   `attach_repository` with the exact commit for deterministic reproduction.
5. **Trigger the failing scenario** via `execute_command`.
6. **Confirm the failure actually reproduces** via `get_logs`/`query_database` before touching
   any code — don't assume; verify the "before" state matches the reported symptom.
7. **Use `code_ask` to locate the responsible code**, form a hypothesis, then `code_edit` to
   apply a fix.
8. **Rebuild + restart** (`start_service` with the same branch, or `restart_service` if the
   change doesn't require a rebuild) and **re-run the exact same trigger** from step 5.
9. **Compare before/after**: same logs pattern gone, DB ends in the expected state, no new
   errors introduced. Only then consider the hypothesis verified.
10. For hotfix testing specifically: also re-run any adjacent scenarios (via the mock-based or
    concurrency playbooks if relevant) to catch regressions the hotfix might introduce.
