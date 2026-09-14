# Leads Search Agent

LittleHorse-orchestrated pipeline that discovers companies via Apollo, scores them against ioet's ICP, matches ioet skills from BambooHR, and publishes to HubSpot with Slack notifications.

## Layout

```
workflow/          WfSpecs, TaskDefs, thin LH workers (HTTP bridge)
services/          Microservices (agent, apollo, skills, hubspot, notify, jobs)
services/common/   Shared schemas, ICP model, HTTP helpers, secrets bootstrap
scripts/           Build/push images, refresh Lambda/ECS, register LH
data/icp.json      Canonical ICP configuration
```

## Prerequisites

- Python **3.13** (required by `littlehorse-client`; 3.14 is not supported yet)
- Docker (LittleHorse kernel + optional full stack)
- `lhctl` CLI ([install guide](https://littlehorse.io/docs/server/developer-guide/install))

## AWS deploy

Infrastructure lives in **infra-terraform** (`ioet-primary/ioet-leads-search`). This repo’s GitHub Actions workflow builds/pushes `:latest` images, refreshes Lambdas/ECS, uploads `data/icp.json` when it changes, and re-registers LittleHorse specs when `workflow/` changes.

See [docs/deploy.md](docs/deploy.md).

## Local setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run services

**Option A — Docker Compose (kernel + all services):**

```bash
docker compose up -d
```

- LittleHorse dashboard: http://localhost:8080
- Apollo: http://localhost:8001/health
- Agent: http://localhost:8002/health
- Skills: http://localhost:8003/health
- HubSpot: http://localhost:8004/health
- Notify: http://localhost:8005/health
- Jobs: http://localhost:8006/health

**Option B — run services individually:**

```bash
uvicorn services.apollo.app:app --port 8001 --reload
uvicorn services.agent.app:app --port 8002 --reload
uvicorn services.skills.app:app --port 8003 --reload
uvicorn services.hubspot.app:app --port 8004 --reload
uvicorn services.notify.app:app --port 8005 --reload
```

## Integration services (step 3)

| Service | Port | Endpoints |
|---------|------|-----------|
| apollo | 8001 | `POST /v1/search-companies`, `POST /v1/find-decision-makers` |
| agent | 8002 | `POST /v1/score-companies`, `POST /v1/match-skills`, `POST /v1/draft-outreach-email` |
| skills | 8003 | `GET /v1/catalog`, `POST /v1/lookup` |
| hubspot | 8004 | `POST /v1/sanitize-public-fields`, `POST /v1/upsert-lead` |
| notify | 8005 | `POST /v1/notify`, `POST /v1/failure` |
| jobs | 8006 | `POST /v1/extract-job-skills` |

Configure keys in `.env` (see `.env.example`). Missing credentials return HTTP 503. HubSpot `dry_run: true` skips CRM writes. Set `SLACK_WEBHOOK_URL` to post campaign/failure alerts to Slack (hybrid runners start real notify-service when set).

Agent service calls **AWS Bedrock Converse** over HTTPS with `AWS_BEDROCK_API_KEY` (Bearer token — same pattern as `birthday_slack_bot`) and pulls the skills catalog from the skills service for matching. ICP scoring and outreach drafting default to Google Gemma 3 27B (`AWS_BEDROCK_MODEL_ID_HIGH`); skill matching and job-skill extraction default to Gemma 3 4B (`AWS_BEDROCK_MODEL_ID_LOW`). Pass `model_id` on the agent request body to override.

## Local testing with mocks

Use `mocks/` to run fake Apollo, BambooHR (skills), and HubSpot services — only Bedrock is real:

```bash
./mocks/run_local_stack.sh
```

See [mocks/README.md](mocks/README.md) for manual setup and LittleHorse workflow instructions.

## Workflow

With LittleHorse + services up (`docker compose up -d`):

```bash
cp .env.example .env   # fill API keys as needed; dry_run skips HubSpot writes
python workflow/register.py   # register TaskDefs + WfSpecs
python workflow/workers.py    # start thin HTTP task workers
```

Parent WfSpec: `leads-search-workflow` — search, score, fan-out; **empty search** → Slack notify and exit  
Child WfSpec: `enrich-and-publish-lead` — enrich one company, extract job skills, draft outreach email, sync HubSpot upsert  

Architecture diagrams: [docs/architecture.html](docs/architecture.html) · [docs/architecture.md](docs/architecture.md)

Example run (after workers are polling):

```bash
lhctl run leads-search-workflow \
  icp-version 2026-08-26 \
  segment-ids '["primary"]' \
  campaign-id demo-001 \
  max-leads 5 \
  dry-run true
```

Campaign size: set `MAX_COMPANIES` and `MAX_CONTACTS_PER_COMPANY` in `.env` (workers use these when set; otherwise `max-leads` / defaults apply). Restart workers after changing them.

## Tests

```bash
pytest
```
