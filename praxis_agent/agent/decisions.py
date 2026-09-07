"""Pydantic schemas used with `llm.with_structured_output(...)` for deterministic routing
decisions inside the graph (case classification, hypothesis/scenario planning, observe/verify
judgements) — this is what makes the conditional edges real branches instead of regex-parsing
free text out of the LLM."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

CaseType = Literal[
    "mock_based_testing",
    "feature_branch_testing",
    "performance_testing",
    "production_repro",
    "hotfix_testing",
    "concurrency_testing",
    "general_debug",
]


class CaseClassification(BaseModel):
    case_type: CaseType = Field(description="Which workflow shape best fits the developer's goal.")
    needs_scenario_iteration: bool = Field(
        description=(
            "True if this goal naturally requires trying multiple scenarios in a loop "
            "(e.g. mock-based testing across several dependency responses, concurrency "
            "testing across several concurrency levels, A/B branch comparison). False for "
            "a single-shot investigation (e.g. general debugging, one-off repro, hotfix check)."
        )
    )
    initial_skill_hints: list[str] = Field(
        default_factory=list,
        description="Skill names (see list_skills) likely relevant to this case type, to consider loading early.",
    )
    reasoning: str = Field(description="One or two sentences explaining the classification.")


class HypothesisPlan(BaseModel):
    hypothesis: str = Field(description="The current best hypothesis about the root cause / what to test.")
    scenario_queue: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Only for iterator cases: a list of scenario descriptors to try one at a time, "
            "e.g. [{\"name\": \"axis-500\", \"response_name\": \"axis-500\"}, ...] or "
            "[{\"name\": \"concurrency-10\", \"parallelism\": 10}, ...]. Leave empty for "
            "single-shot cases."
        ),
    )
    plan_note: str = Field(description="What the very next concrete action should be, in plain language.")


class ObserveDecision(BaseModel):
    need_more_action: bool = Field(
        description="True if more tool calls are needed before you have enough evidence to verify the hypothesis."
    )
    summary: str = Field(description="Concise summary of what has been observed so far.")


class VerifyDecision(BaseModel):
    confirmed: bool = Field(description="True if the evidence gathered confirms the hypothesis / the fix works.")
    reasoning: str = Field(description="Why, citing specific evidence (logs/db/metrics/diff observed).")
    final_answer: Optional[str] = Field(
        default=None, description="If confirmed, a developer-facing summary of root cause + fix + verification."
    )


class EnvironmentRef(BaseModel):
    environment_id: Optional[str] = Field(
        default=None,
        description="The environmentId created/used so far in this conversation, if any (look for values like 'env-xxxxxx').",
    )


class ScenarioOutcome(BaseModel):
    passed: Optional[bool] = Field(description="Whether this specific scenario behaved as expected, if determinable.")
    summary: str = Field(description="Concise evidence-based summary of what happened for this scenario.")
