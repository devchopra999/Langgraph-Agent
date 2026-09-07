"""Client- and tool-level tests for the Experiment API integration (run_experiment)."""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import respx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from praxis_agent.clients.experiment_client import ExperimentClient, ExperimentApiError, _redact
from praxis_agent.tools.experiment_tools import run_experiment

FULL_RESPONSE = {
    "experimentId": "exp-123",
    "hypothesis": "the endpoint 500s on malformed payloads",
    "status": "COMPLETED",
    "hypothesisResult": "PARTIALLY_SUPPORTED",
    "experiment": {"type": "API", "testcaseIds": ["tc-1", "tc-2"]},
    "execution": {"durationMs": 42},
    "testcases": [{"id": "tc-1", "result": "PASSED"}, {"id": "tc-2", "result": "FAILED"}],
    "assertions": [{"testcaseId": "tc-2", "passed": False, "message": "expected 400, got 500"}],
    "hypothesisEvaluation": {"summary": "one of two testcases failed"},
    "evidence": [{"type": "log", "value": "500 Internal Server Error"}],
    "generatedPlan": {"steps": ["send malformed payload", "assert 400"]},
}

CONTEXT = {"service": "edi", "endpoint": "/submit", "method": "POST"}


def test_run_experiment_hypothesis_only():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(200, json={**FULL_RESPONSE, "EXISTING_QAFLOW_RESULTS": {}})
            )
            result = await client.run_experiment("h", CONTEXT, False)
        assert json.loads(route.calls[0].request.content)["runPreviousQaFlows"] is False
        assert result["hypothesisResult"] == "PARTIALLY_SUPPORTED"
        assert "EXISTING_QAFLOW_RESULTS" not in result or result["EXISTING_QAFLOW_RESULTS"] == {}

    asyncio.run(verify())


def test_run_experiment_with_previous_qa_flows_keeps_sections_distinct():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        payload = {
            **FULL_RESPONSE,
            "EXISTING_QAFLOW_RESULTS": {"flows": [{"name": "smoke", "passed": True}]},
        }
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(200, json=payload)
            )
            result = await client.run_experiment("h", CONTEXT, True)
        assert json.loads(route.calls[0].request.content)["runPreviousQaFlows"] is True
        assert result["testcases"] == FULL_RESPONSE["testcases"]
        assert result["EXISTING_QAFLOW_RESULTS"] == {"flows": [{"name": "smoke", "passed": True}]}
        # The two layers must never be merged into one list/section.
        assert result["testcases"] is not result["EXISTING_QAFLOW_RESULTS"]

    asyncio.run(verify())


def test_successful_response_preserves_every_documented_layer():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(200, json=FULL_RESPONSE)
            )
            result = await client.run_experiment("h", CONTEXT, False)
        for key in FULL_RESPONSE:
            assert result[key] == FULL_RESPONSE[key], key

    asyncio.run(verify())


def test_4xx_and_5xx_raise_structured_errors_with_status_code():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(400, json={"error": {"message": "unrecognized context key"}})
            )
            try:
                await client.run_experiment("h", CONTEXT, False)
                raise AssertionError("expected ExperimentApiError")
            except ExperimentApiError as exc:
                assert exc.status_code == 400
                assert "unrecognized context key" in str(exc)

        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/api/v1/experiment").mock(return_value=httpx.Response(500))
            try:
                await client.run_experiment("h", CONTEXT, False)
                raise AssertionError("expected ExperimentApiError")
            except ExperimentApiError as exc:
                assert exc.status_code == 500

    asyncio.run(verify())


def test_network_failure_raises_structured_error():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/api/v1/experiment").mock(side_effect=httpx.ConnectError("refused"))
            try:
                await client.run_experiment("h", CONTEXT, False)
                raise AssertionError("expected ExperimentApiError")
            except ExperimentApiError as exc:
                assert "request failed" in str(exc).lower()

    asyncio.run(verify())


def test_malformed_non_object_response_is_rejected():
    async def verify():
        client = ExperimentClient(base_url="http://executor.test")
        with respx.mock(assert_all_called=True) as mock:
            mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(200, json=["not", "an", "object"])
            )
            try:
                await client.run_experiment("h", CONTEXT, False)
                raise AssertionError("expected ExperimentApiError for malformed body")
            except ExperimentApiError as exc:
                assert "malformed" in str(exc).lower()

    asyncio.run(verify())


def test_missing_hypothesis_or_required_context_field_rejected_before_http_call():
    async def verify():
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post("http://executor.test/api/v1/experiment")
            try:
                await run_experiment.ainvoke({"hypothesis": "", "context": CONTEXT})
            except Exception:
                pass
            try:
                await run_experiment.ainvoke(
                    {"hypothesis": "h", "context": {"service": "edi"}}
                )
            except Exception:
                pass
            assert not route.called, "no HTTP call should be made when validation fails"

    asyncio.run(verify())


def test_extra_context_keys_are_stripped_before_request_is_sent():
    async def verify():
        with respx.mock(assert_all_called=True) as mock:
            route = mock.post("http://executor.test/api/v1/experiment").mock(
                return_value=httpx.Response(200, json=FULL_RESPONSE)
            )
            from praxis_agent.clients.experiment_client import experiment_client as singleton

            original_base = singleton.base_url
            singleton.base_url = "http://executor.test"
            try:
                await run_experiment.ainvoke(
                    {
                        "hypothesis": "h",
                        "context": {**CONTEXT, "scenarioName": "should be dropped", "extra": 1},
                    }
                )
            finally:
                singleton.base_url = original_base

        sent_context = json.loads(route.calls[0].request.content)["context"]
        assert "scenarioName" not in sent_context
        assert "extra" not in sent_context
        assert sent_context == CONTEXT

    asyncio.run(verify())


def test_sensitive_fields_are_redacted_before_logging():
    body = {
        "context": {
            "service": "auth",
            "requestExample": {"password": "hunter2", "nested": {"apiKey": "abc", "ok": "keep"}},
        }
    }
    redacted = _redact(body)
    assert redacted["context"]["requestExample"]["password"] == "***REDACTED***"
    assert redacted["context"]["requestExample"]["nested"]["apiKey"] == "***REDACTED***"
    assert redacted["context"]["requestExample"]["nested"]["ok"] == "keep"


if __name__ == "__main__":
    import inspect

    fns = [obj for name, obj in list(globals().items()) if name.startswith("test_") and inspect.isfunction(obj)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
