"""Verifies run_previous_qa_flows is decided once during the first plan_experiments pass,
threaded verbatim (as a literal boolean) into every workflow node's run_experiment instruction,
and reused unchanged on a later replan even though the LLM's second HypothesisPlan answer
disagrees with the first.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage

from praxis_agent.agent.decisions import (
    CaseClassification,
    EnvironmentPlan,
    EnvironmentRef,
    EvidenceAssessment,
    ExperimentScenario,
    HypothesisPlan,
    ScenarioOutcome,
)


class FakeStructured:
    def __init__(self, value):
        self._value = value

    async def ainvoke(self, _messages):
        return self._value


class FakeLLM:
    def __init__(self):
        self._responses = {
            CaseClassification: CaseClassification(
                case_type="general_debug",
                workflow="generic_experiment",
                fix_requested=False,
                needs_scenario_iteration=False,
                initial_skill_hints=[],
                reasoning="t",
            ),
            EnvironmentPlan: EnvironmentPlan(services=["edi"], reasoning="EDI is under test."),
            EnvironmentRef: EnvironmentRef(environment_id="env-flag1"),
            ScenarioOutcome: ScenarioOutcome(passed=True, summary="ok"),
        }
        self._hypothesis_plans = [
            HypothesisPlan(
                hypothesis="h1",
                scenario_queue=[ExperimentScenario(name="s1", setup="none", trigger="t1", expected_evidence=["e1"])],
                plan_note="first pass",
                run_previous_qa_flows=True,
            ),
            HypothesisPlan(
                hypothesis="h2",
                scenario_queue=[ExperimentScenario(name="s2", setup="none", trigger="t2", expected_evidence=["e2"])],
                plan_note="replan",
                # Deliberately disagrees with the first decision to prove it is NOT re-derived.
                run_previous_qa_flows=False,
            ),
        ]
        self._assessments = [
            EvidenceAssessment(next_step="replan", reasoning="need another angle"),
            EvidenceAssessment(next_step="respond", reasoning="done", final_answer="Done."),
        ]

    def with_structured_output(self, schema, **_kwargs):
        if schema is HypothesisPlan:
            return FakeStructured(self._hypothesis_plans.pop(0))
        if schema is EvidenceAssessment:
            return FakeStructured(self._assessments.pop(0))
        return FakeStructured(self._responses[schema])


async def main():
    import praxis_agent.agent.graph as graph_module

    fake_llm = FakeLLM()
    experiment_instructions: list[str] = []

    async def fake_tool_loop(_messages, tools, instruction, **_kwargs):
        if any(tool.name == "run_experiment" for tool in tools):
            experiment_instructions.append(instruction)
        return [AIMessage(content="phase complete")]

    with patch.object(graph_module, "get_llm", return_value=fake_llm), patch.object(
        graph_module, "run_tool_loop", side_effect=fake_tool_loop
    ):
        graph = graph_module.build_graph()
        result = await graph.ainvoke(
            {"goal": "Test a hypothesis twice", "session_id": "flag-session", "messages": []},
            config={"configurable": {"thread_id": "flag-thread"}},
        )

    assert result["done"] is True
    assert result["run_previous_qa_flows"] is True, "stored flag must stay at its first-decided value"
    assert len(experiment_instructions) == 2, experiment_instructions

    for instruction in experiment_instructions:
        assert "run_experiment" in instruction
        assert "run_previous_qa_flows is fixed at True" in instruction
        assert "run_previous_qa_flows is fixed at False" not in instruction

    print("PASS: run_previous_qa_flows decided once and reused verbatim across a replan")


if __name__ == "__main__":
    asyncio.run(main())
