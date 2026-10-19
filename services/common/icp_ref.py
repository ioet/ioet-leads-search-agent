"""Load an IdealCustomerProfile from an icp-ref URI or the default ICP source."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.common.icp import IdealCustomerProfile, load_icp

logger = logging.getLogger(__name__)

# Matches services.api.storage.LOCAL_ROOT for local:// URIs written by the API.
_LOCAL_ICP_ROOT = Path(".cache/api-icps")


def load_icp_for_request(
    *,
    icp_ref: str | None = None,
    icp_version: str | None = None,
) -> IdealCustomerProfile:
    """Prefer ``icp_ref`` (s3:// or local://); otherwise the env/default ICP file."""
    ref = (icp_ref or "").strip()
    if ref:
        icp = IdealCustomerProfile.model_validate(_load_json_uri(ref))
        if icp_version and icp.version != icp_version:
            logger.warning(
                "icp_version %r does not match document version %r (ref=%s)",
                icp_version,
                icp.version,
                ref,
            )
        return icp

    icp = load_icp()
    if icp_version and icp.version != icp_version:
        raise ValueError(
            f"Unknown icp_version {icp_version!r}; loaded {icp.version!r}"
        )
    return icp


def _load_json_uri(uri: str) -> dict[str, Any]:
    if uri.startswith("s3://"):
        without = uri[len("s3://") :]
        bucket, _, key = without.partition("/")
        if not bucket or not key:
            raise ValueError(f"Invalid S3 URI: {uri}")
        import boto3

        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        raw = json.loads(obj["Body"].read().decode("utf-8"))
    elif uri.startswith("local://"):
        rel = uri[len("local://") :]
        path = _LOCAL_ICP_ROOT / rel
        if not path.is_file():
            raise ValueError(f"Missing local ICP object: {uri}")
        raw = json.loads(path.read_text(encoding="utf-8"))
    elif uri.startswith("/") or uri.startswith("."):
        raw = json.loads(Path(uri).read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported icp_ref scheme: {uri}")

    if not isinstance(raw, dict):
        raise ValueError("ICP JSON must be an object")
    return raw
