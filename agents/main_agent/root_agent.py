from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import requests
from google.adk.agents.llm_agent import Agent
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

DEFAULT_PLANNER_URL = "http://127.0.0.1:8000/plan"
DEFAULT_EXECUTOR_URL = "http://127.0.0.1:8002/execute"
DEFAULT_MCP_URL = "http://127.0.0.1:8001"
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
ENABLE_SERVICE_AUTH = os.getenv("ENABLE_SERVICE_AUTH", "true").lower() == "true"


def _service_url(env_var_name: str, default: str) -> str:
    return os.getenv(env_var_name, default).rstrip("/")


def _audience_from_url(target_url: str) -> str:
    parsed = urlsplit(target_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_headers(target_url: str) -> dict[str, str]:
    if not ENABLE_SERVICE_AUTH:
        return {}

    auth_request = GoogleAuthRequest()
    token = id_token.fetch_id_token(auth_request, _audience_from_url(target_url))
    return {"Authorization": f"Bearer {token}"}


PLANNER_URL = _service_url("PLANNER_URL", DEFAULT_PLANNER_URL)
EXECUTOR_URL = _service_url("EXECUTOR_URL", DEFAULT_EXECUTOR_URL)
MCP_URL = _service_url("MCP_URL", DEFAULT_MCP_URL)


def _extract_plan(plan_response: dict) -> dict:
    if plan_response.get("plan"):
        return plan_response["plan"]

    raw_output = plan_response.get("raw_output", "")
    try:
        return json.loads(raw_output)
    except json.JSONDecodeError:
        return {}


def handle_goal(input_text: str) -> dict:
    """Plan and execute a user goal across the planner, executor, and MCP tool services."""
    try:
        if len(input_text.strip()) < 10:
            return {
                "status": "error",
                "message": "Please provide a clearer goal with enough detail to plan and execute.",
            }

        planner_response = requests.post(
            PLANNER_URL,
            json={"goal": input_text, "workspace_id": "default"},
            headers=_request_headers(PLANNER_URL),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        planner_response.raise_for_status()
        planner_data = planner_response.json()
        plan = _extract_plan(planner_data)

        if not plan.get("tasks"):
            return {
                "status": "error",
                "message": "Planner returned no executable tasks.",
                "planner_response": planner_data,
            }

        executor_response = requests.post(
            EXECUTOR_URL,
            json={
                "goal": input_text,
                "workspace_id": plan.get("workspace_id", "default"),
                "plan": plan,
                "dry_run": False,
            },
            headers=_request_headers(EXECUTOR_URL),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        executor_response.raise_for_status()
        execution = executor_response.json()

        return {
            "status": "success",
            "goal": input_text,
            "plan": plan,
            "execution": execution,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def get_workspace_snapshot(workspace_id: str = "default") -> dict:
    """Inspect the current task, calendar, and email state stored in MCP for a workspace."""
    try:
        response = requests.get(
            f"{MCP_URL}/snapshot",
            params={"workspace_id": workspace_id},
            headers=_request_headers(MCP_URL),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


root_agent = Agent(
    name="aegis_agent",
    model="gemini-2.5-flash",
    description="Plans a productivity goal, executes it through specialized services, and can inspect workspace state.",
    instruction="""
You are the master productivity agent for a multi-agent operations system.

Use `handle_goal` when a user gives you a goal that needs planning and execution.
Use `get_workspace_snapshot` when the user asks about current tasks, calendar events, drafts, or system state.

Always respond with concise structured summaries grounded in tool outputs.
""",
    tools=[handle_goal, get_workspace_snapshot],
)
