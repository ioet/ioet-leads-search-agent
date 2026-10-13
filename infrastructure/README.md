# AWS infrastructure (ioet-primary)

Same stack as `infra-terraform/ioet-primary/ioet-leads-search` (shared S3 backend, VPC, names, and tags). GitHub Actions still only builds images, refreshes Lambda/ECS, uploads ICP, and registers LittleHorse.

| Component | Runtime |
|-----------|---------|
| apollo, agent, skills, hubspot, notify, jobs, icp | Lambda + Function URL (`NONE` auth) |
| ICP admin UI | CloudFront + private S3 (`cloudfront_url` output) |
| workflow workers | ECS Fargate (public subnets in `ioet-primary` VPC) |
| LittleHorse kernel | LittleHorse Cloud (host from Secrets Manager; port 2023 / TLS) |
| API keys / LH host / LH OAuth | Secrets Manager (read at runtime) |
| ICP + skills catalogs | S3 (CI or `apply_infra.sh` uploads `icp.json`) |
| Images | ECR (`…-services`, `…-workers`) |

## Apply (credentials only)

```bash
cp infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
# set aws_access_key_id and aws_secret_access_key (session token if using SSO)
./scripts/apply_infra.sh
```

That script exports the keys for the S3 backend and AWS CLI, bootstraps ECR / GitHub role / S3 / secret, pushes `:latest` images, applies Lambdas + ECS, and uploads `data/icp.json`.

Requires Terraform **>= 1.5.0**, Docker, and AWS credentials that can use `ioet-primary` (VPC, GitHub OIDC provider, tfstate bucket `ioet-primary-tfstates-eb4b4dac1df7f095`).

## Manual apply

```bash
cd infrastructure
terraform init
terraform apply   # needs images already in ECR for Lambdas/ECS
```

Image-based Lambdas and the ECS task need an image in ECR. Bootstrap first if you are not using `apply_infra.sh`:

```bash
terraform apply \
  -target=aws_ecr_repository.services \
  -target=aws_ecr_repository.workers \
  -target=aws_ecr_lifecycle_policy.services \
  -target=aws_ecr_lifecycle_policy.workers \
  -target=aws_iam_role.github_actions \
  -target=aws_iam_role_policy.github_actions \
  -target=aws_s3_bucket.icp \
  -target=aws_s3_bucket_public_access_block.icp \
  -target=aws_s3_bucket_server_side_encryption_configuration.icp \
  -target=aws_s3_bucket_versioning.icp \
  -target=aws_s3_bucket_policy.icp \
  -target=aws_secretsmanager_secret.app \
  -target=aws_secretsmanager_secret_version.app
```

Store `github_actions_role_arn` as GitHub secret `AWS_ROLE_ARN`. Push images (`./scripts/build_and_push.sh`), then `terraform apply`.

Fill `${prefix}/app` in Secrets Manager (`secret_arn` output). Terraform ignores later edits to the secret value.

## After apply

- **Images:** `leads-search-agent-prod-services` and `leads-search-agent-prod-workers` (`:latest` by default). CI refreshes Lambdas (`UpdateFunctionCode`) and forces a new ECS deployment.
- **ICP:** `aws s3 cp data/icp.json s3://$(terraform output -raw icp_bucket)/icp/icp.json`
- **ICP admin:** `terraform output -raw cloudfront_url` then `./scripts/deploy_web.sh`
- **Lambdas:** each function gets `APP_SECRET_ARN`; handlers load that JSON into `os.environ` on cold start.
- **Workers:** ECS injects `LHC_API_HOST`, `LHC_OAUTH_*`, and `LHC_TENANT_ID` from the same secret at task start. Set `LHC_API_HOST` in the secret (not in Terraform).
