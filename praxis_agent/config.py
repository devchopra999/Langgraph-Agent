"""Central configuration for the Praxis Lens LangGraph agent.

All values are read from environment variables (loaded from a local .env file if present)
so nothing sensitive is hard-coded and the mock-server URL can be supplied later without
a code change.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class Settings:
    # LLM
    # LLM_PROVIDER selects which backend `get_llm()` builds: "openai" (default), "ollama", or "bedrock".
    llm_provider: str = os.environ.get("LLM_PROVIDER", "openai").strip().lower()
    openai_api_key: str = os.environ.get("OPENAI_API_KEY", "")
    openai_model: str = os.environ.get("OPENAI_MODEL", "gpt-4o")

    # Ollama (used when LLM_PROVIDER=ollama); talks the OpenAI-compatible API Ollama exposes.
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1/")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "gemma-4-31b-cloud")
    ollama_api_key: str = os.environ.get("OLLAMA_API_KEY", "ollama")

    # AWS Bedrock (used when LLM_PROVIDER=bedrock); authenticates with a plain IAM user
    # access key / secret key pair (no SSO/instance-profile/session token needed).
    bedrock_model: str = os.environ.get(
        "BEDROCK_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0"
    )
    aws_region: str = os.environ.get("AWS_REGION", "us-east-1")
    aws_access_key_id: str = os.environ.get("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

    # Downstream services
    execution_service_url: str = os.environ.get("EXECUTION_SERVICE_URL", "http://localhost:3000").rstrip("/")
    mock_server_url: str = os.environ.get("MOCK_SERVER_URL", "").rstrip("/")

    # FastAPI server
    host: str = os.environ.get("PRAXIS_AGENT_HOST", "0.0.0.0")
    port: int = _int_env("PRAXIS_AGENT_PORT", 8000)

    # Experiment loop guard rails
    max_iterations: int = _int_env("PRAXIS_MAX_ITERATIONS", 6)

    # Execution trace reports
    report_dir: str = os.environ.get("PRAXIS_REPORT_DIR", "logs/reports")

    # Execution-service async job polling
    job_poll_interval_sec: float = float(os.environ.get("PRAXIS_JOB_POLL_INTERVAL_SEC", "2"))
    job_poll_timeout_sec: float = float(os.environ.get("PRAXIS_JOB_POLL_TIMEOUT_SEC", "300"))
    # create_environment provisions multiple services from scratch (image pulls/builds), so it
    # gets a longer dedicated timeout than a single service start/stop/restart.
    job_poll_timeout_sec_create_environment: float = float(
        os.environ.get("PRAXIS_JOB_POLL_TIMEOUT_SEC_CREATE", "600")
    )


settings = Settings()
