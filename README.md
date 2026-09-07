# Praxis Lens — LangGraph Agent

The reasoning/orchestration layer for Praxis Lens. It talks exclusively over HTTP to:

- the **Execution Service** (Node.js, e.g. `http://localhost:3000`) — environments, services,
  logs, databases, metrics, secrets/config, and aider-backed code Q&A/edit
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
    mock_server_client.py      # typed async wrapper over the (assumed) mock-server contract
  tools/                       # one @tool per client method, grouped by domain
    environment_tools.py
    inspection_tools.py
    code_tools.py
    config_tools.py
    mock_tools.py
    orchestrator_tools.py      # zero-downtime route repointing (e.g. -> mock server, A/B)
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
START -> classify_case -> provision_environment -> hypothesize -> scenario_router
                                                                        |
                        +-----------------------------------------------+
                        |                                               |
              run_scenario_loop (self-loop while                       act
              scenario_queue non-empty; mock-based/                     |
              concurrency/A-B testing cases)                            |
                        |                                               |
                        +--------------------> observe <-----------------+
                                                  |  (need_more_action -> act)
                                                  v
                                               verify
                                     confirmed |   | denied + budget left -> hypothesize (loop)
                                               v   v denied + budget exhausted
                                            respond   escalate --(interrupt, human resume)--> hypothesize
                                             (END)
```

- **Case-based branching**: `classify_case` decides the workflow shape (mock-based testing,
  concurrency testing, performance testing, production repro, hotfix testing, feature-branch
  testing, general debug) and whether it needs scenario iteration.
- **Real cycles, not a flat tool loop**: `run_scenario_loop` self-loops draining a queue of
  scenarios (mock response combos, concurrency levels, ...); the `hypothesize -> act/scenario
  loop -> observe -> verify` cycle repeats (bounded by `PRAXIS_MAX_ITERATIONS`) until the
  hypothesis is confirmed or the budget is exhausted, at which point `escalate` uses
  LangGraph's `interrupt()` to hand control back to a human instead of failing silently.
- **Skills are tools**, not silent RAG — the agent calls `list_skills()`/`load_skill(name)`
  itself when it judges it needs a playbook or service-specific domain notes.
- State is checkpointed (in-memory `MemorySaver`, keyed by session id) so follow-up messages
  and interrupt resumes continue the same conversation/graph state.

## Setup

```bash
cp .env.example .env        # fill in OPENAI_API_KEY; EXECUTION_SERVICE_URL defaults to
                             # http://localhost:3000; set MOCK_SERVER_URL for mock-based
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

## Assumptions to revisit once real details are available

- **Mock Server API contract** (`clients/mock_server_client.py`) is built against the
  described-but-unconfirmed contract: response groups -> responses -> mocks, all by id, with
  list/get-by-id lookups. Isolated in one file so it's a small change once real docs exist.
- **Env-var injection on the execution service**: no dedicated endpoint exists yet, so
  `set_env_var` reuses the documented `POST /environments/:id/services/:service/config`
  endpoint (which already writes a per-service env file consumed on restart).

## Tests

```bash
python tests/test_routers.py            # pure routing-function unit tests
python tests/test_graph_happy_path.py    # mocked LLM: single-shot confirm path
python tests/test_graph_scenario_loop.py # mocked LLM: scenario-iteration path (3 scenarios)
python tests/test_graph_escalate.py      # mocked LLM: budget-exhausted -> interrupt -> resume
```

All four are self-contained (fake LLM, no live OpenAI/execution-service calls needed) and
pass as of this writing. A real end-to-end run additionally needs a valid `OPENAI_API_KEY`
and the execution service reachable at `EXECUTION_SERVICE_URL`.
