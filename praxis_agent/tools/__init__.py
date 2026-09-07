"""Aggregates all agent tools into a few convenient collections."""
from __future__ import annotations

from praxis_agent.tools.code_tools import code_ask, code_edit
from praxis_agent.tools.config_tools import get_service_env, set_env_var, update_service_env
from praxis_agent.tools.environment_tools import (
    create_environment,
    delete_environment,
    get_environment,
    get_service_endpoints,
    restart_service,
    start_service,
    stop_service,
)
from praxis_agent.tools.inspection_tools import (
    execute_command,
    get_environment_metrics,
    get_logs,
    get_service_metrics,
    query_database,
)
from praxis_agent.tools.mock_tools import (
    call_mock_endpoint,
    create_mock_api,
    create_mock_response,
    deploy_mock_server,
    get_ekyc_detailed_enquiry,
    get_mock_api,
    get_mock_response,
    list_mock_apis,
    list_mock_responses,
    promote_mock_branch,
    update_mock_api,
    update_mock_branch_info,
    update_mock_response,
    upsert_ekyc_stage,
    wait_for_mock_server_restart,
)
from praxis_agent.tools.orchestrator_tools import (
    bulk_set_orchestrator_routes,
    get_orchestrator_route,
    get_orchestrator_status,
    list_orchestrator_routes,
    set_orchestrator_route,
)
from praxis_agent.tools.skill_tools import list_skills, load_skill

ENVIRONMENT_TOOLS = [
    create_environment,
    get_environment,
    delete_environment,
    start_service,
    stop_service,
    restart_service,
    get_service_endpoints,
]

PROVISION_TOOLS = [create_environment, start_service]

DISCOVERY_TOOLS = [
    get_environment,
    get_service_endpoints,
    get_service_env,
    get_orchestrator_status,
    list_orchestrator_routes,
]

INSPECTION_TOOLS = [
    get_logs,
    query_database,
    execute_command,
    get_service_metrics,
    get_environment_metrics,
]

CODE_TOOLS = [code_ask, code_edit]

CONFIG_TOOLS = [get_service_env, update_service_env, set_env_var]

MOCK_TOOLS = [
    create_mock_response,
    list_mock_responses,
    get_mock_response,
    update_mock_response,
    create_mock_api,
    list_mock_apis,
    get_mock_api,
    update_mock_api,
    wait_for_mock_server_restart,
    call_mock_endpoint,
    upsert_ekyc_stage,
    get_ekyc_detailed_enquiry,
    update_mock_branch_info,
    promote_mock_branch,
    deploy_mock_server,
]

SKILL_TOOLS = [list_skills, load_skill]

ORCHESTRATOR_TOOLS = [
    get_orchestrator_status,
    list_orchestrator_routes,
    get_orchestrator_route,
    set_orchestrator_route,
    bulk_set_orchestrator_routes,
]

ALL_TOOLS = ENVIRONMENT_TOOLS + INSPECTION_TOOLS + CODE_TOOLS + CONFIG_TOOLS + MOCK_TOOLS + SKILL_TOOLS + ORCHESTRATOR_TOOLS

# Nodes use these focused collections rather than granting every capability in every phase.
EVIDENCE_TOOLS = [get_logs, query_database, get_service_metrics, get_environment_metrics, get_environment]
EXPERIMENT_TOOLS = (
    [start_service, stop_service, restart_service]
    + INSPECTION_TOOLS
    + [code_ask]
    + CONFIG_TOOLS
    + ORCHESTRATOR_TOOLS
    + SKILL_TOOLS
)
MOCK_CONTRACT_TOOLS = EXPERIMENT_TOOLS + MOCK_TOOLS
PERFORMANCE_TOOLS = EXPERIMENT_TOOLS
DIAGNOSIS_TOOLS = [code_ask]
EDIT_TOOLS = [code_edit]
DEPLOY_TOOLS = [start_service, restart_service]
