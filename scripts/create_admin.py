#!/usr/bin/env python3
"""Create (or promote) an admin user for the campaign API.

Usage:
  API_JWT_SECRET=dev DYNAMODB_ENDPOINT_URL=http://localhost:8000 \\
  API_ENSURE_TABLES=true \\
  python scripts/create_admin.py --email admin@ioet.com --password '...'
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.api.auth.passwords import hash_password
from services.api.db import ensure_tables
from services.api.models import UserRole, UserStatus
from services.api.stores import users as user_store
from services.api.stores.users import EmailAlreadyExistsError


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an admin user")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument(
        "--ensure-tables",
        action="store_true",
        default=os.environ.get("API_ENSURE_TABLES", "").lower() in {"1", "true", "yes"},
        help="Create DynamoDB tables if missing (local)",
    )
    args = parser.parse_args()

    email = args.email.strip().lower()
    if args.ensure_tables or os.environ.get("DYNAMODB_ENDPOINT_URL"):
        ensure_tables()

    existing = user_store.get_user_by_email(email)
    if existing:
        updated = user_store.update_user(
            existing.user_id,
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        # Refresh password
        from services.api.db import users_table
        from services.api.models import utc_now_iso

        users_table().update_item(
            Key={"user_id": existing.user_id},
            UpdateExpression="SET password_hash = :p, updated_at = :u REMOVE verification_token_hash",
            ExpressionAttributeValues={
                ":p": hash_password(args.password),
                ":u": utc_now_iso(),
            },
        )
        print(f"Updated existing user to active admin: {updated.user_id} ({email})")
        return 0

    try:
        user = user_store.create_user_if_email_free(
            email=email,
            password_hash=hash_password(args.password),
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
    except EmailAlreadyExistsError:
        print(f"Email already exists: {email}", file=sys.stderr)
        return 1

    print(f"Created admin user: {user.user_id} ({email})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
