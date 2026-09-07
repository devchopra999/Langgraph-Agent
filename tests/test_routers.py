"""Unit tests for the graph's pure routing functions (no LLM/network calls needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis_agent.agent.graph import (
    observe_router,
    scenario_loop_router,
    scenario_router,
    verify_router,
)


def test_scenario_router_goes_to_scenario_loop_when_needed():
    state = {"needs_scenario_iteration": True, "scenario_queue": [{"name": "a"}]}
    assert scenario_router(state) == "run_scenario_loop"


def test_scenario_router_goes_to_act_when_no_scenarios():
    assert scenario_router({"needs_scenario_iteration": True, "scenario_queue": []}) == "act"
    assert scenario_router({"needs_scenario_iteration": False, "scenario_queue": [{"x": 1}]}) == "act"


def test_scenario_loop_router_continues_while_queue_nonempty():
    assert scenario_loop_router({"scenario_queue": [{"a": 1}]}) == "run_scenario_loop"
    assert scenario_loop_router({"scenario_queue": []}) == "observe"


def test_observe_router():
    assert observe_router({"need_more_action": True}) == "act"
    assert observe_router({"need_more_action": False}) == "verify"


def test_verify_router_confirmed_goes_to_respond():
    assert verify_router({"verified": True, "iteration_count": 1, "max_iterations": 6}) == "respond"


def test_verify_router_denied_with_budget_loops_back():
    assert verify_router({"verified": False, "iteration_count": 2, "max_iterations": 6}) == "hypothesize"


def test_verify_router_denied_budget_exhausted_escalates():
    assert verify_router({"verified": False, "iteration_count": 6, "max_iterations": 6}) == "escalate"


if __name__ == "__main__":
    import inspect

    fns = [obj for name, obj in list(globals().items()) if name.startswith("test_") and inspect.isfunction(obj)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
