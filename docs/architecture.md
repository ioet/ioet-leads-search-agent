# Leads Search Agent — Architecture

**Current implementation:** two WfSpecs (parent + child), thin workers → HTTP microservices, **direct synchronous** calls to HubSpot and Slack (no SQS queue). Target AWS layout uses **LittleHorse Cloud** + ECS workers + Lambda Function URLs; local dev uses docker-compose + uvicorn.

> **How to view the graphs:** Cursor’s markdown editor shows Mermaid as source code.
> - **Browser:** open [`docs/architecture.html`](architecture.html)
> - **IDE canvas:** [leads-search-architecture.canvas.tsx](/Users/ivan/.cursor/projects/Users-ivan-ioet-repos-leads-search-agent/canvases/leads-search-architecture.canvas.tsx)
>
> Future design (not built): [outbound-queue-design.md](./outbound-queue-design.md)

---

## 1. AWS target deployment

```mermaid
flowchart TB
  subgraph triggers["Triggers"]
    LHCTL["lhctl CLI"]
    Dashboard["LH Cloud Dashboard"]
    Schedule["EventBridge → Scheduled WfRun"]
  end

  subgraph aws_compute["AWS compute"]
    subgraph worker_box["ECS Fargate"]
      Workers["workflow/workers.py<br/>LHTaskWorker pollers"]
    end
    subgraph lambda["Lambda — Function URLs"]
      LamApollo["apollo-service"]
      LamAgent["agent-service"]
      LamSkills["skills-service"]
      LamHub["hubspot-service"]
      LamNotify["notify-service"]
      LamJobs["jobs-service"]
    end
  end

  subgraph managed["Managed / SaaS"]
    LHCloud["LittleHorse Cloud"]
    SM["Secrets Manager"]
    CW["CloudWatch Logs"]
    S3["S3 — icp.json + skills catalogs"]
    Bedrock["Bedrock Converse API"]
  end

  subgraph saas["External SaaS"]
    ApolloAPI["Apollo.io"]
    Bamboo["BambooHR"]
    HS["HubSpot"]
    Slack["Slack"]
  end

  LHCTL --> LHCloud
  Dashboard --> LHCloud
  Schedule --> LHCloud

  Workers -->|"gRPC poll / execute tasks"| LHCloud
  Workers -->|"HTTPS POST"| LamApollo
  Workers -->|"HTTPS POST"| LamAgent
  Workers -->|"HTTPS POST"| LamSkills
  Workers -->|"HTTPS POST"| LamHub
  Workers -->|"HTTPS POST"| LamNotify
  Workers -->|"HTTPS POST"| LamJobs
  Workers -->|"catalog-ref → S3"| S3

  LamApollo --> ApolloAPI
  LamAgent --> Bedrock
  LamSkills --> Bamboo
  LamHub --> HS
  LamNotify --> Slack
  LamJobs --> Bedrock

  LamApollo --> SM
  LamAgent --> SM
  LamSkills --> SM
  LamHub --> SM
  LamNotify --> SM
  LamJobs --> SM
  LamAgent --> S3
  Workers --> CW
  lambda --> CW
```

### Runtime placement

| Component | Runtime | Why |
|-----------|---------|-----|
| **LittleHorse Kernel** | LittleHorse Cloud | Durable workflow state, WfRun orchestration, dashboard |
| **Task workers** (`workers.py`) | ECS Fargate | Long-polling gRPC to LH — not suitable for Lambda |
| **Integration services** (`services/*`) | Lambda + Function URL | Stateless HTTP; scale per invocation; no idle cost |
| **ICP config** | S3 (+ git) | Versioned object loaded at runtime |
| **Skills catalog (per campaign)** | S3 | Large Bamboo snapshot; LH only stores `catalog-ref` |
| **API keys / LH OAuth** | Secrets Manager | Apollo, HubSpot, BambooHR, Slack, Bedrock, LH Cloud |
| **LLM inference** | Bedrock (managed) | Agent/jobs call Converse via Bearer `AWS_BEDROCK_API_KEY` |
| **WfSpec registration** | CI / one-off (`register.py`) | Against LH Cloud |

Terraform for AWS lives in **infra-terraform** (`ioet-primary/ioet-leads-search`). This app repo ships container images, refreshes Lambda/ECS, uploads `icp.json`, and registers WfSpecs — see [deploy.md](./deploy.md).

---

## 2. Combined workflow (parent + child)

Single view of both WfSpecs — open [`architecture.html`](architecture.html) in a browser to render.

