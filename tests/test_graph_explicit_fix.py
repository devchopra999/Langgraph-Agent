"""Smoke test for the explicit-fix-only remediation and replay path."""
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
        scenario = ExperimentScenario(
            name="reported-failure",
            setup="none",
            trigger="call the wrapper endpoint",
            expected_evidence=["failure log"],
        )
        self._responses = {
            CaseClassification: CaseClassification(
                case_type="hotfix_testing",
                workflow="generic_experiment",
                fix_requested=True,
                needs_scenario_iteration=False,
                initial_skill_hints=[],
                reasoning="the developer explicitly requested a fix",
            ),
            EnvironmentPlan: EnvironmentPlan(services=["edi"], reasoning="EDI is under test."),
            EnvironmentRef: EnvironmentRef(environment_id="env-fix123"),
            HypothesisPlan: HypothesisPlan(
                hypothesis="the wrapper dereferences a missing response",
                scenario_queue=[scenario],
                plan_note="reproduce the missing response",
            ),
            ScenarioOutcome: ScenarioOutcome(passed=False, summary="failure reproduced"),
        }
        self._assessments = [
            EvidenceAssessment(next_step="diagnose", reasoning="failure evidence confirms the defect"),
            EvidenceAssessment(next_step="respond", reasoning="the replay passed after the fix", final_answer="Fixed."),
        ]

    def with_structured_output(self, schema, **_kwargs):
        if schema is EvidenceAssessment:
            return FakeStructured(self._assessments.pop(0))
        return FakeStructured(self._responses[schema])


async def main():
    import praxis_agent.agent.graph as graph_module

    fake_llm = FakeLLM()
    tool_sets: list[set[str]] = []

    async def fake_tool_loop(_messages, tools, _instruction, **_kwargs):
        tool_sets.append({tool.name for tool in tools})
        return [AIMessage(content="phase complete")]

    with patch.object(graph_module, "get_llm", return_value=fake_llm), patch.object(
        graph_module, "run_tool_loop", side_effect=fake_tool_loop
    ):
        graph = graph_module.build_graph()
        result = await graph.ainvoke(
            {"goal": "Reproduce and fix the wrapper failure", "session_id": "explicit-fix", "messages": []},
            config={"configurable": {"thread_id": "explicit-fix-thread"}},
        )

    edit_index = next(index for index, tools in enumerate(tool_sets) if tools == {"code_edit"})
    diagnosis_index = next(index for index, tools in enumerate(tool_sets) if tools == {"code_ask"})
    assert diagnosis_index < edit_index
    assert result["done"] is True
    assert result["remediation_attempted"] is True
    assert len(result["scenario_results"]) == 2
    assert result["scenario_results"][0]["scenario"] == result["scenario_results"][1]["scenario"]
    print("PASS: explicit fix ran diagnosis, edit, deploy, and an identical replay")


if __name__ == "__main__":
    asyncio.run(main())
