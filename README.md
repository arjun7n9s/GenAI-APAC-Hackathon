# Productivity Multi-Agent on Google ADK

This project is a cloud-native multi-agent productivity system built around a master Google ADK agent and three specialized services:

- `planner`: turns an open-ended goal into a structured execution plan
- `executor`: converts plan tasks into tool actions
- `mcp`: acts as the tool hub for task records, calendar events, and communication drafts
- `root_agent`: the ADK entrypoint and UI-facing orchestrator

## Why this is stronger now

- The planner now returns structured plans with task dependencies, priorities, timing hints, risks, and communication actions.
- The executor now performs multi-step execution instead of only forwarding task titles.
- MCP now supports snapshots, task updates, email drafts, and optional Firestore-backed persistence for Cloud Run.
- The root agent can both execute a new goal and inspect existing workspace state.
- Cloud Run private service-to-service authentication is built in through Google-signed identity tokens.

## Local structure

```text
agents/main_agent/root_agent.py   ADK master agent
planner/app.py                    planning microservice
executor/app.py                   execution microservice
mcp/app.py                        tool and persistence microservice
DEPLOY.md                         Cloud Run deployment guide
tests/test_workflow.py            local verification
```

## Useful prompts

- `Prepare me for a robotics presentation next Friday and summarize what gets scheduled.`
- `Show me the current workspace snapshot.`
- `Create a launch plan for our hackathon demo and identify the riskiest tasks first.`
