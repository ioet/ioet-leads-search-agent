"""Load Secrets Manager JSON into os.environ for Lambda cold starts.

Infra sets APP_SECRET_ARN on each function. Service code still reads
APOLLO_API_KEY / HUBSPOT_SERVICE_KEY / etc. from the environment.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_LOADED_FLAG = "_APP_SECRET_LOADED"


def load_app_secret_into_environ(*, force: bool = False) -> None:
    """Merge APP_SECRET_ARN JSON into os.environ (does not override non-empty vars)."""
    if not force and os.environ.get(_LOADED_FLAG) == "1":
        return

    arn = os.environ.get("APP_SECRET_ARN", "").strip()
    if not arn:
        return

    try:
        import boto3
    except ImportError:
        logger.warning("boto3 unavailable; skipping APP_SECRET_ARN load")
        return

    try:
        client = boto3.client("secretsmanager")
        raw = client.get_secret_value(SecretId=arn)["SecretString"]
        data = json.loads(raw)
    except Exception:
        logger.exception("Failed to load secret %s", arn)
        raise

    if not isinstance(data, dict):
        raise ValueError(f"Secret {arn} must be a JSON object")

    for key, value in data.items():
        if value is None:
            continue
        text = str(value).strip() if isinstance(value, str) else str(value)
        if text == "":
            continue
        if os.environ.get(key, "").strip():
            continue
        os.environ[key] = text

    os.environ[_LOADED_FLAG] = "1"
