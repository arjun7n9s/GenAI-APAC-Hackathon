from fastapi import FastAPI
import requests
import json

app = FastAPI()

PLANNER_URL = "http://127.0.0.1:8000/plan"
EXECUTOR_URL = "http://127.0.0.1:8002/execute"

@app.get("/")
def home():
    return {"status": "orchestrator running"}

@app.post("/execute")
def execute(goal: dict):
    # Step 1: Call Planner
    plan_res = requests.post(PLANNER_URL, json=goal).json()

    # If using AI planner → parse JSON string
    raw_output = plan_res.get("raw_output", "")

    try:
        parsed = json.loads(raw_output)
        tasks = parsed.get("tasks", [])
    except:
        tasks = []

    # Step 2: Call Executor
    exec_res = requests.post(EXECUTOR_URL, json={"tasks": tasks}).json()

    return {
        "goal": goal,
        "tasks": tasks,
        "execution": exec_res
    }
