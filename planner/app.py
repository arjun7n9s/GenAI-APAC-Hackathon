from fastapi import FastAPI
import json

app = FastAPI()

@app.get("/")
def home():
    return {"status": "planner running"}

@app.post("/plan")
def plan(goal: dict):
    user_goal = goal.get("goal", "")

    tasks = [
        {"title": f"Understand: {user_goal}"},
        {"title": f"Break into steps"},
        {"title": f"Execute and review"}
    ]

    return {
        "raw_output": json.dumps({"tasks": tasks})
    }
