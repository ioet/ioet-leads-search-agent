"""Outbound email for verification links (log locally, SES in prod)."""

from __future__ import annotations

import logging
import urllib.parse

import boto3

from services.api import settings

logger = logging.getLogger(__name__)


def send_verification_email(*, email: str, raw_token: str) -> None:
    verify_url = (
        f"{settings.public_base_url()}/verify-email"
        f"?token={urllib.parse.quote(raw_token)}"
    )
    subject = "Verify your Lead Agent account"
    body = (
        f"Confirm your email for Lead Agent Campaign Builder.\n\n"
        f"Open this link to activate your account:\n{verify_url}\n\n"
        f"If you did not sign up, ignore this message.\n"
    )
    mode = settings.email_mode()
    if mode == "ses":
        _send_ses(to=email, subject=subject, body=body)
        return
    logger.info("Verification email for %s (mode=%s):\n%s", email, mode, body)
    print(f"[api-email] To: {email}\nSubject: {subject}\n\n{body}", flush=True)


def _send_ses(*, to: str, subject: str, body: str) -> None:
    client = boto3.client("ses", region_name=settings.aws_region())
    client.send_email(
        Source=settings.ses_from_email(),
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )
