"""Shared agent state for the Praxis Lens LangGraph graph."""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ScenarioResult(TypedDict, total=False):
    scenario: dict[str, Any]
    summary: str
    passed: Optional[bool]


class AgentState(TypedDict, total=False):
    # Conversation — shared across every node so the LLM keeps full context of what's
    # happened (classification, hypotheses, tool calls, observations, verifications).
    messages: Annotated[list[BaseMessage], add_messages]

    # Session bookkeeping
    session_id: str
    goal: str
    environment_id: Optional[str]

    # classify_case output
    case_type: Optional[str]
    skill_hints: list[str]
    needs_scenario_iteration: bool

    # hypothesize output
    hypothesis: Optional[str]
    scenario_queue: list[dict[str, Any]]
    scenario_results: Annotated[list[dict[str, Any]], operator.add]

    # experiment loop guards
    iteration_count: int
    max_iterations: int
    observe_attempts: int

    # observe/verify outputs
    need_more_action: bool
    verified: Optional[bool]
    verify_reasoning: Optional[str]

    # terminal
    done: bool
    final_answer: Optional[str]
