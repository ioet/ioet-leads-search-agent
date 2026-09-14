# AWS deploy (app repo)

AWS resources are managed in
[`infra-terraform/ioet-primary/ioet-leads-search`](https://github.com/ioet/infra-terraform)
(manual `terraform apply`). This repo only ships images, refreshes runtime, uploads ICP, and registers LittleHorse.

## GitHub Actions secrets / variables

| Name | Type | Required | Notes |
|------|------|----------|--------|
| `AWS_ROLE_ARN` | secret | yes | `terraform output -raw github_actions_role_arn` |
| `ICP_BUCKET` | variable | for ICP upload | `terraform output -raw icp_bucket` (random suffix) |
| `ICP_S3_KEY` | variable | no | default `icp/icp.json` |
| `AWS_REGION` | variable | no | default `us-east-1` |
| `LITTLEHORSE_PORT` | variable | no | default `2023` (host comes from Secrets Manager) |

Do **not** put `LHC_API_HOST` in GitHub secrets — it lives in Secrets Manager (`leads-search-agent-prod/app`) with OAuth and API keys. CI registration loads it via `GetSecretValue`.

## What CI does

| Trigger | Job |
|---------|-----|
| changes under `services/`, Dockerfiles, `requirements` | build/push `:latest` → refresh Lambdas (by **digest**) + ECS |
| changes under `workflow/` | same image refresh + register TaskDefs/WfSpecs |
| changes to `data/icp.json` | `aws s3 cp` to `ICP_BUCKET` |
| `workflow_dispatch` | toggles for images / ICP / register |

## One-time (infra + this repo)

1. In `infra-terraform/ioet-primary/ioet-leads-search`, bootstrap ECR / GitHub role / S3 / secret (see that README), then set `AWS_ROLE_ARN` here.
2. Push `:latest` images (`./scripts/build_and_push.sh` or Actions).
3. Full `terraform apply` in infra (Lambdas + ECS need an image).
4. Fill Secrets Manager (`secret_arn`): API keys, **`LHC_API_HOST`**, LH OAuth / tenant.
5. Set `ICP_BUCKET`, upload ICP, register LH (Actions or scripts).

## Local scripts

```bash
./scripts/build_and_push.sh          # :latest to ECR
./scripts/refresh_runtime.sh         # Lambda UpdateFunctionCode @digest + ECS force deploy
./scripts/register_lh.sh             # host + OAuth from Secrets Manager
```
