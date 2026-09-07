"""Evidence-first LangGraph workflow for Praxis Lens debugging experiments.

    START -> classify_case -> load_relevant_playbook -> scope_environment
          -> provision_environment -> discover_environment -> plan_experiments
          -> workflow_router
               -> mock_contract_workflow
               -> performance_workflow
               -> generic_experiment_workflow
          -> collect_evidence -> assess_evidence
               -> another scenario/new hypothesis -> plan_experiments
               -> explicit fix requested -> diagnose -> edit -> deploy -> replay
               -> conclusive -> respond -> END
               -> missing detail/budget exhausted -> escalate -> plan_experiments

Specialist workflow nodes provide a safe tool order for external mock contracts and performance
investigations. Every other present and future case falls through to the generic experiment
workflow instead of being rejected because it lacks a dedicated graph branch.
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from praxis_agent.agent.context import get_current_bus
from praxis_agent.agent.decisions import (
    CaseClassification,
    EnvironmentPlan,
    EnvironmentRef,
    EvidenceAssessment,
    HypothesisPlan,
    ScenarioOutcome,
)
from praxis_agent.agent.events import EventType
from praxis_agent.agent.llm import get_llm
from praxis_agent.agent.prompts import BASE_SYSTEM_PROMPT
from praxis_agent.agent.state import AgentState
from praxis_agent.agent.tool_loop import run_tool_loop
from praxis_agent.config import settings
from praxis_agent.tools import (
    DEPLOY_TOOLS,
    DIAGNOSIS_TOOLS,
    DISCOVERY_TOOLS,
    EDIT_TOOLS,
    EVIDENCE_TOOLS,
    MOCK_CONTRACT_TOOLS,
    PERFORMANCE_TOOLS,
    PROVISION_TOOLS,
    SKILL_TOOLS,
    EXPERIMENT_TOOLS,
)

MAX_SKILL_CHECK_STEPS = 2
MAX_MOCK_CONTRACT_TOOL_STEPS = 12


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    bus = get_current_bus()
    if bus:
        bus.publish(event_type, payload)


def _environment_plan(state: AgentState) -> dict[str, Any]:
    return state.get("environment_plan") or {}


def _workflow_node(state: AgentState) -> str:
    workflow = state.get("workflow", "generic_experiment")
    if workflow == "mock_contract":
        return "mock_contract_workflow"
    if workflow == "performance":
        return "performance_workflow"
    return "generic_experiment_workflow"


async def classify_case(state: AgentState) -> dict:
    messages = state.get("messages") or []
    if not any(isinstance(message, SystemMessage) for message in messages):
        messages = [SystemMessage(content=BASE_SYSTEM_PROMPT)] + messages
    if not any(isinstance(message, HumanMessage) for message in messages):
        messages = messages + [HumanMessage(content=state.get("goal", ""))]

    classifier = get_llm().with_structured_output(CaseClassification)
    result: CaseClassification = await classifier.ainvoke(
        messages
        + [
            HumanMessage(
                content=(
                    "Classify this debugging/testing request. Select mock_contract only when "
                    "the external Mock Server must be configured against a supplied contract; "
                    "select performance for CPU, memory, throughput, or load analysis; select "
                    "generic_experiment for every other current or future case. Set "
                    "fix_requested true only if the developer explicitly asked to change code. "
                    "Do not call tools."
                )
            )
        ]
    )
    _publish(
        EventType.CASE_CLASSIFIED,
        {
            "case_type": result.case_type,
            "workflow": result.workflow,
            "fix_requested": result.fix_requested,
            "needs_scenario_iteration": result.needs_scenario_iteration,
            "reasoning": result.reasoning,
        },
    )
    return {
        "messages": messages,
        "case_type": result.case_type,
        "workflow": result.workflow,
        "fix_requested": result.fix_requested,
        "needs_scenario_iteration": result.needs_scenario_iteration,
        "skill_hints": result.initial_skill_hints,
        "iteration_count": 0,
        "max_iterations": state.get("max_iterations") or settings.max_iterations,
        "scenario_queue": [],
        "scenario_results": [],
        "remediation_attempted": False,
        "done": False,
    }


async def load_relevant_playbook(state: AgentState) -> dict:
    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Case type: {state.get('case_type')}; workflow: {state.get('workflow')}.\n"
        f"Skill hints: {state.get('skill_hints')}.\n"
        "Before planning the environment or an experiment, inspect available playbooks and load "
        "only the one(s) relevant to this request. Do not use any non-skill tool."
    )
    new_messages = await run_tool_loop(
        state.get("messages") or [], SKILL_TOOLS, instruction, max_steps=MAX_SKILL_CHECK_STEPS
    )
    return {"messages": new_messages}


async def scope_environment(state: AgentState) -> dict:
    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Existing environment id: {state.get('environment_id') or 'none'}.\n"
        "Determine the minimal executor catalog services required. The Mock Server is external "
        "and must never appear in services. Do not request standalone or independent databases. "
        "If the developer named a branch, add it to branch_services so it is started after "
        "provisioning. Include a repository only when the developer supplied an HTTPS URL and "
        "exact revision. If an existing environment is supplied, services may be empty."
    )
    planner = get_llm().with_structured_output(EnvironmentPlan, method="function_calling")
    plan: EnvironmentPlan = await planner.ainvoke(
        (state.get("messages") or []) + [HumanMessage(content=instruction)]
    )
    _publish(EventType.AGENT_THOUGHT, {"stage": "scope", "summary": plan.reasoning})
    return {"environment_plan": plan.model_dump(mode="json")}


async def provision_environment(state: AgentState) -> dict:
    plan = _environment_plan(state)
    branches = plan.get("branch_services") or []
    environment_id = state.get("environment_id")

    if environment_id:
        if not branches:
            return {}
        instruction = (
            f"Environment id: {environment_id}\n"
            f"Start these services from their requested branches: {branches}.\n"
            "Call start_service once for each listed service and branch. Do not call any other tool."
        )
        return {
            "messages": await run_tool_loop(
                state.get("messages") or [], PROVISION_TOOLS, instruction
            )
        }

    services = plan.get("services") or []
    if not services:
        return {
            "messages": [
                AIMessage(
                    content=(
                        "No executor services could be safely selected from the request. "
                        "More service or contract detail is required before provisioning."
                    )
                )
            ]
        }

    instruction = (
        f"Create exactly one isolated environment with these executor catalog services: {services}.\n"
        f"Repository checkout, if supplied: {plan.get('repository')}.\n"
        f"After it is ready, start these branch-specific services if any: {branches}.\n"
        "Use create_environment exactly once, then start_service for each requested branch. "
        "Never include the external Mock Server or standalone/independent databases. Do not "
        "perform reproduction, inspection, routing, config, or code-edit actions yet."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], PROVISION_TOOLS, instruction)
    extractor = get_llm().with_structured_output(EnvironmentRef)
    ref: EnvironmentRef = await extractor.ainvoke(
        (state.get("messages") or [])
        + new_messages
        + [HumanMessage(content="Extract the environment_id created during provisioning, if any.")]
    )
    return {"messages": new_messages, "environment_id": ref.environment_id}


def provision_router(state: AgentState) -> str:
    return "discover_environment" if state.get("environment_id") else "escalate"


async def discover_environment(state: AgentState) -> dict:
    plan = _environment_plan(state)
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Services under test: {plan.get('services') or 'discover from environment status'}.\n"
        "Perform a read-only runtime inventory before designing any scenario. Inspect environment "
        "status, exact internal service endpoints (including toolbox), orchestrator health, and "
        "registered in-environment routes. Inspect the env file of every service under test. "
        "Use only the supplied discovery tools; do not execute commands, mutate configuration, "
        "change routes, configure the external Mock Server, or edit code."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], DISCOVERY_TOOLS, instruction)
    _publish(
        EventType.AGENT_THOUGHT,
        {
            "stage": "discover_environment",
            "summary": "Collected live service topology, endpoints, routes, and relevant configuration.",
        },
    )
    return {"messages": new_messages}


async def plan_experiments(state: AgentState) -> dict:
    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Workflow: {state.get('workflow')}\n"
        f"Environment id: {state.get('environment_id')}\n"
        f"Configured external Mock Server URL: {settings.mock_server_url or 'not configured'}\n"
        f"Previous hypothesis: {state.get('hypothesis')}\n"
        f"Previous assessment: {state.get('verify_reasoning')}\n"
        "Use the discovered topology and loaded playbook to form or refine one hypothesis and an "
        "ordered scenario queue. Each scenario must contain setup, an exact trigger, and expected "
        "evidence so it can be replayed after an explicitly requested fix. For an external mock "
        "contract workflow, base scenarios only on the contract the developer supplied. Return an "
        "empty queue only if a safe experiment cannot be designed from the information available."
    )
    planner = get_llm().with_structured_output(HypothesisPlan, method="function_calling")
    plan: HypothesisPlan = await planner.ainvoke(
        (state.get("messages") or []) + [HumanMessage(content=instruction)]
    )
    scenarios = [scenario.model_dump(mode="json") for scenario in plan.scenario_queue]
    _publish(
        EventType.HYPOTHESIS,
        {
            "hypothesis": plan.hypothesis,
            "plan_note": plan.plan_note,
            "scenario_count": len(scenarios),
        },
    )
    return {
        "messages": [AIMessage(content=f"Hypothesis: {plan.hypothesis}\nPlan: {plan.plan_note}")],
        "hypothesis": plan.hypothesis,
        "scenario_queue": scenarios,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


def plan_router(state: AgentState) -> str:
    return _workflow_node(state) if state.get("scenario_queue") else "escalate"


async def _run_next_scenario(
    state: AgentState, instruction: str, tools: list[BaseTool], *, max_steps: int | None = None
) -> dict:
    queue = list(state.get("scenario_queue") or [])
    scenario = queue.pop(0)
    _publish(EventType.SCENARIO_STARTED, {"scenario": scenario})
    kwargs = {"max_steps": max_steps} if max_steps is not None else {}
    new_messages = await run_tool_loop(state.get("messages") or [], tools, instruction, **kwargs)
    return {
        "messages": new_messages,
        "scenario_queue": queue,
        "active_scenario": scenario,
    }


async def generic_experiment_workflow(state: AgentState) -> dict:
    scenario = (state.get("scenario_queue") or [None])[0]
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Hypothesis: {state.get('hypothesis')}\n"
        f"Execute this generic experiment scenario exactly: {scenario}\n"
        "Set up only the documented environment state this scenario requires, execute its trigger, "
        "and leave evidence collection to the next node. You may use read-only code Q&A to "
        "understand the service, but must not call code_edit. Do not request external Mock Server "
        "or standalone databases from the executor."
    )
    return await _run_next_scenario(state, instruction, EXPERIMENT_TOOLS)


async def mock_contract_workflow(state: AgentState) -> dict:
    scenario = (state.get("scenario_queue") or [None])[0]
    mock_url = settings.mock_server_url or "not configured"
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Configured external Mock Server URL: {mock_url}\n"
        f"Hypothesis: {state.get('hypothesis')}\n"
        f"Execute this external mock-contract scenario exactly: {scenario}\n"
        "Use the existing external Mock Server tools to create/select responses and API definitions "
        "only from the developer-supplied third-party contract. Inspect orchestrator routes and "
        "the wrapper call site first. When the wrapper calls the orchestrator, prefer a "
        "caller-specific route to target=\"mock-server\"; no restart is needed. Otherwise point "
        "the wrapper at the external Mock Server through its discovered env/config setting and "
        "restart it if the setting changed. Trigger the wrapper using its supplied contract. "
        "Never provision mock-server through the executor. Do not call code_edit."
    )
    return await _run_next_scenario(
        state, instruction, MOCK_CONTRACT_TOOLS, max_steps=MAX_MOCK_CONTRACT_TOOL_STEPS
    )


async def performance_workflow(state: AgentState) -> dict:
    scenario = (state.get("scenario_queue") or [None])[0]
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Hypothesis: {state.get('hypothesis')}\n"
        f"Execute this performance scenario exactly: {scenario}\n"
        "Use run_load_test for bounded concurrent load against discovered internal service "
        "endpoints; specify a service-relative path, request inputs, hit count, and a per-request "
        "timeout no greater than 60 seconds. Do not guess service ports or use localhost to reach "
        "another container. Establish the specified load; the next node will capture comparable "
        "metrics and other evidence. Do not call code_edit."
    )
    return await _run_next_scenario(state, instruction, PERFORMANCE_TOOLS)


async def collect_evidence(state: AgentState) -> dict:
    scenario = state.get("active_scenario") or {}
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Scenario just executed: {scenario}\n"
        "Collect only the concrete evidence required by this scenario: relevant logs, the "
        "service-owned database state, and service or aligned environment metrics when applicable. "
        "Use database service names discovered during environment inventory. Do not change "
        "configuration, routes, mocks, source code, or lifecycle state."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], EVIDENCE_TOOLS, instruction)
    outcome_llm = get_llm().with_structured_output(ScenarioOutcome)
    outcome: ScenarioOutcome = await outcome_llm.ainvoke(
        (state.get("messages") or [])
        + new_messages
        + [HumanMessage(content="Summarize this scenario using only the collected evidence.")]
    )
    result = {"scenario": scenario, "summary": outcome.summary, "passed": outcome.passed}
    _publish(EventType.SCENARIO_COMPLETED, result)
    return {
        "messages": new_messages,
        "scenario_results": [*(state.get("scenario_results") or []), result],
    }


async def assess_evidence(state: AgentState) -> dict:
    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Current hypothesis: {state.get('hypothesis')}\n"
        f"Scenario results: {state.get('scenario_results')}\n"
        f"Queued scenarios remaining: {len(state.get('scenario_queue') or [])}\n"
        f"Code fix explicitly requested: {state.get('fix_requested')}.\n"
        "Assess only the evidence collected so far. Select next_scenario when queued coverage "
        "remains, replan when a different hypothesis needs testing, diagnose only when the defect "
        "is evidenced and an explicitly requested fix should be prepared, respond when the "
        "requested investigation is conclusive, or escalate when a safe experiment needs missing "
        "developer information."
    )
    assessor = get_llm().with_structured_output(EvidenceAssessment)
    decision: EvidenceAssessment = await assessor.ainvoke(
        (state.get("messages") or []) + [HumanMessage(content=instruction)]
    )
    _publish(
        EventType.VERIFY_RESULT,
        {
            "confirmed": decision.next_step in {"diagnose", "respond"},
            "reasoning": decision.reasoning,
        },
    )
    return {
        "messages": [AIMessage(content=f"Assessment: {decision.next_step}. {decision.reasoning}")],
        "verified": decision.next_step in {"diagnose", "respond"},
        "verify_reasoning": decision.reasoning,
        "final_answer": decision.final_answer,
        "assessment_next_step": decision.next_step,
    }


def assessment_router(state: AgentState) -> str:
    if state.get("scenario_queue"):
        return _workflow_node(state)

    next_step = state.get("assessment_next_step")
    if next_step == "respond":
        return "respond"
    if next_step == "diagnose" and state.get("fix_requested") and not state.get("remediation_attempted"):
        return "diagnose"
    if next_step in {"next_scenario", "replan", "diagnose"} and state.get(
        "iteration_count", 0
    ) < state.get("max_iterations", settings.max_iterations):
        return "plan_experiments"
    return "escalate"


async def diagnose(state: AgentState) -> dict:
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Confirmed evidence: {state.get('verify_reasoning')}\n"
        f"Scenario to replay after the fix: {state.get('active_scenario')}\n"
        "The developer explicitly requested a code fix. Use read-only code Q&A to identify the "
        "minimal change that explains the evidence. Do not edit code in this phase."
    )
    return {
        "messages": await run_tool_loop(
            state.get("messages") or [], DIAGNOSIS_TOOLS, instruction
        )
    }


async def edit(state: AgentState) -> dict:
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Diagnosis: {state.get('verify_reasoning')}\n"
        "Apply only the minimal source change needed to address the diagnosed defect. The developer "
        "explicitly requested this fix. Do not perform deployment or verification in this phase."
    )
    return {
        "messages": await run_tool_loop(state.get("messages") or [], EDIT_TOOLS, instruction)
    }


async def deploy(state: AgentState) -> dict:
    plan = _environment_plan(state)
    instruction = (
        f"Environment id: {state.get('environment_id')}\n"
        f"Branch services from the environment plan: {plan.get('branch_services') or []}\n"
        "Pick up the completed code edit using the documented lifecycle operation: start the "
        "affected service from its requested branch when a source rebuild is required, otherwise "
        "restart the affected service. Do not use unsupported rebuild endpoints. Do not run the "
        "verification trigger yet."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], DEPLOY_TOOLS, instruction)
    active_scenario = state.get("active_scenario")
    return {
        "messages": new_messages,
        "scenario_queue": [active_scenario] if active_scenario else [],
        "remediation_attempted": True,
    }


async def respond(state: AgentState) -> dict:
    answer = state.get("final_answer") or state.get("verify_reasoning") or "Investigation complete."
    _publish(EventType.RUN_COMPLETED, {"final_answer": answer})
    return {"messages": [AIMessage(content=answer)], "done": True}


async def escalate(state: AgentState) -> dict:
    _publish(
        EventType.ESCALATION,
        {
            "hypothesis": state.get("hypothesis"),
            "iteration_count": state.get("iteration_count"),
            "scenario_results": state.get("scenario_results"),
        },
    )
    guidance = interrupt(
        {
            "reason": (
                "A safe next experiment needs more developer detail, or the hypothesis budget "
                "was exhausted."
            ),
            "hypothesis": state.get("hypothesis"),
            "last_assessment": state.get("verify_reasoning"),
            "scenario_results": state.get("scenario_results"),
        }
    )
    return {
        "messages": [HumanMessage(content=str(guidance))],
        "iteration_count": 0,
        "verified": False,
        "done": False,
    }


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_case", classify_case)
    graph.add_node("load_relevant_playbook", load_relevant_playbook)
    graph.add_node("scope_environment", scope_environment)
    graph.add_node("provision_environment", provision_environment)
    graph.add_node("discover_environment", discover_environment)
    graph.add_node("plan_experiments", plan_experiments)
    graph.add_node("generic_experiment_workflow", generic_experiment_workflow)
    graph.add_node("mock_contract_workflow", mock_contract_workflow)
    graph.add_node("performance_workflow", performance_workflow)
    graph.add_node("collect_evidence", collect_evidence)
    graph.add_node("assess_evidence", assess_evidence)
    graph.add_node("diagnose", diagnose)
    graph.add_node("edit", edit)
    graph.add_node("deploy", deploy)
    graph.add_node("respond", respond)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "classify_case")
    graph.add_edge("classify_case", "load_relevant_playbook")
    graph.add_edge("load_relevant_playbook", "scope_environment")
    graph.add_edge("scope_environment", "provision_environment")
    graph.add_conditional_edges(
        "provision_environment",
        provision_router,
        {"discover_environment": "discover_environment", "escalate": "escalate"},
    )
    graph.add_edge("discover_environment", "plan_experiments")
    graph.add_conditional_edges(
        "plan_experiments",
        plan_router,
        {
            "generic_experiment_workflow": "generic_experiment_workflow",
            "mock_contract_workflow": "mock_contract_workflow",
            "performance_workflow": "performance_workflow",
            "escalate": "escalate",
        },
    )
    for workflow in (
        "generic_experiment_workflow",
        "mock_contract_workflow",
        "performance_workflow",
    ):
        graph.add_edge(workflow, "collect_evidence")
    graph.add_edge("collect_evidence", "assess_evidence")
    graph.add_conditional_edges(
        "assess_evidence",
        assessment_router,
        {
            "generic_experiment_workflow": "generic_experiment_workflow",
            "mock_contract_workflow": "mock_contract_workflow",
            "performance_workflow": "performance_workflow",
            "plan_experiments": "plan_experiments",
            "diagnose": "diagnose",
            "respond": "respond",
            "escalate": "escalate",
        },
    )
    graph.add_edge("diagnose", "edit")
    graph.add_edge("edit", "deploy")
    graph.add_conditional_edges(
        "deploy",
        _workflow_node,
        {
            "generic_experiment_workflow": "generic_experiment_workflow",
            "mock_contract_workflow": "mock_contract_workflow",
            "performance_workflow": "performance_workflow",
        },
    )
    graph.add_edge("respond", END)
    graph.add_edge("escalate", "plan_experiments")

    return graph.compile(checkpointer=MemorySaver())


def _print_graph(compiled) -> None:
    print("\n=== Praxis Lens agent graph ===")
    print(compiled.get_graph().draw_mermaid())
    print("=== (paste into https://mermaid.live to visualize) ===\n")


praxis_graph = build_graph()
_print_graph(praxis_graph)
