# Local mock integrations

Standalone FastAPI mocks that mirror the **same HTTP contracts** as `services/apollo`, `services/skills` (BambooHR), and `services/hubspot`. Use them to exercise the **real agent-service (Bedrock)** without external API keys.

**Hybrid mode:** if `APOLLO_API_KEY` is set in `.env`, `run_mocks.sh` / `run_local_stack.sh` start the **real** Apollo service on `:8001` and keep Bamboo/HubSpot/Notify/Jobs mocked.
Same pattern for Bamboo (`BAMBOOHR_API_KEY` + `BAMBOOHR_SUBDOMAIN`), HubSpot (`HUBSPOT_SERVICE_KEY`), and Slack (`SLACK_WEBHOOK_URL` → real notify-service on `:8005`).

## Quick start (all-in-one)

```bash
cp mocks/.env.example .env   # optional; Bedrock vars only
chmod +x mocks/run_local_stack.sh
./mocks/run_local_stack.sh
```

Requires `AWS_BEDROCK_API_KEY` (Bearer token — same as birthday_slack_bot).

## Manual (two terminals)

**Terminal 1 — mocks**

```bash
chmod +x mocks/run_mocks.sh
./mocks/run_mocks.sh
```

**Terminal 2 — real agent**

```bash
export SKILLS_SERVICE_URL=http://127.0.0.1:8003
export AWS_BEDROCK_API_KEY=your-key
export AWS_BEDROCK_REGION=us-east-1
export AWS_BEDROCK_MODEL_ID_HIGH=google.gemma-3-27b-it
export AWS_BEDROCK_MODEL_ID_LOW=google.gemma-3-4b-it
uvicorn services.agent.app:app --host 127.0.0.1 --port 8002 --reload
```

**Terminal 3 — demo**

```bash
python mocks/demo_agent_flow.py
```

## What the demo does

1. **Apollo** — real API when `APOLLO_API_KEY` is set; otherwise fixture companies
2. **Agent + Bedrock** — scores companies against ICP
3. **Apollo** — decision-maker contacts (real or mock, same as step 1)
4. **HubSpot mock** — sanitizes public fields
5. **Jobs mock + Bedrock** — extracts required skills from job postings
6. **Agent + Bedrock + bamboo mock** — matches ioet skills from the catalog
7. **Agent + Bedrock** — drafts a customer-centric outreach email (stored as HubSpot note)
8. **HubSpot mock** — upserts lead (`dry_run: true`) and stores payload in memory

Mock logs print every request/response body so you can see agent ↔ mock traffic.

## Inspect results

```bash
curl http://127.0.0.1:8004/v1/store | python3 -m json.tool
```

Each upsert is also written to the local filesystem (default: `.cache/hubspot-mock/`):

| File | Contents |
|------|----------|
| `store.json` | Full mock CRM aggregate — contacts and notes include a `company` ref |
| `leads/{domain}.json` | Latest lead per company (contacts, skill matches, outreach email) |
| `leads/{domain}-note.txt` | Outreach email / HubSpot note only — easy to read |
| `leads/history/` | Timestamped copy of every upsert |

In `store.json`, each contact and note has a `company` object (`id`, `key`, `name`, `domain`) so you can see which company they belong to without cross-referencing IDs.

```bash
cat .cache/hubspot-mock/leads/ledgerflow.ai-note.txt
ls .cache/hubspot-mock/leads/
```

Override output directory with `HUBSPOT_MOCK_OUTPUT_DIR` in `.env`.

Slack notifications (notify mock) are written to `.cache/notify-mock/`:

| File | Contents |
|------|----------|
| `latest-notify.txt` | Most recent campaign summary / notify message (Slack text) |
| `latest-failure.txt` | Most recent failure alert (Slack text) |
| `slack-feed.txt` | Append-only feed of all Slack messages |
| `messages.json` | Full message history with payloads |
| `history/` | Timestamped copy of each message |

```bash
cat .cache/notify-mock/latest-notify.txt
tail .cache/notify-mock/slack-feed.txt
```

Override with `NOTIFY_MOCK_OUTPUT_DIR` in `.env`.

## Full LittleHorse workflow with mocks

```bash
cp mocks/.env.example .env
./mocks/run_mocks.sh          # terminal 1
uvicorn services.agent.app:app --port 8002   # terminal 2 (Bedrock)
python workflow/register.py
python workflow/workers.py    # terminal 3 — uses SERVICE_URL_* from .env
```

## Ports

| Service | Port | Module |
|---------|------|--------|
| Apollo mock | 8001 | `mocks.apollo.app` |
| Agent (real) | 8002 | `services.agent.app` |
| Bamboo mock | 8003 | `mocks.bamboo.app` |
| HubSpot mock | 8004 | `mocks.hubspot.app` |
| Notify mock / real Slack | 8005 | `mocks.notify.app` or `services.notify.app` when `SLACK_WEBHOOK_URL` is set |
| Jobs mock | 8006 | `mocks.jobs.app` |

## Fixture data

Edit `mocks/data/fixtures.py` to add companies, contacts, or ioet employees/skills.
