"""Tool wrapping the Experiment API — a dedicated execution engine that generates and runs
hypothesis-driven test cases and, when asked, a service's existing QA flows.

This is the only place that talks to the Experiment API. The LLM must supply structured
arguments (hypothesis, context, run_previous_qa_flows); this module owns URL construction,
request/response handling, validation, and error classification so the model never needs to
construct a raw HTTP request itself.

`run_previous_qa_flows` must be explicit and is never re-derived here: when true, the
Experiment API is responsible for triggering the service's existing QA flows as part of this
same call — do not call any other tool to run those flows again, or they will execute twice.
"""
from __future__ import annotations

from typing import Any, Optional

from langchain_core.tools import tool

from praxis_agent.clients.experiment_client import experiment_client
from praxis_agent.tools._tool_utils import instrumented

_REQUIRED_CONTEXT_FIELDS = ("service", "endpoint", "method")
# The Experiment API validates `context` against a strict schema and 400s on unknown keys, so
# only these documented fields may ever be forwarded — anything else the LLM adds is dropped.
_ALLOWED_CONTEXT_FIELDS = ("service", "endpoint", "method", "requestExample", "knownFields")


def _validate(hypothesis: str, context: dict[str, Any]) -> None:
    if not hypothesis or not hypothesis.strip():
        raise ValueError("run_experiment requires a non-empty hypothesis.")
    if not isinstance(context, dict):
        raise ValueError("run_experiment requires context to be an object.")
    missing = [field for field in _REQUIRED_CONTEXT_FIELDS if not context.get(field)]
    if missing:
        raise ValueError(f"run_experiment context is missing required field(s): {missing}.")


def _filter_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key in _ALLOWED_CONTEXT_FIELDS}


@tool
@instrumented("run_experiment")
async def run_experiment(
    hypothesis: str,
    context: dict[str, Any],
    run_previous_qa_flows: bool = False,
) -> dict:
    """Test a hypothesis against a target API by calling the Experiment API
    (POST /api/v1/experiment). `context` must include service, endpoint, method, and should
    include requestExample and knownFields when available. Set run_previous_qa_flows=true only
    when the developer explicitly also wants the service's existing QA flows triggered in this
    same call — the Experiment API runs them for you; never call another tool to run them again.

    Returns the full response untouched, preserving every layer distinctly: experimentId,
    status, hypothesisResult, experiment/execution metadata, testcases, assertions,
    hypothesisEvaluation, evidence, generatedPlan, and (when requested) EXISTING_QAFLOW_RESULTS.
    A COMPLETED status does not mean the hypothesis was supported — always read
    hypothesisResult and the individual assertions/testcases to judge that. context accepts
    only service, endpoint, method, requestExample, knownFields — any other key (e.g. a
    scenario name/description) is dropped before the request is sent, since the API rejects
    unrecognized context keys."""
    _validate(hypothesis, context)
    return await experiment_client.run_experiment(hypothesis, _filter_context(context), run_previous_qa_flows)
