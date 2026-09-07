"""Async HTTP client for the Experiment API.

The Experiment API is a dedicated execution engine that, given a hypothesis and context,
generates and runs test cases to evaluate that hypothesis and — when asked — also triggers
a service's existing QA flows in the same call. This client owns URL construction, request
serialization, timeouts, and error/response handling; it never fabricates a result and never
collapses the response's distinct layers (experiment status, testcases, assertions, hypothesis
evaluation, existing QA-flow results) into a single boolean.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from praxis_agent.api_call_log import log_api_call
from praxis_agent.config import settings

_SENSITIVE_KEYS = {"password", "secret", "token", "authorization", "apikey", "api_key", "access_token"}


def _redact(value: Any) -> Any:
    """Deep-copies `value`, replacing any dict value whose key looks sensitive with a
    placeholder so passwords/secrets never reach logs or traces."""
    if isinstance(value, dict):
        return {
            key: ("***REDACTED***" if key.lower() in _SENSITIVE_KEYS else _redact(val))
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class ExperimentApiError(RuntimeError):
    """Raised for network failures, non-2xx responses, or a malformed response contract."""

    def __init__(self, message: str, *, status_code: int | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}


class ExperimentClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.experiment_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.experiment_api_timeout_sec

    async def run_experiment(
        self,
        hypothesis: str,
        context: dict[str, Any],
        run_previous_qa_flows: bool,
    ) -> dict[str, Any]:
        """POST /api/v1/experiment — test `hypothesis` against `context`, optionally also
        triggering the service's existing QA flows in the same call. Returns the full response
        payload untouched (experiment status, testcases, assertions, hypothesis evaluation,
        evidence, generated plan, and EXISTING_QAFLOW_RESULTS when requested) so the caller can
        reason over every layer instead of a collapsed pass/fail."""
        body = {
            "hypothesis": hypothesis,
            "context": context,
            "runPreviousQaFlows": run_previous_qa_flows,
        }
        url = f"{self.base_url}/api/v1/experiment"
        started = time.monotonic()
        status_code: int | None = None
        response_body: Any = None
        error: str | None = None
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=body)
            status_code = resp.status_code
            try:
                parsed = resp.json()
            except ValueError:
                parsed = None

            if resp.status_code >= 400:
                response_body = _redact(parsed) if parsed is not None else resp.text
                message = (
                    (parsed or {}).get("error", {}).get("message")
                    if isinstance(parsed, dict)
                    else None
                ) or f"Experiment API returned HTTP {resp.status_code}"
                raise ExperimentApiError(message, status_code=resp.status_code, details=response_body if isinstance(response_body, dict) else {"body": response_body})

            if not isinstance(parsed, dict):
                response_body = _redact(parsed) if parsed is not None else resp.text
                raise ExperimentApiError(
                    "Experiment API returned a malformed (non-object) response body",
                    status_code=resp.status_code,
                    details={"body": response_body},
                )

            response_body = _redact(parsed)
            return parsed
        except httpx.RequestError as exc:
            error = f"{exc.__class__.__name__}: {exc}"
            raise ExperimentApiError(f"Experiment API request failed: {exc}") from exc
        except ExperimentApiError as exc:
            error = error or str(exc)
            raise
        finally:
            log_api_call(
                client="experiment_api",
                method="POST",
                url=url,
                request_body=_redact(body),
                status_code=status_code,
                response_body=response_body,
                error=error,
                duration_ms=(time.monotonic() - started) * 1000,
            )


experiment_client = ExperimentClient()