```mermaid
flowchart TD
  S1["search-companies"] --> S2["count-companies (local)"]
  S2 --> C0{"count = 0?"}

  C0 -->|"yes"| E1["build-empty-search-notification (local)"]
  E1 --> N["notify → POST /v1/notify"]

  C0 -->|"no"| S3["score-companies-icp"]
  S3 --> S4["select-top-leads (local)"]
  S4 --> S4b["fetch-ioet-skills-catalog (local)"]
  S4b --> S5["spawn child per lead"]

  S5 --> C1

  subgraph child ["enrich-and-publish-lead (×N)"]
    direction LR
    C1["find-decision-makers"] --> C2["sanitize-public-fields"]
    C2 --> C2b["extract-job-skills"]
    C2b --> C3["match-ioet-skills"]
    C3 --> C3b["draft-outreach-email"]
    C3b --> C4["upsert-hubspot"]
    C4 --> C5["complete(lead)"]
  end

  C5 --> S6["build-campaign-summary (local)"]
  S6 --> N

  N --> Done(["complete / Done"])
```

`(local)` = task runs in the worker process, no HTTP microservice. Each failed step uses LH retries, then `notify-failure` → Slack; the campaign continues.

---

## 3. End-to-end WfSpec hierarchy (compact)

Two WfSpecs today — no grandchild, no async outbound queue.

```mermaid
flowchart TB
  subgraph parent["leads-search-workflow"]
    P1["search-companies"]
    P2["count-companies"]
    P3{"count = 0?"}
    P4["build-empty-search-notification"]
    P5["notify"]
    P6["score → select → fan-out"]
    P7["build-campaign-summary"]
    P1 --> P2 --> P3
    P3 -->|yes| P4 --> P5
    P3 -->|no| P6
    P6 --> P7 --> P5
  end

  subgraph child["enrich-and-publish-lead (×N)"]
    C1["find-decision-makers"]
    C2["sanitize-public-fields"]
    C2b["extract-job-skills"]
    C3["match-ioet-skills"]
    C3b["draft-outreach-email"]
    C4["upsert-hubspot"]
    C5["complete(lead)"]
    C1 --> C2 --> C2b --> C3 --> C3b --> C4 --> C5
  end

  P6 -->|"run_wf + wait_for_child_wf"| child
```

---

## 4. Request flow

```mermaid
sequenceDiagram
  participant T as Trigger
  participant LH as LH Kernel
  participant W as Task Worker
  participant Svc as Microservice
  participant Ext as External API

  T->>LH: start leads-search-workflow
  LH->>W: search-companies
  W->>Svc: POST apollo /v1/search-companies
  Svc->>Ext: Apollo.io
  Ext-->>Svc: companies
  Svc-->>W: JSON
  W-->>LH: complete

  LH->>W: count-companies (local)
  W-->>LH: count

  alt count = 0
    LH->>W: build-empty-search-notification (local)
    LH->>W: notify
    W->>Svc: POST notify /v1/notify
    Svc->>Ext: Slack webhook
  else count > 0
    LH->>W: score-companies-icp
    W->>Svc: POST agent /v1/score-companies
    Svc->>Ext: Bedrock Converse
    LH->>W: select-top-leads (local)
    loop each selected company
      LH->>LH: run enrich-and-publish-lead
      LH->>W: find-decision-makers → match-ioet-skills
      LH->>W: upsert-hubspot
      W->>Svc: POST hubspot /v1/upsert-lead
      Svc->>Ext: HubSpot CRM (sync)
      Svc-->>W: lead + hubspot_ids
    end
    LH->>W: build-campaign-summary (local)
    LH->>W: notify
    W->>Svc: POST notify /v1/notify
    Svc->>Ext: Slack webhook
  end
```

---

## 5. Local development (current)

Same worker → HTTP pattern; services run as uvicorn instead of Lambda.

```mermaid
flowchart LR
  subgraph local["docker compose + host processes"]
    LHL["LH standalone :2023"]
    SVC["uvicorn services :8001–8005"]
    Wrk["python workflow/workers.py"]
    Reg["python workflow/register.py"]
  end

  subgraph optional["Optional mocks"]
    Mocks["mocks/ fake Apollo, Bamboo, HubSpot"]
  end

  Reg --> LHL
  Wrk -->|"poll"| LHL
  Wrk -->|"HTTP localhost"| SVC
  Wrk -.-> Mocks
```

See [mocks/README.md](../mocks/README.md) for offline demos.

---

## 6. IAM & networking (planned)

