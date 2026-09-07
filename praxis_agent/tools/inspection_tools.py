"""Tools for observing a running environment: logs, database queries, arbitrary command
execution, and CPU/memory metrics."""
from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from praxis_agent.clients.execution_client import execution_client
from praxis_agent.tools._tool_utils import instrumented


@tool
@instrumented("get_logs")
async def get_logs(environment_id: str, service: str, tail: Optional[int] = 200, since: Optional[str] = None) -> dict:
    """Fetch recent logs for a service container. Use `tail` to limit line count and
    `since` (ISO timestamp) to fetch only logs after a point in time — e.g. right before you
    triggered a reproduction step, so you only look at the relevant window."""
    return await execution_client.get_logs(environment_id, service, tail=tail, since=since)


@tool
@instrumented("query_database")
async def query_database(environment_id: str, service: str, query: str) -> dict:
    """Run a database query for any service. For mysql services,
    `query` is raw SQL. For mongodb services, `query` is a JS expression evaluated against
    `db`, e.g. "db.users.find({}).toArray()"."""
    return await execution_client.query_database(environment_id, service, query)


@tool
@instrumented("execute_command")
async def execute_command(environment_id: str, service: str, command: list[str], timeout: Optional[int] = 60) -> dict:
    """Execute an arbitrary command inside a service's container. `command` MUST be a list of
    argv tokens (e.g. ["python3", "-c", "print(1)"]), never a single shell string. Use this to
    reproduce a bug, run a generated load/concurrency test script, curl an internal endpoint,
    inspect the filesystem, etc."""
    return await execution_client.execute_command(environment_id, service, command, timeout=timeout)


@tool
@instrumented("get_service_metrics")
async def get_service_metrics(
    environment_id: str, service: str, duration: Optional[int] = None, interval: Optional[int] = None
) -> dict:
    """Sample CPU/memory usage for one service. Omit `duration` for an instant single-sample
    read, or set duration (max 60s) + interval (min 1s) to get a time series — useful for
    performance/soak testing to see whether CPU/memory trends up under load.
    don't set duration > 60 or the request will timeout
    """
    return await execution_client.get_service_metrics(environment_id, service, duration=duration, interval=interval)


@tool
@instrumented("get_environment_metrics")
async def get_environment_metrics(
    environment_id: str,
    services: Optional[list[str]] = None,
    duration: Optional[int] = None,
    interval: Optional[int] = None,
) -> dict:
    """Sample CPU/memory for multiple services in one call so they can be compared directly
    (e.g. "did the app service's CPU spike while the database stayed flat?"). Omit `services`
    to default to every currently-running service in the environment."""
    return await execution_client.get_environment_metrics(environment_id, services=services, duration=duration, interval=interval)


@tool
@instrumented("run_load_test")
async def run_load_test(
    environment_id: str,
    service: str,
    endpoint: str,
    method: str,
    headers: dict[str, str],
    body: dict,
    hit_count: int,
    timeout: int,
    on_progress=None,
) -> dict:
    """Send `hit_count` concurrent requests to a service endpoint and return the completed
    aggregate result. `endpoint` is a service-relative path such as "/health"; `timeout` is the
    per-request timeout in seconds and must not exceed 60. Returns completion counts, status-code
    distribution, and min/max/average latency in milliseconds. Use this for bounded concurrency
    or load scenarios, then collect logs and metrics as needed."""
    return await execution_client.run_load_test(
        environment_id=environment_id,
        service=service,
        endpoint=endpoint,
        method=method,
        headers=headers,
        body=body,
        hit_count=hit_count,
        timeout=timeout,
        on_progress=on_progress,
    )
