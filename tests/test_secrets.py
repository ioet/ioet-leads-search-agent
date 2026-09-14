"""Unit tests for Secrets Manager → environ bootstrap."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from services.common.secrets import _LOADED_FLAG, load_app_secret_into_environ


def test_load_app_secret_skips_when_arn_missing(monkeypatch):
    monkeypatch.delenv("APP_SECRET_ARN", raising=False)
    monkeypatch.delenv(_LOADED_FLAG, raising=False)
    load_app_secret_into_environ()
    assert _LOADED_FLAG not in __import__("os").environ


def test_load_app_secret_merges_without_overriding(monkeypatch):
    monkeypatch.setenv("APP_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123:secret:x")
    monkeypatch.setenv("EXISTING", "keep-me")
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    monkeypatch.delenv(_LOADED_FLAG, raising=False)

    fake = MagicMock()
    fake.get_secret_value.return_value = {
        "SecretString": json.dumps(
            {
                "APOLLO_API_KEY": "new-key",
                "EXISTING": "should-not-win",
                "EMPTY": "",
            }
        )
    }

    with patch("boto3.client", return_value=fake):
        load_app_secret_into_environ()

    import os

    assert os.environ["APOLLO_API_KEY"] == "new-key"
    assert os.environ["EXISTING"] == "keep-me"
    assert "EMPTY" not in os.environ or os.environ.get("EMPTY") == ""
    assert os.environ[_LOADED_FLAG] == "1"
