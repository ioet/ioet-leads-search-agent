"""Worker skills catalog durable store tests."""

import asyncio

import pytest
from unittest.mock import MagicMock, patch

from services.common.catalog_store import CatalogNotFoundError
from workflow.workers import fetch_ioet_skills_catalog_task, match_ioet_skills_task


def test_fetch_ioet_skills_catalog_persists_only() -> None:
    catalog = [
        {
            "employee_id": "1",
            "display_name": "Grace Hopper",
            "skills": ["Python"],
        }
    ]
    ctx = MagicMock()

    class _WfRunId:
        id = "parent-wf-123"

    ctx.wf_run_id = _WfRunId()

    with (
        patch("workflow.workers.fetch_skills_catalog", return_value=catalog),
        patch("workflow.workers.save_skills_catalog") as save_mock,
    ):
        ref = asyncio.run(fetch_ioet_skills_catalog_task(ctx))

    assert ref == "parent-wf-123"
    saved = [call.args for call in save_mock.call_args_list]
    assert ("parent-wf-123", catalog) in saved
    assert ("latest", catalog) in saved


def test_fetch_ioet_skills_catalog_falls_back_to_latest_on_timeout(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SKILLS_CATALOG_LOCAL_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    monkeypatch.delenv("SKILLS_CATALOG_STORAGE", raising=False)
    from services.common.catalog_store import load_skills_catalog, save_skills_catalog

    previous = [{"employee_id": "7", "display_name": "Linus", "skills": ["Go"]}]
    save_skills_catalog("latest", previous)

    ctx = MagicMock()

    class _WfRunId:
        id = "parent-wf-timeout"

    ctx.wf_run_id = _WfRunId()

    with patch("workflow.workers.fetch_skills_catalog", side_effect=TimeoutError("read timed out")):
        ref = asyncio.run(fetch_ioet_skills_catalog_task(ctx))

    assert ref == "parent-wf-timeout"
    assert load_skills_catalog("parent-wf-timeout") == previous


def test_fetch_ioet_skills_catalog_raises_without_snapshot(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SKILLS_CATALOG_LOCAL_DIR", str(tmp_path))
    monkeypatch.delenv("SKILLS_CATALOG_S3_BUCKET", raising=False)
    monkeypatch.delenv("SKILLS_CATALOG_STORAGE", raising=False)
    ctx = MagicMock()

    class _WfRunId:
        id = "parent-wf-none"

    ctx.wf_run_id = _WfRunId()

    with patch("workflow.workers.fetch_skills_catalog", side_effect=TimeoutError("read timed out")):
        with pytest.raises(Exception, match="read timed out"):
            asyncio.run(fetch_ioet_skills_catalog_task(ctx))


def test_match_ioet_skills_loads_from_durable_store() -> None:
    catalog = [
        {
            "employee_id": "2",
            "display_name": "Ana Rodriguez",
            "skills": ["Python", "AWS"],
        }
    ]
    lead = {
        "company": {"name": "Acme", "domain": "acme.com"},
        "job_context": {"required_skills": ["Python"], "postings": []},
    }
    ctx = MagicMock()

    async def _fake_post(task_name, path, payload):
        assert payload["skills_catalog"] == catalog
        return {"company": lead["company"], "skill_matches": [], "status": "matched"}

    with (
        patch("workflow.workers.require_skills_catalog", return_value=catalog),
        patch("workflow.workers.fetch_skills_catalog") as fetch_mock,
        patch("workflow.workers.post_json", side_effect=_fake_post),
    ):
        result = asyncio.run(match_ioet_skills_task(lead, "parent-wf-999", ctx))

    fetch_mock.assert_not_called()
    assert result["status"] == "matched"


def test_match_ioet_skills_fails_when_durable_store_missing() -> None:
    lead = {
        "company": {"name": "Acme", "domain": "acme.com"},
        "job_context": {"required_skills": ["Python"], "postings": []},
    }
    ctx = MagicMock()

    with (
        patch(
            "workflow.workers.require_skills_catalog",
            side_effect=CatalogNotFoundError("missing"),
        ),
        patch("workflow.workers.fetch_skills_catalog") as fetch_mock,
        patch("workflow.workers.post_json") as post_mock,
    ):
        with pytest.raises(CatalogNotFoundError):
            asyncio.run(match_ioet_skills_task(lead, "missing-ref", ctx))

    fetch_mock.assert_not_called()
    post_mock.assert_not_called()
