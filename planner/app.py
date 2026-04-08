from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

app = FastAPI()

PLANNER_MODEL = os.getenv("PLANNER_MODEL", "gemini-2.5-flash")
ENABLE_VERTEX_PLANNER = os.getenv("ENABLE_VERTEX_PLANNER", "false").lower() == "true"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class GoalRequest(BaseModel):
    goal: str = Field(..., min_length=3)
    workspace_id: str = "default"
    due_date: str | None = None
    audience: str | None = None
    constraints: list[str] = Field(default_factory=list)
    preferences: list[str] = Field(default_factory=list)


def _parse_due_date(raw_due_date: str | None) -> date | None:
    if not raw_due_date:
        return None

    try:
        return datetime.strptime(raw_due_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def _detect_goal_type(goal: str) -> str:
    normalized = goal.lower()
    if any(keyword in normalized for keyword in ["presentation", "pitch", "demo", "talk"]):
        return "presentation"
    if any(keyword in normalized for keyword in ["trip", "travel", "flight", "hotel"]):
        return "travel"
    if any(keyword in normalized for keyword in ["launch", "ship", "release", "deploy"]):
        return "launch"
    if any(keyword in normalized for keyword in ["study", "exam", "interview", "learn"]):
        return "learning"
    return "general"


def _default_schedule_hint(task_index: int, due_date: date | None, duration_minutes: int) -> dict[str, Any]:
    if not due_date:
        return {
            "date": None,
            "start_time": None,
            "duration_minutes": duration_minutes,
            "rationale": "No due date was provided, so this task is unscheduled.",
        }

    days_before_due = max(0, 4 - task_index)
    scheduled_date = due_date - timedelta(days=days_before_due)
    start_hour = 10 + min(task_index, 5)
    return {
        "date": scheduled_date.isoformat(),
        "start_time": f"{start_hour:02d}:00",
        "duration_minutes": duration_minutes,
        "rationale": "Front-loaded before the deadline to protect time for review and iteration.",
    }


def _build_task(
    plan_id: str,
    task_index: int,
    title: str,
    summary: str,
    category: str,
    priority: str,
    estimated_minutes: int,
    success_criteria: list[str],
    due_date: date | None,
    depends_on: list[str] | None = None,
    communication: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = f"{plan_id}-task-{task_index + 1}"
    tool_actions = ["create_task"]
    if due_date:
        tool_actions.append("create_calendar_event")
    if communication:
        tool_actions.append("draft_email")

    return {
        "id": task_id,
        "title": title,
        "summary": summary,
        "category": category,
        "priority": priority,
        "estimated_minutes": estimated_minutes,
        "depends_on": depends_on or [],
        "success_criteria": success_criteria,
        "tool_actions": tool_actions,
        "schedule_hint": _default_schedule_hint(task_index, due_date, estimated_minutes),
        "communication": communication,
    }


def _presentation_tasks(plan_id: str, request: GoalRequest, due_date: date | None) -> list[dict[str, Any]]:
    goal = request.goal
    audience = request.audience or "stakeholders"

    tasks = [
        _build_task(
            plan_id=plan_id,
            task_index=0,
            title="Clarify the presentation outcome",
            summary=f"Define the single most important outcome for '{goal}' and align it to the audience.",
            category="planning",
            priority="high",
            estimated_minutes=45,
            success_criteria=[
                "Success metric is explicit",
                f"Audience needs for {audience} are captured",
                "Key message is written in one sentence",
            ],
            due_date=due_date,
        ),
        _build_task(
            plan_id=plan_id,
            task_index=1,
            title="Gather supporting material and evidence",
            summary="Collect facts, examples, metrics, screenshots, and reference material needed for credibility.",
            category="research",
            priority="high",
            estimated_minutes=60,
            success_criteria=[
                "Core evidence is collected",
                "Sources are easy to cite during Q&A",
                "Open questions are listed",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-1"],
        ),
        _build_task(
            plan_id=plan_id,
            task_index=2,
            title="Draft the slide or narrative structure",
            summary="Turn the goal into a clear opening, supporting sections, and strong close.",
            category="creation",
            priority="high",
            estimated_minutes=90,
            success_criteria=[
                "Opening and closing are compelling",
                "Each section supports the central message",
                "The narrative fits within the target time",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-1", f"{plan_id}-task-2"],
        ),
        _build_task(
            plan_id=plan_id,
            task_index=3,
            title="Rehearse and tighten the delivery",
            summary="Practice the delivery, reduce weak transitions, and prepare likely Q&A.",
            category="review",
            priority="medium",
            estimated_minutes=45,
            success_criteria=[
                "Run-through finishes on time",
                "Transitions feel natural",
                "Top questions have crisp answers",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-3"],
            communication={
                "channel": "email",
                "recipient": "team@example.com",
                "subject": "Request for presentation feedback",
                "purpose": "Ask for a quick review slot after rehearsal.",
            },
        ),
    ]
    return tasks


def _general_tasks(plan_id: str, request: GoalRequest, due_date: date | None) -> list[dict[str, Any]]:
    goal = request.goal
    return [
        _build_task(
            plan_id=plan_id,
            task_index=0,
            title="Clarify the desired outcome",
            summary=f"Define what success looks like for '{goal}' and the boundary of work.",
            category="planning",
            priority="high",
            estimated_minutes=30,
            success_criteria=[
                "Outcome is measurable",
                "Scope is explicit",
                "Known constraints are recorded",
            ],
            due_date=due_date,
        ),
        _build_task(
            plan_id=plan_id,
            task_index=1,
            title="Break the goal into execution blocks",
            summary="Split the work into concrete chunks that can be executed and tracked independently.",
            category="planning",
            priority="high",
            estimated_minutes=45,
            success_criteria=[
                "Each block has a clear owner or next step",
                "Dependencies are mapped",
                "The riskiest block is visible early",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-1"],
        ),
        _build_task(
            plan_id=plan_id,
            task_index=2,
            title="Execute the highest-value block first",
            summary="Start with the piece that removes the most uncertainty or unlocks later work.",
            category="creation",
            priority="high",
            estimated_minutes=60,
            success_criteria=[
                "A concrete artifact or result exists",
                "New blockers are identified",
                "The next action is obvious",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-2"],
        ),
        _build_task(
            plan_id=plan_id,
            task_index=3,
            title="Review, communicate, and close the loop",
            summary="Check quality, communicate progress, and prepare the next follow-up decision.",
            category="communication",
            priority="medium",
            estimated_minutes=30,
            success_criteria=[
                "Outcome is reviewed",
                "Stakeholders are updated",
                "A next checkpoint exists",
            ],
            due_date=due_date,
            depends_on=[f"{plan_id}-task-3"],
            communication={
                "channel": "email",
                "recipient": "stakeholder@example.com",
                "subject": "Progress update",
                "purpose": "Share status and request confirmation on the next milestone.",
            },
        ),
    ]


def _build_fallback_plan(request: GoalRequest) -> dict[str, Any]:
    plan_id = uuid.uuid4().hex[:8]
    due_date = _parse_due_date(request.due_date)
    goal_type = _detect_goal_type(request.goal)

    if goal_type == "presentation":
        tasks = _presentation_tasks(plan_id, request, due_date)
        execution_strategy = (
            "Front-load thinking and evidence collection, then build the story, then rehearse with review time protected."
        )
        risks = [
            "The message may be too broad for the audience.",
            "Evidence may be weak or scattered across sources.",
            "Rehearsal can get squeezed without a scheduled review slot.",
        ]
    else:
        tasks = _general_tasks(plan_id, request, due_date)
        execution_strategy = (
            "Reduce ambiguity first, sequence the work into dependencies, and communicate progress at the end of the loop."
        )
        risks = [
            "The goal may still be too broad.",
            "Critical dependencies may surface late.",
            "Progress may remain invisible without a checkpoint message.",
        ]

    return {
        "plan_id": plan_id,
        "workspace_id": request.workspace_id,
        "goal": request.goal,
        "goal_type": goal_type,
        "goal_summary": f"Plan for: {request.goal}",
        "audience": request.audience,
        "constraints": request.constraints,
        "preferences": request.preferences,
        "execution_strategy": execution_strategy,
        "risks": risks,
        "tasks": tasks,
        "planner_source": "heuristic",
        "created_at": _utc_now_iso(),
    }


def _clean_json_payload(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return json.loads(cleaned)


def _vertex_plan(request: GoalRequest) -> dict[str, Any]:
    from google import genai

    prompt = f"""
You are a senior operations planning agent.
Return JSON only. No markdown.

Create a production-quality execution plan for this user goal:
{json.dumps(request.dict(), indent=2)}

Return an object with:
- plan_id
- workspace_id
- goal
- goal_type
- goal_summary
- audience
- constraints
- preferences
- execution_strategy
- risks: string[]
- tasks: object[] where each task includes
  - id
  - title
  - summary
  - category
  - priority
  - estimated_minutes
  - depends_on: string[]
  - success_criteria: string[]
  - tool_actions: string[]
  - schedule_hint: {{date,start_time,duration_minutes,rationale}}
  - communication: null or {{channel,recipient,subject,purpose}}
"""

    client = genai.Client(
        vertexai=True,
        project=os.getenv("GOOGLE_CLOUD_PROJECT"),
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1"),
    )

    try:
        response = client.models.generate_content(
            model=PLANNER_MODEL,
            contents=prompt,
        )
        payload = _clean_json_payload(response.text)
        payload["planner_source"] = "vertex"
        payload.setdefault("workspace_id", request.workspace_id)
        payload.setdefault("goal", request.goal)
        payload.setdefault("created_at", _utc_now_iso())
        return payload
    finally:
        client.close()


@app.get("/")
def home():
    return {
        "status": "planner running",
        "model": PLANNER_MODEL,
        "vertex_enabled": ENABLE_VERTEX_PLANNER,
    }


@app.post("/plan")
def plan(goal: GoalRequest):
    if not goal.goal.strip():
        raise HTTPException(status_code=400, detail="goal is required")

    try:
        plan_payload = _vertex_plan(goal) if ENABLE_VERTEX_PLANNER else _build_fallback_plan(goal)
    except Exception:
        plan_payload = _build_fallback_plan(goal)
        plan_payload["planner_source"] = "heuristic_fallback"

    return {
        "plan": plan_payload,
        "raw_output": json.dumps(plan_payload),
    }
