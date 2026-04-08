from fastapi import FastAPI
from datetime import datetime

app = FastAPI()

@app.get("/")
def home():
    return {"status": "MCP running"}

# ------------------------
# TASK TOOL
# ------------------------
tasks = []

@app.post("/task/create")
def create_task(data: dict):
    task = {
        "id": len(tasks) + 1,
        "title": data.get("title"),
        "status": "pending",
        "created_at": str(datetime.now())
    }
    tasks.append(task)
    return {"message": "task created", "task": task}

# ------------------------
# CALENDAR TOOL (mock)
# ------------------------
@app.post("/calendar/create")
def create_event(data: dict):
    return {
        "message": "calendar event created",
        "event": data
    }

# ------------------------
# EMAIL TOOL (mock)
# ------------------------
@app.post("/email/send")
def send_email(data: dict):
    return {
        "message": "email sent",
        "details": data
    }
