"""LLM factory shared across the graph's nodes."""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from praxis_agent.config import settings

_llm: ChatOpenAI | None = None


def get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        if settings.llm_provider == "ollama":
            # Ollama exposes an OpenAI-compatible API, so ChatOpenAI works as-is;
            # only the base_url/model/api_key differ.
            _llm = ChatOpenAI(
                model=settings.ollama_model,
                api_key=settings.ollama_api_key,
                base_url=settings.ollama_base_url,
                temperature=0.2,
            )
        else:
            _llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)

    return _llm
