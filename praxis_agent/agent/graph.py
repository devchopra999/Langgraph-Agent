"""The Praxis Lens LangGraph agent graph.

Real state machine (not a flat ReAct loop): a case classifier branches into either a
scenario-iteration path (mock-based testing, concurrency testing, A/B comparisons) or a
single-shot path (repro/hotfix/general debug), both of which feed into the shared
hypothesize -> act -> observe -> verify experiment loop with real back-edges, capped by
`max_iterations`, and an escalation path (human-in-the-loop `interrupt`) if the budget is
exhausted without a confirmed fix.

    START
      -> classify_case
      -> provision_environment           (skippable if environment_id already set)
      -> hypothesize                     (loop target on a denied verify)
      -> scenario_router (conditional)
           -> run_scenario_loop (self-looping while scenario_queue non-empty) -> observe
           -> act                                                             -> observe
      -> observe (conditional: back to act for more evidence, or -> verify)
      -> verify (conditional: confirmed -> respond/END
                              denied + budget left -> hypothesize
                              denied + budget exhausted -> escalate -> END)
"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from praxis_agent.agent.context import get_current_bus
from praxis_agent.agent.decisions import (
    CaseClassification,
    EnvironmentRef,
    HypothesisPlan,
    ObserveDecision,
    ScenarioOutcome,
    VerifyDecision,
)
from praxis_agent.agent.events import EventType
from praxis_agent.agent.llm import get_llm
from praxis_agent.agent.prompts import BASE_SYSTEM_PROMPT
from praxis_agent.agent.state import AgentState
from praxis_agent.agent.tool_loop import run_tool_loop
from praxis_agent.config import settings
from praxis_agent.tools import ALL_TOOLS

MAX_OBSERVE_ATTEMPTS = 3


def _publish(event_type: str, payload: dict[str, Any]) -> None:
    bus = get_current_bus()
    if bus:
        bus.publish(event_type, payload)


# ---------------------------------------------------------------------- #
# nodes
# ---------------------------------------------------------------------- #
async def classify_case(state: AgentState) -> dict:
    messages = state.get("messages") or []
    if not any(isinstance(m, SystemMessage) for m in messages):
        messages = [SystemMessage(content=BASE_SYSTEM_PROMPT)] + messages
    if not any(isinstance(m, HumanMessage) for m in messages):
        messages = messages + [HumanMessage(content=state.get("goal", ""))]

    classifier = get_llm().with_structured_output(CaseClassification)
    result: CaseClassification = await classifier.ainvoke(
        messages
        + [
            HumanMessage(
                content=(
                    "Classify this debugging/testing goal into a case_type and decide whether it "
                    "needs scenario iteration. Do not call any tools yet."
                )
            )
        ]
    )
    _publish(
        EventType.CASE_CLASSIFIED,
        {"case_type": result.case_type, "needs_scenario_iteration": result.needs_scenario_iteration, "reasoning": result.reasoning},
    )
    return {
        "messages": messages,
        "case_type": result.case_type,
        "needs_scenario_iteration": result.needs_scenario_iteration,
        "skill_hints": result.initial_skill_hints,
        "iteration_count": 0,
        "max_iterations": state.get("max_iterations") or settings.max_iterations,
        "observe_attempts": 0,
        "scenario_queue": [],
        "scenario_results": [],
        "done": False,
    }


async def provision_environment(state: AgentState) -> dict:
    if state.get("environment_id"):
        return {}

    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Case type: {state.get('case_type')}. Skill hints: {state.get('skill_hints')}.\n"
        "Decide the minimal set of services needed and create/provision the environment now "
        "(use list_skills/load_skill first if a relevant playbook exists). If a repository/"
        "branch/commit was mentioned in the goal, attach it. Stop once the environment is "
        "ready — do not start reproducing the bug yet."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], ALL_TOOLS, instruction)

    extractor = get_llm().with_structured_output(EnvironmentRef)
    ref: EnvironmentRef = await extractor.ainvoke((state.get("messages") or []) + new_messages)

    return {"messages": new_messages, "environment_id": ref.environment_id}


async def hypothesize(state: AgentState) -> dict:
    instruction = (
        f"Goal: {state.get('goal')}\n"
        f"Case type: {state.get('case_type')}\n"
        f"Environment id: {state.get('environment_id')}\n"
        f"Previous hypothesis (if any): {state.get('hypothesis')}\n"
        f"Prior verify reasoning (if any): {state.get('verify_reasoning')}\n"
        "Form (or refine) your hypothesis and decide the next concrete plan. If this case "
        "needs scenario iteration, populate scenario_queue with the concrete scenarios to try."
    )
    # HypothesisPlan.scenario_queue is a free-form list[dict[str, Any]], which OpenAI's
    # strict json_schema structured-output mode rejects (requires additionalProperties=false
    # on every nested object). function_calling mode doesn't enforce that strictness.
    planner = get_llm().with_structured_output(HypothesisPlan, method="function_calling")
    plan: HypothesisPlan = await planner.ainvoke((state.get("messages") or []) + [HumanMessage(content=instruction)])

    _publish(EventType.HYPOTHESIS, {"hypothesis": plan.hypothesis, "plan_note": plan.plan_note, "scenario_count": len(plan.scenario_queue)})

    scenario_queue = plan.scenario_queue if state.get("needs_scenario_iteration") else []
    return {
        "messages": [AIMessage(content=f"Hypothesis: {plan.hypothesis}\nPlan: {plan.plan_note}")],
        "hypothesis": plan.hypothesis,
        "scenario_queue": scenario_queue,
        "iteration_count": state.get("iteration_count", 0) + 1,
        "observe_attempts": 0,
    }


def scenario_router(state: AgentState) -> str:
    if state.get("needs_scenario_iteration") and state.get("scenario_queue"):
        return "run_scenario_loop"
    return "act"


async def run_scenario_loop(state: AgentState) -> dict:
    queue = list(state.get("scenario_queue") or [])
    scenario = queue.pop(0)
    _publish(EventType.SCENARIO_STARTED, {"scenario": scenario})

    instruction = (
        f"Hypothesis: {state.get('hypothesis')}\n"
        f"Environment id: {state.get('environment_id')}\n"
        f"Execute exactly this scenario now: {scenario}\n"
        "Set up whatever mock/config/env-var/concurrency-parameter this scenario implies, "
        "trigger the reproduction, and gather evidence (logs/db/metrics) for THIS scenario "
        "only. Do not judge the overall hypothesis yet."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], ALL_TOOLS, instruction)

    outcome_llm = get_llm().with_structured_output(ScenarioOutcome)
    outcome: ScenarioOutcome = await outcome_llm.ainvoke(
        (state.get("messages") or []) + new_messages + [HumanMessage(content="Summarize the pass/fail outcome for this single scenario.")]
    )
    result = {"scenario": scenario, "summary": outcome.summary, "passed": outcome.passed}
    _publish(EventType.SCENARIO_COMPLETED, result)

    return {
        "messages": new_messages,
        "scenario_queue": queue,
        "scenario_results": [result],
    }


def scenario_loop_router(state: AgentState) -> str:
    if state.get("scenario_queue"):
        return "run_scenario_loop"
    return "observe"


async def act(state: AgentState) -> dict:
    instruction = (
        f"Hypothesis: {state.get('hypothesis')}\n"
        f"Environment id: {state.get('environment_id')}\n"
        "Take the next concrete action(s) to test this hypothesis in the environment."
    )
    new_messages = await run_tool_loop(state.get("messages") or [], ALL_TOOLS, instruction)
    return {"messages": new_messages}


async def observe(state: AgentState) -> dict:
    instruction = (
        "Based on everything observed so far (including any per-scenario results), do you "
        "need more tool calls to gather evidence before judging the hypothesis, or is it "
        "time to verify?"
    )
    observer = get_llm().with_structured_output(ObserveDecision)
    decision: ObserveDecision = await observer.ainvoke((state.get("messages") or []) + [HumanMessage(content=instruction)])

    attempts = state.get("observe_attempts", 0)
    need_more = decision.need_more_action and attempts < MAX_OBSERVE_ATTEMPTS
    _publish(EventType.AGENT_THOUGHT, {"stage": "observe", "summary": decision.summary, "need_more_action": need_more})

    return {
        "messages": [AIMessage(content=f"Observation: {decision.summary}")],
        "need_more_action": need_more,
        "observe_attempts": attempts + 1,
    }


def observe_router(state: AgentState) -> str:
    return "act" if state.get("need_more_action") else "verify"


async def verify(state: AgentState) -> dict:
    instruction = (
        f"Hypothesis under test: {state.get('hypothesis')}\n"
        "Judge, using the concrete evidence gathered (logs/db/metrics/diffs), whether the "
        "hypothesis is confirmed (the bug reproduced and, if a fix was applied, the fix "
        "resolves it) or denied."
    )
    verifier = get_llm().with_structured_output(VerifyDecision)
    decision: VerifyDecision = await verifier.ainvoke((state.get("messages") or []) + [HumanMessage(content=instruction)])

    _publish(EventType.VERIFY_RESULT, {"confirmed": decision.confirmed, "reasoning": decision.reasoning})

    return {
        "messages": [AIMessage(content=f"Verify: confirmed={decision.confirmed}. {decision.reasoning}")],
        "verified": decision.confirmed,
        "verify_reasoning": decision.reasoning,
        "final_answer": decision.final_answer,
    }


def verify_router(state: AgentState) -> str:
    if state.get("verified"):
        return "respond"
    if state.get("iteration_count", 0) < state.get("max_iterations", settings.max_iterations):
        return "hypothesize"
    return "escalate"


async def respond(state: AgentState) -> dict:
    answer = state.get("final_answer") or state.get("verify_reasoning") or "Done."
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
            "reason": "Exhausted the experiment-loop iteration budget without confirming the hypothesis.",
            "hypothesis": state.get("hypothesis"),
            "last_verify_reasoning": state.get("verify_reasoning"),
            "scenario_results": state.get("scenario_results"),
        }
    )
    # Execution resumes here once the developer responds via Command(resume=...).
    return {
        "messages": [HumanMessage(content=str(guidance))],
        "iteration_count": 0,
        "verified": False,
        "done": False,
    }


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("classify_case", classify_case)
    graph.add_node("provision_environment", provision_environment)
    graph.add_node("hypothesize", hypothesize)
    graph.add_node("run_scenario_loop", run_scenario_loop)
    graph.add_node("act", act)
    graph.add_node("observe", observe)
    graph.add_node("verify", verify)
    graph.add_node("respond", respond)
    graph.add_node("escalate", escalate)

    graph.add_edge(START, "classify_case")
    graph.add_edge("classify_case", "provision_environment")
    graph.add_edge("provision_environment", "hypothesize")
    graph.add_conditional_edges("hypothesize", scenario_router, {"run_scenario_loop": "run_scenario_loop", "act": "act"})
    graph.add_conditional_edges("run_scenario_loop", scenario_loop_router, {"run_scenario_loop": "run_scenario_loop", "observe": "observe"})
    graph.add_edge("act", "observe")
    graph.add_conditional_edges("observe", observe_router, {"act": "act", "verify": "verify"})
    graph.add_conditional_edges("verify", verify_router, {"respond": "respond", "hypothesize": "hypothesize", "escalate": "escalate"})
    graph.add_edge("respond", END)
    graph.add_edge("escalate", "hypothesize")

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


def _print_graph(compiled) -> None:
    """Print the compiled graph structure to stdout on startup.

    `draw_ascii` (via the optional `grandalf` package) can crash on graphs with
    self-loops/cycles like ours, so we use the always-reliable Mermaid text form.
    """
    print("\n=== Praxis Lens agent graph ===")
    print(compiled.get_graph().draw_mermaid())
    print("=== (paste into https://mermaid.live to visualize) ===\n")


praxis_graph = build_graph()
_print_graph(praxis_graph)
