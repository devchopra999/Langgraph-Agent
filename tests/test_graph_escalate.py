"""Smoke test for the escalate/interrupt path: forces every verify to deny until the
iteration budget is exhausted, confirms the graph pauses at `escalate` via LangGraph's
interrupt() rather than crashing or looping forever, and that resuming with Command(resume=)
continues the run.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage
from langgraph.types import Command

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
        return AIMessage(content="ok")


class FakeLLM:
    def __init__(self):
        self._responses = {
            CaseClassification: CaseClassification(
                case_type="general_debug", needs_scenario_iteration=False, initial_skill_hints=[], reasoning="t"
            ),
            EnvironmentRef: EnvironmentRef(environment_id="env-test999"),
            HypothesisPlan: HypothesisPlan(hypothesis="maybe X", scenario_queue=[], plan_note="try again"),
            ObserveDecision: ObserveDecision(need_more_action=False, summary="evidence gathered"),
            VerifyDecision: VerifyDecision(confirmed=False, reasoning="still failing", final_answer=None),
        }

    def bind_tools(self, _tools):
        return FakeToolBound()

    def with_structured_output(self, schema):
        return FakeStructured(self._responses[schema])


async def main():
    with patch("praxis_agent.agent.llm.get_llm", return_value=FakeLLM()), patch(
        "praxis_agent.agent.tool_loop.get_llm", return_value=FakeLLM()
    ), patch("praxis_agent.config.settings.max_iterations", 2):
        from praxis_agent.agent.graph import build_graph

        graph = build_graph()
        config = {"configurable": {"thread_id": "test-thread-escalate"}}
        result = await graph.ainvoke(
            {"goal": "Fix the flaky thing", "session_id": "test-session-2", "messages": []}, config=config
        )

        snapshot = await graph.aget_state(config)
        waiting = bool(snapshot.next) and any(getattr(t, "interrupts", None) for t in snapshot.tasks)
        assert waiting, f"expected graph to be paused at escalate, next={snapshot.next}"
        print("PASS: graph paused at escalate node awaiting human input, next =", snapshot.next)

        # Resume with human guidance; FakeLLM still always denies, so it should escalate
        # again rather than loop forever or crash.
        result2 = await graph.ainvoke(Command(resume="try checking the retry queue"), config=config)
        snapshot2 = await graph.aget_state(config)
        waiting2 = bool(snapshot2.next) and any(getattr(t, "interrupts", None) for t in snapshot2.tasks)
        assert waiting2, f"expected graph to be paused at escalate again, next={snapshot2.next}"
        print("PASS: resume worked and graph escalated again as expected (no infinite loop / crash)")


if __name__ == "__main__":
    asyncio.run(main())
