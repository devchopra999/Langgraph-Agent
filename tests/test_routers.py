"""Unit tests for the graph's pure workflow-routing functions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis_agent.agent.graph import (
    assessment_router,
    plan_router,
    provision_router,
    _workflow_node,
)
from praxis_agent.tools import ALL_TOOLS, EDIT_TOOLS, EXPERIMENT_TOOLS, MOCK_CONTRACT_TOOLS, PERFORMANCE_TOOLS


def test_workflow_router_selects_specialists_and_generic_fallback():
    assert _workflow_node({"workflow": "mock_contract"}) == "mock_contract_workflow"
    assert _workflow_node({"workflow": "performance"}) == "performance_workflow"
    assert _workflow_node({"workflow": "unknown-future-case"}) == "generic_experiment_workflow"


def test_provision_router_requires_environment_before_discovery():
    assert provision_router({"environment_id": "env-123"}) == "discover_environment"
    assert provision_router({"environment_id": None}) == "escalate"


def test_plan_router_uses_generic_fallback_and_escalates_without_safe_scenario():
    assert plan_router({"workflow": "generic_experiment", "scenario_queue": [{"name": "a"}]}) == "generic_experiment_workflow"
    assert plan_router({"workflow": "performance", "scenario_queue": [{"name": "a"}]}) == "performance_workflow"
    assert plan_router({"workflow": "generic_experiment", "scenario_queue": []}) == "escalate"


def test_assessment_router_drains_scenarios_before_concluding():
    assert assessment_router(
        {
            "workflow": "generic_experiment",
            "scenario_queue": [{"name": "next"}],
            "assessment_next_step": "respond",
        }
    ) == "generic_experiment_workflow"


def test_assessment_router_only_edits_after_explicit_fix_request():
    base = {"scenario_queue": [], "assessment_next_step": "diagnose", "iteration_count": 1, "max_iterations": 6}
    assert assessment_router({**base, "fix_requested": True, "remediation_attempted": False}) == "diagnose"
    assert assessment_router({**base, "fix_requested": False, "remediation_attempted": False}) == "plan_experiments"


def test_experiment_workflows_cannot_edit_source():
    assert EDIT_TOOLS[0].name == "code_edit"
    for tools in (EXPERIMENT_TOOLS, MOCK_CONTRACT_TOOLS, PERFORMANCE_TOOLS):
        assert "code_edit" not in {tool.name for tool in tools}


def test_load_test_is_available_only_to_performance_workflow():
    assert "run_load_test" in {tool.name for tool in ALL_TOOLS}
    assert "run_load_test" in {tool.name for tool in PERFORMANCE_TOOLS}
    assert "run_load_test" not in {tool.name for tool in EXPERIMENT_TOOLS}
    assert "run_load_test" not in {tool.name for tool in MOCK_CONTRACT_TOOLS}


def test_assessment_router_escalates_at_budget_limit():
    assert assessment_router(
        {
            "scenario_queue": [],
            "assessment_next_step": "replan",
            "iteration_count": 6,
            "max_iterations": 6,
        }
    ) == "escalate"


if __name__ == "__main__":
    import inspect

    fns = [obj for name, obj in list(globals().items()) if name.startswith("test_") and inspect.isfunction(obj)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
