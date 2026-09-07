"""LLM factory shared across the graph's nodes."""
from __future__ import annotations

from typing import Union

from langchain_openai import ChatOpenAI

from praxis_agent.config import settings

_ChatModel = Union[ChatOpenAI, "ChatBedrockConverse"]

_llm: _ChatModel | None = None


def _build_bedrock_llm() -> "ChatBedrockConverse":
    # Imported lazily so the (optional) langchain-aws/boto3 dependency is only required
    # when LLM_PROVIDER=bedrock is actually selected.
    from langchain_aws import ChatBedrockConverse

    # Authenticate with a plain IAM user access key / secret key pair (no SSO or
    # instance-profile assumption, so no session token is needed). Credentials are passed
    # explicitly rather than relying on the default boto3 credential chain, so they must
    # come from Settings/env vars.
    return ChatBedrockConverse(
        model=settings.bedrock_model,
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        temperature=0.2,
    )


def get_llm() -> _ChatModel:
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
        elif settings.llm_provider == "bedrock":
            _llm = _build_bedrock_llm()
        else:
            _llm = ChatOpenAI(model=settings.openai_model, api_key=settings.openai_api_key, temperature=0.2)

    return _llm
