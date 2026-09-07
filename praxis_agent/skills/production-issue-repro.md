---
name: production-issue-repro
tags: [reproduction, repro, incident, hotfix, configuration]
summary: Playbook for reproducing a reported production bug in an isolated environment, gathering
  evidence, and verifying an explicitly requested fix.
---

# Production issue reproduction playbook

Use this for "reproduce this reported bug" or "quick hotfix testing" requests.

## Steps

1. **Scope the services.** From the bug description, select the minimal executor catalog
   services needed. Do not request the external Mock Server or standalone databases.
2. **Create and discover the environment.** Use `create_environment`, then inspect its status,
   exact internal endpoints, orchestrator status, and the target service env before reproducing.
   Query only the service-owned database instance that discovery identifies.
3. **If the bug involves an external dependency** (e.g. a third-party API returning something
   unexpected), see the `mock-based-testing` skill — mock the dependency rather than hitting
   the real one.
4. **Start the relevant branch when supplied.** If the developer identifies a branch that
   reproduces the issue, use `start_service(..., branch=...)` for deterministic reproduction.
5. **Trigger the failing scenario** via `execute_command`.
6. **Confirm the failure actually reproduces** via `get_logs`/`query_database` before touching
   any code — don't assume; verify the "before" state matches the reported symptom.
7. **Use `code_ask` to locate the responsible code** only after evidence supports a hypothesis.
   Call `code_edit` only when the developer explicitly asks for a source change.
8. **Deploy + restart** with `start_service` using the same branch when a source build is
   needed, or `restart_service` otherwise, then **re-run the exact same trigger** from step 5.
9. **Compare before/after**: same logs pattern gone, DB ends in the expected state, no new
   errors introduced. Only then consider the hypothesis verified.
10. For hotfix testing specifically: also re-run any adjacent scenarios (via the mock-based or
    concurrency playbooks if relevant) to catch regressions the hotfix might introduce.
