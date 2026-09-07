# Praxis Lens — LangGraph Agent

The reasoning/orchestration layer for Praxis Lens. It talks exclusively over HTTP to:

- the **Execution Service** (Node.js, e.g. `http://localhost:3000`) — environments, services,
  logs, service-owned databases, metrics, configuration, and aider-backed code Q&A/edit
- the **Mock Server** (URL supplied at runtime) — mocked dependency responses for
  scenario-based testing

It never touches Docker, git, shell, or the filesystem directly.

## Architecture

```
praxis_agent/
  config.py                  # env-driven settings (OPENAI_API_KEY, EXECUTION_SERVICE_URL, ...)
  clients/
    execution_client.py       # typed async wrapper over every execution-service endpoint,
                               # with transparent job polling for async operations
    mock_server_client.py      # typed async wrapper over the external mock-server contract
  tools/                       # focused @tool collections grouped by domain
    environment_tools.py
    inspection_tools.py
    code_tools.py
    config_tools.py
    mock_tools.py
    orchestrator_tools.py      # in-environment route inspection/repointing
    skill_tools.py             # list_skills() / load_skill(name)
  skills/                       # markdown playbooks + service notes, loaded on demand
  agent/
    state.py                   # AgentState (messages, case_type, hypothesis, scenario_queue, ...)
    decisions.py                # Pydantic schemas for structured-output routing decisions
    prompts.py                  # base system prompt
    llm.py                      # ChatOpenAI factory
    tool_loop.py                 # reusable ReAct-style tool-calling micro-loop
    graph.py                     # the compiled LangGraph StateGraph (see below)
    events.py                    # per-session SSE event bus
    context.py                   # contextvar plumbing so tools can publish events
    runner.py                    # runs the graph per session, handles interrupt/resume
  api/
    server.py                   # FastAPI: /sessions, /sessions/:id/message, /sessions/:id/events (SSE)
  tui/
    main.py                     # Rich-based terminal UI consuming the SSE stream live
main.py                          # uvicorn entrypoint
tests/                           # offline smoke tests (mocked LLM, no network required)
```

## Graph design

```
START -> classify_case -> load_relevant_playbook -> scope_environment
      -> provision_environment -> discover_environment -> plan_experiments
      -> workflow_router
           | mock-contract workflow
           | performance workflow
           + generic experiment workflow (fallback)
      -> collect_evidence -> assess_evidence
           | queued scenario/new hypothesis -> plan_experiments
           | explicit fix requested -> diagnose -> edit -> deploy -> replay scenario
           | conclusive -> respond -> END
           + missing detail/budget exhausted -> escalate --(interrupt, human resume)--> plan_experiments
```

- **Specialists plus fallback**: mock-contract and performance requests use purpose-built,
  phase-limited tool paths. Replication, concurrency, hotfix, feature-branch, configuration,
  integration, and new future cases use the generic experiment workflow rather than failing
  classification.
- **Discovery before experiments**: after provisioning, the agent reads live service state,
  internal endpoints (including `toolbox`), orchestrator state/routes, and target-service env.
  It then plans replayable scenarios with explicit triggers and expected evidence.
- **Evidence-first remediation**: source editing is unavailable during reproduction and
  observation. It is permitted only when the developer explicitly requests a change, evidence
  supports the diagnosis, and the post-edit workflow can replay the same scenario.
- **Skills are tools**, not silent RAG — the agent calls `list_skills()`/`load_skill(name)`
  itself when it judges it needs a playbook or service-specific domain notes.
- State is checkpointed (in-memory `MemorySaver`, keyed by session id) so follow-up messages
  and interrupt resumes continue the same conversation/graph state.

## Setup

```bash
cp .env.example .env        # fill in OPENAI_API_KEY; EXECUTION_SERVICE_URL defaults to
                             # http://localhost:3000; set MOCK_SERVER_URL for mock-contract
                             # testing
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python main.py                                  # starts the FastAPI server on :8000
python -m praxis_agent.tui.main --goal "Reproduce the intermittent EDI/Axis failure"
# or, to attach to an existing session from another terminal:
python -m praxis_agent.tui.main --session-id session-xxxxxxxx
```

### API

- `POST /sessions {"goal": "..."}` -> `{sessionId, status}` — starts a run in the background
- `POST /sessions/:id/message {"text": "..."}` -> follow-up turn (resumes an `interrupt` if
  the agent escalated and is waiting for human input, otherwise a new conversational turn)
- `GET /sessions/:id/events` -> SSE stream of structured events (`case_classified`,
  `hypothesis`, `tool_call_started/completed/failed`, `job_progress`, `skill_loaded`,
  `scenario_started/completed`, `verify_result`, `escalation`, `run_completed`, `error`)
- `GET /sessions/:id` -> current status (`running` / `waiting_input` / `completed` / `failed`)

## API call logging

Every outbound call to the Execution Service and Mock Server is logged as JSON lines to
`logs/api_calls.log` (path configurable via `PRAXIS_API_LOG_FILE`), including method, URL,
request body/params, status code, response body, error (if any), and duration:

```bash
tail -f logs/api_calls.log | python -m json.tool --json-lines   # or just `tail -f` for raw JSON
```

This is independent of the SSE event stream — useful when you want to see the exact wire
traffic rather than the agent's higher-level tool-call view.

## Runtime boundaries

- The **Mock Server is external** to every executor environment and is reached only through the
  existing mock tools. The agent points a wrapper service at its configured external domain with
  `get_service_env`/`update_service_env` (or the single-key `set_env_var`) and restarts that
  wrapper. It never provisions the Mock Server or targets it through executor routes.
- The executor provisions only catalog services required for the experiment. The agent never
  asks it to create standalone/independent databases; it discovers and queries service-owned
  database instances from the live environment.
- The agent can inspect a service's complete env file and merge values through the documented
  `/env` endpoints. `set_env_var` remains a single-key wrapper for the documented `/config`
  endpoint.

## Tests

```bash
python tests/test_routers.py            # pure routing-function unit tests
python tests/test_execution_client.py    # mocked HTTP: supported executor request paths
python tests/test_graph_happy_path.py    # mocked LLM: discovery -> generic evidence path
python tests/test_graph_scenario_loop.py # mocked LLM: external mock-contract scenarios
python tests/test_graph_explicit_fix.py  # mocked LLM: explicit fix -> deploy -> identical replay
python tests/test_graph_escalate.py      # mocked LLM: budget-exhausted -> interrupt -> resume
```

All six are self-contained (fake LLM/mock HTTP, no live OpenAI/execution-service calls needed).
A real end-to-end run additionally needs a valid `OPENAI_API_KEY`
and the execution service reachable at `EXECUTION_SERVICE_URL`.
