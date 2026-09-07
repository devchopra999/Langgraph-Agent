"""Reusable ReAct-style tool-calling micro-loop.

Several graph nodes (`provision_environment`, `act`, each `run_scenario_loop` iteration) all
need the same shape of work: "given the conversation so far plus a specific instruction, let
the LLM call tools as many times as it needs (bounded), then stop once it responds with plain
text." This helper implements that once so the graph nodes stay small and declarative.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool

from praxis_agent.agent.context import get_current_bus, set_current_reason
from praxis_agent.agent.events import EventType
from praxis_agent.agent.llm import get_llm

MAX_TOOL_LOOP_STEPS = 8
DEFAULT_TOOL_CALL_REASON = "No explicit reasoning was given for this tool call."


async def run_tool_loop(
    messages: list,
    tools: list[BaseTool],
    instruction: str,
    *,
    max_steps: int = MAX_TOOL_LOOP_STEPS,
) -> list:
    """Runs an agent<->tools loop starting from `messages` + a new instruction message.

    Returns the list of NEW messages produced (instruction message, AI messages, tool
    messages) — the caller is responsible for merging these into the shared graph state via
    the `add_messages` reducer.
    """
    llm_with_tools = get_llm().bind_tools(tools)
    tools_by_name = {t.name: t for t in tools}

    new_messages: list = [HumanMessage(content=instruction)]
    working_messages = messages + new_messages

    for _ in range(max_steps):
        ai_msg: AIMessage = await llm_with_tools.ainvoke(working_messages)
        new_messages.append(ai_msg)
        working_messages.append(ai_msg)

        if not ai_msg.tool_calls:
            break

        # The LLM is instructed (see BASE_SYSTEM_PROMPT) to always explain, in its message
        # content, why it's about to call the upcoming tool(s). Surface that reasoning as its
        # own event and thread it through to each tool call so the TUI/SSE feed can show
        # "why", not just "what", for everything the agent does.
        reason = (ai_msg.content or "").strip() if isinstance(ai_msg.content, str) else ""
        reason = reason or DEFAULT_TOOL_CALL_REASON
        bus = get_current_bus()
        if bus:
            bus.publish(
                EventType.AGENT_THOUGHT,
                {"stage": "acting", "reason": reason, "tools": [tc["name"] for tc in ai_msg.tool_calls]},
            )

        for tool_call in ai_msg.tool_calls:
            tool_obj = tools_by_name.get(tool_call["name"])
            set_current_reason(reason)
            try:
                if tool_obj is None:
                    tool_result = f"ERROR: unknown tool '{tool_call['name']}'"
                else:
                    try:
                        tool_result = await tool_obj.ainvoke(tool_call["args"])
                    except Exception as exc:  # noqa: BLE001
                        tool_result = f"ERROR calling {tool_call['name']}: {exc}"
            finally:
                set_current_reason(None)
            tool_msg = ToolMessage(content=str(tool_result), tool_call_id=tool_call["id"])
            new_messages.append(tool_msg)
            working_messages.append(tool_msg)

    return new_messages
