# AWS deploy (app repo)

Terraform in [`infrastructure/`](../infrastructure/README.md) provisions AWS
(same config and S3 state as `infra-terraform/ioet-primary/ioet-leads-search`).
GitHub Actions still only ships images, refreshes runtime, uploads ICP, and
registers LittleHorse.

## GitHub Actions secrets / variables

| Name | Type | Required | Notes |
|------|------|----------|--------|
| `AWS_ROLE_ARN` | secret | yes | `terraform output -raw github_actions_role_arn` |
| `ICP_BUCKET` | variable | for ICP upload | `terraform output -raw icp_bucket` (random suffix) |
| `ICP_S3_KEY` | variable | no | default `icp/icp.json` |
| `WEB_BUCKET` | variable | for SPA deploy | `terraform output -raw web_bucket` |
| `CLOUDFRONT_DISTRIBUTION_ID` | variable | for SPA deploy | `terraform output -raw cloudfront_distribution_id` |
| `AWS_REGION` | variable | no | default `us-east-1` |
| `LITTLEHORSE_PORT` | variable | no | default `2023` (host comes from Secrets Manager) |

Do **not** put `LHC_API_HOST` in GitHub secrets — it lives in Secrets Manager (`leads-search-agent-prod/app`) with OAuth and API keys. CI registration loads it via `GetSecretValue`.

## What CI does

| Trigger | Job |
|---------|-----|
| changes under `services/`, Dockerfiles, `requirements` | build/push `:latest` → refresh Lambdas (by **digest**) + ECS |
| changes under `workflow/` | same image refresh + register TaskDefs/WfSpecs |
| changes to `data/icp.json` | `aws s3 cp` to `ICP_BUCKET` |
| changes under `web/` | build SPA with `VITE_ICP_API_URL` from the icp Function URL → `s3 sync` + CloudFront invalidation |
| `workflow_dispatch` | toggles for images / ICP / register / web |

## One-time (infra)

1. `cp infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars` and set AWS keys.
2. `./scripts/apply_infra.sh` — bootstraps ECR / GitHub role / S3 / secret, pushes `:latest`, applies Lambdas + ECS, uploads ICP.
3. Fill Secrets Manager (`secret_arn`): API keys, **`LHC_API_HOST`**, LH OAuth / tenant.
4. Set GitHub secret `AWS_ROLE_ARN` and variables `ICP_BUCKET`, `WEB_BUCKET`, `CLOUDFRONT_DISTRIBUTION_ID` from terraform outputs (`cloudfront_url` is the admin UI).
5. `./scripts/register_lh.sh` (or Actions) and `./scripts/deploy_web.sh`.

## Local scripts

```bash
./scripts/apply_infra.sh             # terraform + images + ICP (needs terraform.tfvars)
./scripts/build_and_push.sh          # :latest to ECR
./scripts/refresh_runtime.sh         # Lambda UpdateFunctionCode @digest + ECS force deploy
./scripts/register_lh.sh             # prod: host + OAuth from Secrets Manager
./scripts/register_lh.sh --local     # local docker-compose LH (localhost:2023 PLAINTEXT)
./scripts/deploy_web.sh              # build React SPA → CloudFront origin
```
