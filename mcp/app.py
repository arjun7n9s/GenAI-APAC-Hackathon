from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from pydantic import Field

app = FastAPI()

STORAGE_BACKEND = os.getenv("MCP_STORAGE_BACKEND", "memory").lower()
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID")
FIRESTORE_COLLECTION_PREFIX = os.getenv("FIRESTORE_COLLECTION_PREFIX", "productivity")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _model_payload(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class TaskCreateRequest(BaseModel):
    workspace_id: str = "default"
    source_task_id: str | None = None
    title: str
    summary: str | None = None
    category: str | None = None
    priority: str | None = None
    estimated_minutes: int | None = None
    depends_on: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    status: str = "pending"


class TaskStatusUpdateRequest(BaseModel):
    status: str


class CalendarCreateRequest(BaseModel):
    workspace_id: str = "default"
    title: str
    date: str
    start_time: str | None = None
    duration_minutes: int | None = None
    description: str | None = None


class EmailRequest(BaseModel):
    workspace_id: str = "default"
    to: str
    subject: str | None = None
    purpose: str | None = None
    body: str | None = None


class MemoryStore:
    def __init__(self):
        self.records = {
            "tasks": {},
            "calendar_events": {},
            "emails": {},
        }

    def create(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        record_id = uuid.uuid4().hex[:10]
        record = {
            "id": record_id,
            "created_at": _utc_now_iso(),
            **payload,
        }
        self.records[kind][record_id] = record
        return record

    def list(self, kind: str, workspace_id: str) -> list[dict[str, Any]]:
        return [
            record
            for record in self.records[kind].values()
            if record.get("workspace_id", "default") == workspace_id
        ]

    def update(self, kind: str, record_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        record = self.records[kind].get(record_id)
        if not record:
            return None
        record.update(updates)
        record["updated_at"] = _utc_now_iso()
        return record

    def snapshot(self, workspace_id: str) -> dict[str, Any]:
        return {
            "tasks": self.list("tasks", workspace_id),
            "calendar_events": self.list("calendar_events", workspace_id),
            "emails": self.list("emails", workspace_id),
        }


class FirestoreStore:
    def __init__(self, project_id: str | None, prefix: str):
        from google.cloud import firestore

        self.client = firestore.Client(project=project_id)
        self.prefix = prefix

    def _collection(self, kind: str):
        return self.client.collection(f"{self.prefix}_{kind}")

    def create(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        record_id = uuid.uuid4().hex[:10]
        record = {
            "id": record_id,
            "created_at": _utc_now_iso(),
            **payload,
        }
        self._collection(kind).document(record_id).set(record)
        return record

    def list(self, kind: str, workspace_id: str) -> list[dict[str, Any]]:
        documents = self._collection(kind).where("workspace_id", "==", workspace_id).stream()
        return [document.to_dict() for document in documents]

    def update(self, kind: str, record_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        doc_ref = self._collection(kind).document(record_id)
        snapshot = doc_ref.get()
        if not snapshot.exists:
            return None

        payload = {
            **updates,
            "updated_at": _utc_now_iso(),
        }
        doc_ref.update(payload)
        updated = snapshot.to_dict()
        updated.update(payload)
        return updated

    def snapshot(self, workspace_id: str) -> dict[str, Any]:
        return {
            "tasks": self.list("tasks", workspace_id),
            "calendar_events": self.list("calendar_events", workspace_id),
            "emails": self.list("emails", workspace_id),
        }


def _build_store():
    if STORAGE_BACKEND == "firestore":
        try:
            return FirestoreStore(FIRESTORE_PROJECT_ID, FIRESTORE_COLLECTION_PREFIX), "firestore"
        except Exception:
            return MemoryStore(), "memory_fallback"
    return MemoryStore(), "memory"


store, resolved_backend = _build_store()


@app.get("/")
def home():
    return {
        "status": "MCP running",
        "storage_backend": resolved_backend,
    }


@app.post("/task/create")
def create_task(data: TaskCreateRequest):
    task = store.create(
        "tasks",
        {
            **_model_payload(data),
        },
    )
    return {"message": "task created", "task": task}


@app.get("/task/list")
def list_tasks(workspace_id: str = "default"):
    return {
        "workspace_id": workspace_id,
        "tasks": store.list("tasks", workspace_id),
    }


@app.post("/task/{task_id}/status")
def update_task_status(task_id: str, data: TaskStatusUpdateRequest):
    task = store.update("tasks", task_id, _model_payload(data))
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return {"message": "task updated", "task": task}


@app.post("/calendar/create")
def create_event(data: CalendarCreateRequest):
    event = store.create("calendar_events", _model_payload(data))
    return {
        "message": "calendar event created",
        "event": event,
    }


@app.get("/calendar/list")
def list_events(workspace_id: str = "default"):
    return {
        "workspace_id": workspace_id,
        "events": store.list("calendar_events", workspace_id),
    }


@app.post("/email/draft")
def draft_email(data: EmailRequest):
    draft = store.create("emails", {**_model_payload(data), "status": "draft"})
    return {
        "message": "email draft created",
        "email": draft,
    }


@app.post("/email/send")
def send_email(data: EmailRequest):
    email = store.create("emails", {**_model_payload(data), "status": "sent"})
    return {
        "message": "email sent",
        "details": email,
    }


@app.get("/snapshot")
def snapshot(workspace_id: str = "default"):
    data = store.snapshot(workspace_id)
    return {
        "workspace_id": workspace_id,
        "storage_backend": resolved_backend,
        "counts": {
            "tasks": len(data["tasks"]),
            "calendar_events": len(data["calendar_events"]),
            "emails": len(data["emails"]),
        },
        **data,
    }
