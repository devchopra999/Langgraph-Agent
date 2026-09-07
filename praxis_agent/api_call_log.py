"""Logs every outbound HTTP call made to the Execution Service / Mock Server to a file, so
you can see exactly which API was called, with what request body, and what came back —
useful for debugging the agent's behavior independent of the SSE event stream.

Writes JSON lines (one call per line) to PRAXIS_API_LOG_FILE (default ./logs/api_calls.log).
Also mirrors to a human-readable rotating text line for quick tailing.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_LOG_PATH = Path(os.environ.get("PRAXIS_API_LOG_FILE", "logs/api_calls.log")).resolve()
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_api_call(
    *,
    client: str,
    method: str,
    url: str,
    request_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    status_code: int | None = None,
    response_body: Any = None,
    error: str | None = None,
    duration_ms: float | None = None,
) -> None:
    entry = {
        "ts": time.time(),
        "iso_ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "client": client,  # "execution_service" | "mock_server"
        "method": method,
        "url": url,
        "request_body": request_body,
        "params": params,
        "status_code": status_code,
        "response_body": response_body,
        "error": error,
        "duration_ms": duration_ms,
    }
    line = json.dumps(entry, default=str)
    with _LOG_PATH.open("a") as f:
        f.write(line + "\n")
