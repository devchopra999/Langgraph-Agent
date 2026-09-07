"""Smoke test for the specialist external mock-contract workflow."""
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


class FakeToolBound:
    async def ainvoke(self, _messages):
        return AIMessage(content="ok")


class FakeLLM:
    def __init__(self):
        self._responses = {
            CaseClassification: CaseClassification(
                case_type="mock_based_testing",
                workflow="mock_contract",
                needs_scenario_iteration=True,
                initial_skill_hints=["mock-based-testing"],
                reasoning="t",
            ),
            EnvironmentPlan: EnvironmentPlan(services=["edi"], reasoning="EDI is the wrapper under test."),
            EnvironmentRef: EnvironmentRef(environment_id="env-scenario1"),
            HypothesisPlan: HypothesisPlan(
                hypothesis="edi mishandles axis 500s",
                scenario_queue=[
                    ExperimentScenario(name="success", setup="mock 200", trigger="call wrapper", expected_evidence=["200 response"]),
                    ExperimentScenario(name="axis-500", setup="mock 500", trigger="call wrapper", expected_evidence=["error log"]),
                    ExperimentScenario(name="malformed", setup="mock malformed body", trigger="call wrapper", expected_evidence=["validation error"]),
                ],
                plan_note="run each mock scenario",
            ),
            ScenarioOutcome: ScenarioOutcome(passed=True, summary="handled correctly"),
            EvidenceAssessment: EvidenceAssessment(
                next_step="respond",
                reasoning="all 3 scenarios passed",
                final_answer="EDI handles all axis response variants.",
            ),
        }

    def bind_tools(self, _tools):
        return FakeToolBound()

    def with_structured_output(self, schema, **_kwargs):
        return FakeStructured(self._responses[schema])


async def main():
    with patch("praxis_agent.agent.llm.get_llm", return_value=FakeLLM()), patch(
        "praxis_agent.agent.tool_loop.get_llm", return_value=FakeLLM()
    ):
        from praxis_agent.agent.graph import build_graph

        graph = build_graph()
        result = await graph.ainvoke(
            {"goal": "Test EDI against all axis mock scenarios", "session_id": "s3", "messages": []},
            config={"configurable": {"thread_id": "test-thread-scenarios"}},
        )

    assert result["done"] is True
    assert result["scenario_queue"] == [], "queue should be fully drained"
    assert len(result["scenario_results"]) == 3, result["scenario_results"]
    assert result["verified"] is True
    print("PASS: scenario loop drained all 3 scenarios and reached a confirmed verify/respond")
    print("scenario_results:", result["scenario_results"])


if __name__ == "__main__":
    asyncio.run(main())