```mermaid
flowchart LR
  subgraph roles["IAM roles"]
    WorkerRole["EC2 worker role<br/>invoke Function URLs"]
    AgentRole["agent Lambda role<br/>bedrock:InvokeModel"]
    SkillsRole["skills Lambda role<br/>read BambooHR secret"]
  end

  subgraph net["Network"]
    VPC["VPC"]
    EC2Priv["EC2 private subnet<br/>LH + workers"]
    LambdaVPC["Lambda optional VPC<br/>for BambooHR IP allowlist"]
  end

  WorkerRole --> LambdaVPC
  AgentRole --> Bedrock
  EC2Priv --> VPC
```

---

## 7. Workflow steps (implemented)

Same graph runs locally and in AWS — only the runtime hosting changes.

**Parent:** `leads-search-workflow`

```mermaid
flowchart TD
  S1["search-companies"] --> C["count-companies (local)"]
  C -->|"count = 0"| B1["build-empty-search-notification (local)"]
  B1 --> N["notify → POST /v1/notify"]
  N --> E1["complete"]
  C -->|"count > 0"| S2["score-companies-icp"]
  S2 --> S3["select-top-leads (local)"]
  S3 --> S3b["fetch-ioet-skills-catalog (local)"]
  S3b --> S4["spawn child per lead"]
  S4 --> S5["build-campaign-summary (local)"]
  S5 --> N
```

Both notify branches use the same **`notify`** task → `POST /v1/notify`. Local build tasks format `{ message, details }`; notify posts to Slack directly. Step errors use **`notify-failure`** → `POST /v1/failure`.

**Child:** `enrich-and-publish-lead` — `upsert-hubspot` calls HubSpot **synchronously** via hubspot-service (`dry_run` skips CRM writes).

```mermaid
flowchart LR
  T1["find-decision-makers"] --> T2["sanitize-public-fields"]
  T2 --> T2b["extract-job-skills"]
  T2b --> T3["match-ioet-skills"]
  T3 --> T3b["draft-outreach-email"]
  T3b --> T4["upsert-hubspot → HubSpot API"]
  T4 --> Done["complete(lead)"]
```

---

## 8. Task → service mapping

| TaskDef | Runtime | HTTP endpoint |
|---------|---------|---------------|
| `search-companies` | apollo Lambda | `POST /v1/search-companies` |
| `score-companies-icp` | agent Lambda | `POST /v1/score-companies` |
| `find-decision-makers` | apollo Lambda | `POST /v1/find-decision-makers` |
| `sanitize-public-fields` | hubspot Lambda | `POST /v1/sanitize-public-fields` |
| `extract-job-skills` | jobs Lambda → Bedrock | `POST /v1/extract-job-skills` |
| `match-ioet-skills` | agent Lambda | `POST /v1/match-skills` |
| `draft-outreach-email` | agent Lambda | `POST /v1/draft-outreach-email` |
| `upsert-hubspot` | hubspot Lambda | `POST /v1/upsert-lead` |
| `notify` | notify Lambda | `POST /v1/notify` |
| `notify-failure` | notify Lambda | `POST /v1/failure` |
| `count-companies` | local worker | — |
| `build-empty-search-notification` | local worker | — |
| `build-campaign-summary` | local worker | — |
| `fetch-ioet-skills-catalog` | local worker → skills HTTP (once per campaign) | — |
| `select-top-leads` | local worker | — |

**External writes (sync today):** `upsert-hubspot` → HubSpot CRM; `notify` / `notify-failure` → Slack webhook.

---

## 9. Repository layout

```
leads-search-agent/
├── workflow/
│   ├── register.py          → CI / operator (registers WfSpecs to LH Cloud)
│   ├── workers.py           → ECS Fargate (long-lived pollers)
│   └── workflows/           → compiled into LH kernel via register.py
├── services/
│   ├── apollo/              → Lambda Function URL
│   ├── agent/               → Lambda Function URL (+ Bedrock)
│   ├── skills/              → Lambda Function URL
│   ├── hubspot/             → Lambda Function URL
│   ├── notify/              → Lambda Function URL
│   └── jobs/                → Lambda Function URL
├── scripts/                 → build/push, refresh runtime, register LH
├── data/icp.json            → uploaded to S3 by CI when changed
└── docker-compose.yml       → local dev only
```

AWS Terraform: `infra-terraform/ioet-primary/ioet-leads-search`.

---

## Related docs

- [Architecture plan](./leads_agent_architecture.plan.md) — design rationale and phases
- [outbound-queue-design.md](./outbound-queue-design.md) — **deferred** SQS outbound pattern
- [README](../README.md) — local setup and run commands
- [deploy.md](./deploy.md) — app-repo CI deploy (images, ICP, LH register)
