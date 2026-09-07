"""Shared agent state for the Praxis Lens LangGraph graph."""
from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ScenarioResult(TypedDict, total=False):
    scenario: dict[str, Any]
    summary: str
    passed: Optional[bool]


class AgentState(TypedDict, total=False):
    # Conversation — shared across every node so the LLM keeps full context of what's
    # happened (classification, hypotheses, tool calls, evidence, and assessments).
    messages: Annotated[list[BaseMessage], add_messages]

    # Session bookkeeping
    session_id: str
    goal: str
    environment_id: Optional[str]

    # classify_case output
    case_type: Optional[str]
    workflow: str
    fix_requested: bool
    skill_hints: list[str]
    needs_scenario_iteration: bool

    # environment planning/discovery output
    environment_plan: dict[str, Any]

    # experiment-planning output
    hypothesis: Optional[str]
    scenario_queue: list[dict[str, Any]]
    active_scenario: dict[str, Any]
    scenario_results: list[dict[str, Any]]

    # experiment loop guards
    iteration_count: int
    max_iterations: int
    remediation_attempted: bool

    # evidence assessment outputs
    verified: Optional[bool]
    verify_reasoning: Optional[str]
    assessment_next_step: Optional[str]

    # terminal
    done: bool
    final_answer: Optional[str]
