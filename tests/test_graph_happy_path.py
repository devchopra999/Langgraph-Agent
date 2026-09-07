"""End-to-end smoke test for the generic evidence-first workflow."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
        # No tool calls -> run_tool_loop exits immediately after one AI message.
        return AIMessage(content="ok, nothing more to do")


class FakeLLM:
    """Returns canned structured-output responses keyed by schema class, and a no-tool-call
    response for bind_tools(), so the tool-calling micro-loop terminates immediately."""

    def __init__(self):
        self._responses = {
            CaseClassification: CaseClassification(
                case_type="general_debug",
                needs_scenario_iteration=False,
                initial_skill_hints=[],
                reasoning="test",
            ),
            EnvironmentPlan: EnvironmentPlan(services=["edi"], reasoning="EDI is under test."),
            EnvironmentRef: EnvironmentRef(environment_id="env-test123"),
            HypothesisPlan: HypothesisPlan(
                hypothesis="the bug is X",
                scenario_queue=[
                    ExperimentScenario(
                        name="reproduce",
                        setup="none",
                        trigger="call the EDI endpoint",
                        expected_evidence=["an EDI error log"],
                    )
                ],
                plan_note="run the reported request",
            ),
            ScenarioOutcome: ScenarioOutcome(passed=True, summary="the requested evidence was collected"),
            EvidenceAssessment: EvidenceAssessment(
                next_step="respond", reasoning="logs confirm it", final_answer="Issue replicated."
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
            {"goal": "Reproduce and fix the widget bug", "session_id": "test-session", "messages": []},
            config={"configurable": {"thread_id": "test-thread-happy-path"}},
        )

    assert result["done"] is True, result
    assert result["verified"] is True
    assert result["environment_id"] == "env-test123"
    assert "Issue replicated." in (result.get("final_answer") or "")
    assert len(result["scenario_results"]) == 1
    contents = [str(message.content) for message in result["messages"]]
    discovery_index = next(index for index, content in enumerate(contents) if "read-only runtime inventory" in content)
    experiment_index = next(index for index, content in enumerate(contents) if "generic experiment scenario" in content)
    assert discovery_index < experiment_index
    print("PASS: generic evidence-first graph run reached respond/END with expected state")
    print({k: result[k] for k in ("case_type", "hypothesis", "environment_id", "verified", "final_answer")})


if __name__ == "__main__":
    asyncio.run(main())
