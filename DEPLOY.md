# Productivity Multi-Agent Deployment Guide

This project now deploys as four Cloud Run services:

- `planner`: structured planning service, with optional Vertex-powered planning
- `mcp`: tool and persistence service, with optional Firestore storage
- `executor`: turns plan tasks into task records, scheduled events, and email drafts
- `productivity-agent`: the Google ADK root agent with UI

## Recommended production shape

Use private Cloud Run services for `planner`, `executor`, and `mcp`, all invoked with identity tokens from the same service account. Keep the ADK UI either private or public depending on demo needs.

## Pre-reqs

In Cloud Shell, from `~/productivity_multi_agent`:

```bash
export PROJECT_ID="$(gcloud config get-value project)"
export REGION="asia-south1"
export SERVICE_ACCOUNT="productivity-agent-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export REPO_ROOT="$HOME/productivity_multi_agent"
```

Enable services:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com
```

Create the runtime service account if it does not exist:

```bash
gcloud iam service-accounts create productivity-agent-sa \
  --display-name="Productivity Multi Agent"
```

Grant runtime access:

```bash
for ROLE in \
  roles/aiplatform.user \
  roles/logging.logWriter \
  roles/monitoring.metricWriter \
  roles/cloudtrace.agent \
  roles/datastore.user
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="$ROLE"
done
```

## Optional Firestore setup

If you want persistent task state, create a Firestore database once:

```bash
gcloud firestore databases create --location="$REGION"
```

Then deploy MCP with:

- `MCP_STORAGE_BACKEND=firestore`
- `FIRESTORE_PROJECT_ID=$PROJECT_ID`
- `FIRESTORE_COLLECTION_PREFIX=productivity`

If you skip this, MCP falls back to in-memory storage.

## Deploy backend services

Deploy `planner` first. This version supports an optional Vertex planner mode.

```bash
cd "$REPO_ROOT/planner"
gcloud run deploy planner \
  --source . \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --set-env-vars="ENABLE_VERTEX_PLANNER=true,PLANNER_MODEL=gemini-2.5-flash,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION}"
```

Deploy `mcp`:

```bash
cd "$REPO_ROOT/mcp"
gcloud run deploy mcp \
  --source . \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --set-env-vars="MCP_STORAGE_BACKEND=firestore,FIRESTORE_PROJECT_ID=${PROJECT_ID},FIRESTORE_COLLECTION_PREFIX=productivity"
```

If you want the simpler memory version for a quick demo:

```bash
cd "$REPO_ROOT/mcp"
gcloud run deploy mcp \
  --source . \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --set-env-vars="MCP_STORAGE_BACKEND=memory"
```

Capture the MCP URL and deploy `executor`:

```bash
export MCP_URL="$(gcloud run services describe mcp --region="$REGION" --format='value(status.url)')"

cd "$REPO_ROOT/executor"
gcloud run deploy executor \
  --source . \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --set-env-vars="MCP_URL=${MCP_URL},ENABLE_SERVICE_AUTH=true,REQUEST_TIMEOUT_SECONDS=30"
```

Allow private invocation:

```bash
for SERVICE in planner executor mcp; do
  gcloud run services add-iam-policy-binding "$SERVICE" \
    --region="$REGION" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/run.invoker"
done
```

Capture backend URLs for the ADK service:

```bash
export PLANNER_URL="$(gcloud run services describe planner --region="$REGION" --format='value(status.url)')/plan"
export EXECUTOR_URL="$(gcloud run services describe executor --region="$REGION" --format='value(status.url)')/execute"
export MCP_URL="$(gcloud run services describe mcp --region="$REGION" --format='value(status.url)')"
```

## Deploy the ADK root agent with UI

From the repo root:

```bash
cd "$REPO_ROOT"

uvx --from google-adk==1.14.0 adk deploy cloud_run \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --service_name=productivity-agent \
  --with_ui \
  . \
  -- \
  --service-account="$SERVICE_ACCOUNT" \
  --no-allow-unauthenticated \
  --set-env-vars="GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GOOGLE_CLOUD_LOCATION=${REGION},PLANNER_URL=${PLANNER_URL},EXECUTOR_URL=${EXECUTOR_URL},MCP_URL=${MCP_URL},ENABLE_SERVICE_AUTH=true,REQUEST_TIMEOUT_SECONDS=30"
```

If you want the UI public for judging or demo access, replace `--no-allow-unauthenticated` with `--allow-unauthenticated`.

## Validate each service

Planner:

```bash
export TOKEN="$(gcloud auth print-identity-token)"
curl -X POST "${PLANNER_URL}" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"goal":"Prepare for robotics presentation","workspace_id":"demo"}'
```

Executor:

```bash
export EXECUTOR_BASE="$(gcloud run services describe executor --region="$REGION" --format='value(status.url)')"
curl -X POST "${EXECUTOR_BASE}/execute" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"workspace_id":"demo","dry_run":true,"tasks":[{"id":"task-1","title":"Draft storyline","schedule_hint":{"date":"2026-04-10"},"communication":{"channel":"email","recipient":"team@example.com"}}]}'
```

MCP snapshot:

```bash
curl "${MCP_URL}/snapshot?workspace_id=demo" \
  -H "Authorization: Bearer ${TOKEN}"
```

ADK UI:

```bash
export AGENT_URL="$(gcloud run services describe productivity-agent --region="$REGION" --format='value(status.url)')"
echo "$AGENT_URL"
```

## Good demo prompts

- `Prepare me for a robotics presentation next Friday. Break it into tasks, schedule the work, and draft any follow-up communication.`
- `Create a launch plan for our hackathon prototype, then show me the workspace snapshot.`
- `Build a study plan for an AI interview and summarize the execution artifacts that were created.`

## Notes

- Planner gracefully falls back to a heuristic plan if Vertex generation fails.
- MCP gracefully falls back to in-memory storage if Firestore configuration is missing or invalid.
- The ADK root agent supports both workflow execution and workspace inspection.
