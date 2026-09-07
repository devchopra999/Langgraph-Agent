"""Pydantic schemas for deterministic graph planning and evidence-assessment decisions."""
from __future__ import annotations

from typing import Literal, Optional

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

WorkflowKind = Literal["mock_contract", "performance", "generic_experiment"]


class CaseClassification(BaseModel):
    case_type: CaseType = Field(description="Which workflow shape best fits the developer's goal.")
    workflow: WorkflowKind = Field(
        default="generic_experiment",
        description=(
            "The execution path: mock_contract for external dependency contract testing, "
            "performance for load/resource investigation, or generic_experiment for all other "
            "debugging/testing cases and future workflows."
        ),
    )
    fix_requested: bool = Field(
        default=False,
        description="True only when the developer explicitly asks to modify or fix source code.",
    )
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
    scenario_queue: list["ExperimentScenario"] = Field(
        default_factory=list,
        description=(
            "Ordered scenarios to try one at a time. Each retains its setup, exact trigger, "
            "and expected evidence so it can be replayed after an explicitly requested code fix."
        ),
    )
    plan_note: str = Field(description="What the very next concrete action should be, in plain language.")
    run_previous_qa_flows: bool = Field(
        default=False,
        description=(
            "True only if the developer explicitly also wants the target service's existing QA "
            "flows triggered by the same Experiment API call. Only consulted on the first "
            "plan_experiments pass of an investigation; ignored on replans since the value is "
            "decided once and reused thereafter."
        ),
    )


class ExperimentScenario(BaseModel):
    name: str = Field(description="Short, unique name for this scenario.")
    setup: str = Field(
        description="Required configuration, external mock setup, or load preconditions; use 'none' if not needed."
    )
    trigger: str = Field(description="Exact API call, command, or load action to execute.")
    expected_evidence: list[str] = Field(
        default_factory=list,
        description="Logs, database changes, responses, or metrics that determine the scenario outcome.",
    )


class EnvironmentPlan(BaseModel):
    services: list[str] = Field(
        default_factory=list,
        description="Minimal executor catalog services to provision. Never include an external mock server or databases.",
    )
    environment_required: bool = Field(
        default=True,
        description=(
            "False only when the entire goal targets an already-running, fully external service "
            "(nothing to start, stop, or modify locally) — e.g. testing a hypothesis against a "
            "live external API via the Experiment API. True otherwise, including whenever any "
            "services are requested."
        ),
    )
    branch_services: list["ServiceBranch"] = Field(
        default_factory=list,
        description="Services that must be started from a requested branch after the environment exists.",
    )
    repository: Optional["RepositoryRef"] = Field(
        default=None,
        description="Optional HTTPS repository URL and exact commit for executor workspace checkout.",
    )
    reasoning: str = Field(description="Why these services and source revisions are needed.")


class ServiceBranch(BaseModel):
    service: str = Field(description="Executor catalog service name.")
    branch: str = Field(description="Requested branch to build and start for this service.")


class RepositoryRef(BaseModel):
    url: str = Field(description="HTTPS repository URL.")
    commit: str = Field(description="Exact commit or revision to check out.")


class EnvironmentRef(BaseModel):
    environment_id: Optional[str] = Field(
        default=None,
        description="The environmentId created/used so far in this conversation, if any (look for values like 'env-xxxxxx').",
    )


class ScenarioOutcome(BaseModel):
    passed: Optional[bool] = Field(description="Whether this specific scenario behaved as expected, if determinable.")
    summary: str = Field(description="Concise evidence-based summary of what happened for this scenario.")


class EvidenceAssessment(BaseModel):
    next_step: Literal["next_scenario", "replan", "diagnose", "respond", "escalate"] = Field(
        description=(
            "next_scenario for another queued experiment, replan for a new hypothesis, diagnose "
            "when the defect is evidenced and an explicitly requested fix should be prepared, "
            "respond when the requested investigation is conclusively complete, or escalate when "
            "a safe experiment requires user input."
        )
    )
    reasoning: str = Field(description="Evidence-based rationale for the chosen next step.")
    final_answer: Optional[str] = Field(
        default=None,
        description="Developer-facing conclusion when next_step is respond.",
    )
