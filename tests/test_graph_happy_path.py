"""End-to-end smoke test of the compiled graph with a fully mocked LLM and mocked tools —
validates the classify -> provision -> hypothesize -> act -> observe -> verify -> respond
wiring works without needing a real OpenAI key or a live execution service.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage

from praxis_agent.agent.decisions import (
    CaseClassification,
    EnvironmentRef,
    HypothesisPlan,
    ObserveDecision,
    VerifyDecision,
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
            EnvironmentRef: EnvironmentRef(environment_id="env-test123"),
            HypothesisPlan: HypothesisPlan(
                hypothesis="the bug is X", scenario_queue=[], plan_note="do the thing"
            ),
            ObserveDecision: ObserveDecision(need_more_action=False, summary="enough evidence"),
            VerifyDecision: VerifyDecision(confirmed=True, reasoning="logs confirm it", final_answer="Fixed X."),
        }

    def bind_tools(self, _tools):
        return FakeToolBound()

    def with_structured_output(self, schema):
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
    assert "Fixed X." in (result.get("final_answer") or "")
    print("PASS: happy path graph run reached respond/END with expected state")
    print({k: result[k] for k in ("case_type", "hypothesis", "environment_id", "verified", "final_answer")})


if __name__ == "__main__":
    asyncio.run(main())
