from fastapi import FastAPI
import requests

app = FastAPI()

MCP_URL = "https://mcp-388581456192.asia-south1.run.app"

@app.get("/")
def home():
    return {"status": "executor running"}

@app.post("/execute")
def execute(data: dict):
    tasks = data.get("tasks", [])

    results = []

    for task in tasks:
        # 1. Create task in MCP
        task_res = requests.post(
            f"{MCP_URL}/task/create",
            json={"title": task.get("title")}
        ).json()

        # 2. Create calendar event
        cal_res = requests.post(
            f"{MCP_URL}/calendar/create",
            json={"title": task.get("title")}
        ).json()

        results.append({
            "task": task_res,
            "calendar": cal_res
        })

    return {
        "message": "execution complete",
        "results": results
    }
