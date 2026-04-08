from google.adk.agents import Agent
import requests
import json

PLANNER_URL = "https://planner-388581456192.asia-south1.run.app/plan"
EXECUTOR_URL = "https://executor-388581456192.asia-south1.run.app/execute"

def handle_goal(input_text: str):
    return f"DEBUG: Received input → {input_text}"
    try:
        if len(input_text.strip()) < 10:
            return "Please provide a clear goal like: 'Prepare for robotics presentation'"

        # Step 1: Planner
        plan_res = requests.post(PLANNER_URL, json={"goal": input_text}).json()
        raw_output = plan_res.get("raw_output", "")

        try:
            parsed = json.loads(raw_output)
            tasks = parsed.get("tasks", [])
        except:
            tasks = []

        if not tasks:
            return "Could not generate tasks."

        # Step 2: Executor
        exec_res = requests.post(EXECUTOR_URL, json={"tasks": tasks}).json()


        return f"""
Goal: {input_text}

Tasks:
{tasks}

Execution:
{exec_res}
"""

    except Exception as e:
        return f"Error: {str(e)}"

root_agent = Agent(
    name="productivity-agent",
    model="gemini-1.5-flash",
    instruction="""
You are a productivity execution agent.

When the user provides a goal, you MUST call the internal system
to break it into tasks and execute them.

Always respond with structured output.
""",
    # 👇 THIS is the key change
    callable=handle_goal
)
