"""Environment-backed settings for the campaign API."""

from __future__ import annotations

import os


def allowed_email_domain() -> str:
    return os.environ.get("API_ALLOWED_EMAIL_DOMAIN", "ioet.com").strip().lower()


def jwt_secret() -> str:
    secret = os.environ.get("API_JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("API_JWT_SECRET is required")
    return secret


def access_token_ttl_seconds() -> int:
    return int(os.environ.get("API_ACCESS_TOKEN_TTL_SECONDS", "900"))


def refresh_token_ttl_seconds() -> int:
    return int(os.environ.get("API_REFRESH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))


def cookie_secure() -> bool:
    return os.environ.get("API_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}


def cookie_samesite() -> str:
    value = os.environ.get("API_COOKIE_SAMESITE", "lax").strip().lower()
    if value not in {"lax", "strict", "none"}:
        return "lax"
    return value


def access_cookie_name() -> str:
    return os.environ.get("API_ACCESS_COOKIE", "access_token")


def refresh_cookie_name() -> str:
    return os.environ.get("API_REFRESH_COOKIE", "refresh_token")


def public_base_url() -> str:
    """Base URL used in verification emails (e.g. http://localhost:5173)."""
    return os.environ.get("API_PUBLIC_BASE_URL", "http://localhost:8010").rstrip("/")


def email_mode() -> str:
    """``log`` prints links locally; ``ses`` sends via Amazon SES."""
    return os.environ.get("API_EMAIL_MODE", "log").strip().lower()


def ses_from_email() -> str:
    return os.environ.get("API_SES_FROM_EMAIL", "noreply@ioet.com").strip()


def users_table_name() -> str:
    return os.environ.get("API_USERS_TABLE", "leads-api-users")


def refresh_tokens_table_name() -> str:
    return os.environ.get("API_REFRESH_TOKENS_TABLE", "leads-api-refresh-tokens")


def icps_table_name() -> str:
    return os.environ.get("API_ICPS_TABLE", "leads-api-icps")


def campaigns_table_name() -> str:
    return os.environ.get("API_CAMPAIGNS_TABLE", "leads-api-campaigns")


def schedules_table_name() -> str:
    return os.environ.get("API_SCHEDULES_TABLE", "leads-api-schedules")


def campaign_runs_table_name() -> str:
    return os.environ.get("API_CAMPAIGN_RUNS_TABLE", "leads-api-campaign-runs")


def icp_files_bucket() -> str:
    """S3 bucket for ICP PDFs/JSON. Empty → local `.cache/api-icps`."""
    return (
        os.environ.get("API_ICP_FILES_BUCKET", "").strip()
        or os.environ.get("ICP_S3_BUCKET", "").strip()
    )


def dynamodb_endpoint_url() -> str | None:
    url = os.environ.get("DYNAMODB_ENDPOINT_URL", "").strip()
    return url or None


def aws_region() -> str:
    return os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))


def internal_service_token() -> str:
    """Shared secret for worker → API callbacks (X-Internal-Token)."""
    return os.environ.get("API_INTERNAL_SERVICE_TOKEN", "").strip()


def campaign_api_base_url() -> str:
    """Base URL workers use to callback into this API."""
    return os.environ.get(
        "CAMPAIGN_API_BASE_URL",
        os.environ.get("API_PUBLIC_BASE_URL", "http://localhost:8010"),
    ).rstrip("/")
