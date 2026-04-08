import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from executor.app import app as executor_app
from mcp import app as mcp_module
from planner.app import app as planner_app


ROOT = Path(__file__).resolve().parents[1]


def load_root_agent_module():
    google_module = types.ModuleType("google")
    adk_module = types.ModuleType("google.adk")
    agents_module = types.ModuleType("google.adk.agents")
    llm_agent_module = types.ModuleType("google.adk.agents.llm_agent")

    class DummyAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    llm_agent_module.Agent = DummyAgent

    sys.modules["google"] = google_module
    sys.modules["google.adk"] = adk_module
    sys.modules["google.adk.agents"] = agents_module
    sys.modules["google.adk.agents.llm_agent"] = llm_agent_module

    spec = importlib.util.spec_from_file_location(
        "root_agent_module",
        ROOT / "agents" / "main_agent" / "root_agent.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PlannerTests(unittest.TestCase):
    def test_plan_returns_structured_plan(self):
        client = TestClient(planner_app)
        response = client.post("/plan", json={"goal": "Prepare for robotics presentation"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("plan", payload)
        self.assertGreaterEqual(len(payload["plan"]["tasks"]), 4)
        self.assertIn("planner_source", payload["plan"])

    def test_plan_requires_goal(self):
        client = TestClient(planner_app)
        response = client.post("/plan", json={"goal": ""})

        self.assertEqual(response.status_code, 422)


class MCPTests(unittest.TestCase):
    def setUp(self):
        mcp_module.store = mcp_module.MemoryStore()
        mcp_module.resolved_backend = "memory"
        self.client = TestClient(mcp_module.app)

    def test_create_task_and_snapshot(self):
        task_response = self.client.post(
            "/task/create",
            json={"workspace_id": "demo", "title": "Draft slides"},
        )
        event_response = self.client.post(
            "/calendar/create",
            json={"workspace_id": "demo", "title": "Practice", "date": "2026-04-09"},
        )
        email_response = self.client.post(
            "/email/draft",
            json={"workspace_id": "demo", "to": "team@example.com"},
        )
        snapshot_response = self.client.get("/snapshot", params={"workspace_id": "demo"})

        self.assertEqual(task_response.status_code, 200)
        self.assertEqual(event_response.status_code, 200)
        self.assertEqual(email_response.status_code, 200)
        self.assertEqual(snapshot_response.status_code, 200)
        snapshot = snapshot_response.json()
        self.assertEqual(snapshot["counts"]["tasks"], 1)
        self.assertEqual(snapshot["counts"]["calendar_events"], 1)
        self.assertEqual(snapshot["counts"]["emails"], 1)

    def test_update_task_status(self):
        created = self.client.post(
            "/task/create",
            json={"workspace_id": "demo", "title": "Draft slides"},
        ).json()
        task_id = created["task"]["id"]
        response = self.client.post(f"/task/{task_id}/status", json={"status": "done"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["task"]["status"], "done")


class ExecutorTests(unittest.TestCase):
    def test_execute_requires_tasks(self):
        client = TestClient(executor_app)
        response = client.post("/execute", json={"tasks": []})

        self.assertEqual(response.status_code, 400)

    @patch("executor.app.requests.post")
    def test_execute_runs_task_calendar_and_email_actions(self, mock_post):
        with patch("executor.app._request_headers", return_value={}):
            task_response = MagicMock()
            task_response.json.return_value = {"message": "task created"}
            task_response.raise_for_status.return_value = None

            calendar_response = MagicMock()
            calendar_response.json.return_value = {"message": "calendar event created"}
            calendar_response.raise_for_status.return_value = None

            email_response = MagicMock()
            email_response.json.return_value = {"message": "email draft created"}
            email_response.raise_for_status.return_value = None

            mock_post.side_effect = [task_response, calendar_response, email_response]

            client = TestClient(executor_app)
            response = client.post(
                "/execute",
                json={
                    "workspace_id": "demo",
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Rehearse presentation",
                            "summary": "Practice the demo",
                            "priority": "high",
                            "category": "review",
                            "estimated_minutes": 30,
                            "depends_on": [],
                            "success_criteria": ["Finish a full run-through"],
                            "schedule_hint": {
                                "date": "2026-04-09",
                                "start_time": "14:00",
                                "duration_minutes": 30,
                            },
                            "communication": {
                                "channel": "email",
                                "recipient": "team@example.com",
                                "subject": "Need presentation feedback",
                                "purpose": "Book a review slot",
                            },
                        }
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["summary"]["task_records"], 1)
            self.assertEqual(payload["summary"]["calendar_events"], 1)
            self.assertEqual(payload["summary"]["email_drafts"], 1)
            self.assertEqual(mock_post.call_count, 3)

    def test_execute_dry_run_returns_actions_without_network(self):
        client = TestClient(executor_app)
        response = client.post(
            "/execute",
            json={
                "workspace_id": "demo",
                "dry_run": True,
                "tasks": [
                    {
                        "id": "task-1",
                        "title": "Draft storyline",
                        "schedule_hint": {"date": "2026-04-09"},
                        "communication": {"channel": "email", "recipient": "team@example.com"},
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"][0]["actions"]), 3)


class RootAgentTests(unittest.TestCase):
    def setUp(self):
        self.original_planner_url = os.environ.get("PLANNER_URL")
        self.original_executor_url = os.environ.get("EXECUTOR_URL")
        self.original_mcp_url = os.environ.get("MCP_URL")
        os.environ["PLANNER_URL"] = "http://planner.test/plan"
        os.environ["EXECUTOR_URL"] = "http://executor.test/execute"
        os.environ["MCP_URL"] = "http://mcp.test"

    def tearDown(self):
        if self.original_planner_url is None:
            os.environ.pop("PLANNER_URL", None)
        else:
            os.environ["PLANNER_URL"] = self.original_planner_url

        if self.original_executor_url is None:
            os.environ.pop("EXECUTOR_URL", None)
        else:
            os.environ["EXECUTOR_URL"] = self.original_executor_url

        if self.original_mcp_url is None:
            os.environ.pop("MCP_URL", None)
        else:
            os.environ["MCP_URL"] = self.original_mcp_url

    @patch("requests.post")
    def test_handle_goal_runs_planner_then_executor(self, mock_post):
        module = load_root_agent_module()

        planner_response = MagicMock()
        planner_response.json.return_value = {
            "plan": {"workspace_id": "demo", "tasks": [{"id": "task-1", "title": "Plan"}]}
        }
        planner_response.raise_for_status.return_value = None

        executor_response = MagicMock()
        executor_response.json.return_value = {
            "message": "execution complete",
            "summary": {"task_records": 1},
        }
        executor_response.raise_for_status.return_value = None

        mock_post.side_effect = [planner_response, executor_response]

        with patch.object(module, "_request_headers", return_value={}):
            result = module.handle_goal("Prepare for robotics presentation")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["plan"]["workspace_id"], "demo")
        self.assertEqual(module.root_agent.kwargs["tools"][0].__name__, "handle_goal")
        self.assertEqual(module.root_agent.kwargs["tools"][1].__name__, "get_workspace_snapshot")

    @patch("requests.get")
    def test_workspace_snapshot_tool(self, mock_get):
        module = load_root_agent_module()

        snapshot_response = MagicMock()
        snapshot_response.json.return_value = {"counts": {"tasks": 1}}
        snapshot_response.raise_for_status.return_value = None
        mock_get.return_value = snapshot_response

        with patch.object(module, "_request_headers", return_value={}):
            result = module.get_workspace_snapshot("demo")

        self.assertEqual(result["counts"]["tasks"], 1)


if __name__ == "__main__":
    unittest.main()
