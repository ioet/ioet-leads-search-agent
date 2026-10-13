# Load IAM keys from infrastructure/terraform.tfvars and drop leftover SSO tokens.
# Source after ROOT is set:  # shellcheck source=aws_from_tfvars.sh
#   ROOT=...; source "$(dirname "$0")/aws_from_tfvars.sh"
set -euo pipefail

: "${ROOT:?ROOT must be set to the repo root before sourcing aws_from_tfvars.sh}"
TFVARS="${TFVARS:-$ROOT/infrastructure/terraform.tfvars}"

if [[ ! -f "$TFVARS" ]]; then
  echo "Missing ${TFVARS}" >&2
  echo "Copy terraform.tfvars.example and set aws_access_key_id / aws_secret_access_key" >&2
  exit 1
fi

unset AWS_SESSION_TOKEN AWS_SECURITY_TOKEN \
  AWS_PROFILE AWS_DEFAULT_PROFILE \
  AWS_ROLE_ARN AWS_ROLE_SESSION_NAME \
  AWS_WEB_IDENTITY_TOKEN_FILE \
  AWS_CONTAINER_CREDENTIALS_RELATIVE_URI \
  AWS_CONTAINER_CREDENTIALS_FULL_URI
export AWS_EC2_METADATA_DISABLED=true

eval "$(python3 - "$TFVARS" <<'PY'
import re
import shlex
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()


def get(key: str) -> str:
    match = re.search(
        rf"(?m)^\s*{re.escape(key)}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))",
        text,
    )
    if not match:
        return ""
    return (match.group(1) or match.group(2) or match.group(3) or "").strip()


access_key = get("aws_access_key_id")
secret_key = get("aws_secret_access_key")
session_token = get("aws_session_token")
if not access_key or not secret_key:
    sys.stderr.write("terraform.tfvars must set aws_access_key_id and aws_secret_access_key\n")
    sys.exit(1)
if access_key.endswith("..."):
    sys.stderr.write("Replace the placeholder AWS keys in terraform.tfvars\n")
    sys.exit(1)

print(f"export AWS_ACCESS_KEY_ID={shlex.quote(access_key)}")
print(f"export AWS_SECRET_ACCESS_KEY={shlex.quote(secret_key)}")
if session_token:
    print(f"export AWS_SESSION_TOKEN={shlex.quote(session_token)}")
    print(f"export AWS_SECURITY_TOKEN={shlex.quote(session_token)}")
print("export AWS_REGION=us-east-1")
print("export AWS_DEFAULT_REGION=us-east-1")
PY
)"

if ! ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"; then
  echo "AWS rejected the access key in terraform.tfvars." >&2
  echo "ExpiredToken / InvalidClientTokenId usually means a leftover SSO session, not a missing token field." >&2
  exit 1
fi
echo "Using AWS account ${ACCOUNT} (IAM access key from terraform.tfvars)"
