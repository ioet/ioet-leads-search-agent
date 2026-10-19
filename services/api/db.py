"""DynamoDB client and local table bootstrap."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError

from services.api import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def dynamodb_resource():
    kwargs: dict[str, Any] = {"region_name": settings.aws_region()}
    endpoint = settings.dynamodb_endpoint_url()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
        kwargs.setdefault("aws_access_key_id", os_access_key())
        kwargs.setdefault("aws_secret_access_key", os_secret_key())
    return boto3.resource("dynamodb", **kwargs)


def os_access_key() -> str:
    import os

    return os.environ.get("AWS_ACCESS_KEY_ID", "local")


def os_secret_key() -> str:
    import os

    return os.environ.get("AWS_SECRET_ACCESS_KEY", "local")


def users_table():
    return dynamodb_resource().Table(settings.users_table_name())


def refresh_tokens_table():
    return dynamodb_resource().Table(settings.refresh_tokens_table_name())


def icps_table():
    return dynamodb_resource().Table(settings.icps_table_name())


def campaigns_table():
    return dynamodb_resource().Table(settings.campaigns_table_name())


def schedules_table():
    return dynamodb_resource().Table(settings.schedules_table_name())


def campaign_runs_table():
    return dynamodb_resource().Table(settings.campaign_runs_table_name())


def ensure_tables() -> None:
    """Create API tables if missing (DynamoDB Local / first boot)."""
    client = dynamodb_resource().meta.client
    _ensure_users_table(client)
    _ensure_refresh_tokens_table(client)
    _ensure_simple_pk_table(client, settings.icps_table_name(), "icp_id")
    _ensure_simple_pk_table(client, settings.campaigns_table_name(), "campaign_id")
    _ensure_schedules_table(client)
    _ensure_campaign_runs_table(client)


def _table_exists(client, name: str) -> bool:
    try:
        client.describe_table(TableName=name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def _ensure_users_table(client) -> None:
    name = settings.users_table_name()
    if _table_exists(client, name):
        return
    logger.info("Creating DynamoDB table %s", name)
    client.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "user_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)


def _ensure_refresh_tokens_table(client) -> None:
    name = settings.refresh_tokens_table_name()
    if _table_exists(client, name):
        return
    logger.info("Creating DynamoDB table %s", name)
    client.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "token_hash", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "token_hash", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)


def _ensure_simple_pk_table(client, name: str, pk: str) -> None:
    if _table_exists(client, name):
        return
    logger.info("Creating DynamoDB table %s", name)
    client.create_table(
        TableName=name,
        AttributeDefinitions=[{"AttributeName": pk, "AttributeType": "S"}],
        KeySchema=[{"AttributeName": pk, "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)


def _ensure_schedules_table(client) -> None:
    name = settings.schedules_table_name()
    if _table_exists(client, name):
        return
    logger.info("Creating DynamoDB table %s", name)
    client.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "schedule_id", "AttributeType": "S"},
            {"AttributeName": "campaign_id", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "schedule_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "campaign_id-index",
                "KeySchema": [{"AttributeName": "campaign_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)


def _ensure_campaign_runs_table(client) -> None:
    name = settings.campaign_runs_table_name()
    if _table_exists(client, name):
        return
    logger.info("Creating DynamoDB table %s", name)
    client.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "run_id", "AttributeType": "S"},
            {"AttributeName": "campaign_id", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
        ],
        KeySchema=[{"AttributeName": "run_id", "KeyType": "HASH"}],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "campaign_id-created_at-index",
                "KeySchema": [
                    {"AttributeName": "campaign_id", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=name)


def reset_dynamodb_cache() -> None:
    """Clear cached resource (tests)."""
    dynamodb_resource.cache_clear()
