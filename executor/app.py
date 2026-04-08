from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi import HTTPException
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from pydantic import BaseModel
from pydantic import Field
import requests

app = FastAPI()

MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8001").rstrip("/")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
ENABLE_SERVICE_AUTH = os.getenv("ENABLE_SERVICE_AUTH", "true").lower() == "true"


class ExecuteRequest(BaseModel):
    goal: str | None = None
    workspace_id: str = "default"
    dry_run: bool = False
    plan: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] = Field(default_factory=list)


def _audience_from_url(target_url: str) -> str:
    parsed = urlsplit(target_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_headers(target_url: str) -> dict[str, str]:
    if not ENABLE_SERVICE_AUTH:
        return {}

    auth_request = GoogleAuthRequest()
    token = id_token.fetch_id_token(auth_request, _audience_from_url(target_url))
    return {"Authorization": f"Bearer {token}"}


def _post_to_mcp(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"{MCP_URL}{path}",
        json=payload,
        headers=_request_headers(MCP_URL),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response.json()


def _normalize_tasks(request: ExecuteRequest) -> list[dict[str, Any]]:
    if request.plan and request.plan.get("tasks"):
        return request.plan["tasks"]
    return request.tasks


@app.get("/")
def home():
    return {
        "status": "executor running",
        "mcp_url": MCP_URL,
    }


@app.post("/execute")
def execute(data: ExecuteRequest):
    tasks = _normalize_tasks(data)
    if not tasks:
        raise HTTPException(status_code=400, detail="tasks are required")

    results = []
    summary = {
        "task_records": 0,
        "calendar_events": 0,
        "email_drafts": 0,
        "failures": 0,
    }

    for task in tasks:
        task_result = {
            "task_id": task.get("id"),
            "title": task.get("title"),
            "actions": [],
            "errors": [],
        }

        base_task_payload = {
            "workspace_id": data.workspace_id,
            "source_task_id": task.get("id"),
            "title": task.get("title"),
            "summary": task.get("summary"),
            "priority": task.get("priority"),
            "category": task.get("category"),
            "estimated_minutes": task.get("estimated_minutes"),
            "depends_on": task.get("depends_on", []),
            "success_criteria": task.get("success_criteria", []),
            "status": "planned" if data.dry_run else "pending",
        }

        if data.dry_run:
            task_result["actions"].append({"type": "create_task", "payload": base_task_payload})
            if task.get("schedule_hint", {}).get("date"):
                task_result["actions"].append(
                    {"type": "create_calendar_event", "payload": task.get("schedule_hint")}
                )
            if task.get("communication"):
                task_result["actions"].append({"type": "draft_email", "payload": task["communication"]})
            results.append(task_result)
            continue

        try:
            created_task = _post_to_mcp("/task/create", base_task_payload)
            summary["task_records"] += 1
            task_result["actions"].append({"type": "create_task", "result": created_task})
        except Exception as exc:
            summary["failures"] += 1
            task_result["errors"].append(f"task creation failed: {exc}")

        schedule_hint = task.get("schedule_hint") or {}
        if schedule_hint.get("date"):
            try:
                calendar_payload = {
                    "workspace_id": data.workspace_id,
                    "title": task.get("title"),
                    "date": schedule_hint.get("date"),
                    "start_time": schedule_hint.get("start_time"),
                    "duration_minutes": schedule_hint.get("duration_minutes"),
                    "description": task.get("summary"),
                }
                calendar_event = _post_to_mcp("/calendar/create", calendar_payload)
                summary["calendar_events"] += 1
                task_result["actions"].append({"type": "create_calendar_event", "result": calendar_event})
            except Exception as exc:
                summary["failures"] += 1
                task_result["errors"].append(f"calendar creation failed: {exc}")

        communication = task.get("communication")
        if communication and communication.get("channel") == "email":
            try:
                email_payload = {
                    "workspace_id": data.workspace_id,
                    "to": communication.get("recipient"),
                    "subject": communication.get("subject"),
                    "purpose": communication.get("purpose"),
                    "body": f"Draft generated for task: {task.get('title')}",
                }
                email_draft = _post_to_mcp("/email/draft", email_payload)
                summary["email_drafts"] += 1
                task_result["actions"].append({"type": "draft_email", "result": email_draft})
            except Exception as exc:
                summary["failures"] += 1
                task_result["errors"].append(f"email draft failed: {exc}")

        results.append(task_result)

    return {
        "message": "execution complete",
        "workspace_id": data.workspace_id,
        "goal": data.goal,
        "dry_run": data.dry_run,
        "summary": summary,
        "results": results,
    }
