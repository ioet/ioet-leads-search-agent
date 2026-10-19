"""Workflow WfSpec construction tests (no LittleHorse server required)."""

import pytest

from services.common.schemas import NotifyRequest
from tests.helpers import assert_model
from workflow.workers import TASK_HANDLERS, TASK_NAMES
from workflow.workflows.enrich_publish import CHILD_WF_NAME, get_workflow as get_child
from workflow.workflows.leads_search import PARENT_WF_NAME, get_workflow as get_parent


def test_task_handlers_cover_all_names() -> None:
    assert set(TASK_HANDLERS) == set(TASK_NAMES)
    assert "search-companies" in TASK_NAMES
    assert "filter-hubspot-companies" in TASK_NAMES
    assert "select-top-leads" in TASK_NAMES
    assert "notify" in TASK_NAMES
    assert "notify-failure" in TASK_NAMES
    assert "fetch-ioet-skills-catalog" in TASK_NAMES
    assert "match-ioet-skills" in TASK_NAMES
    assert "draft-outreach-email" in TASK_NAMES
    assert "record-campaign-run" in TASK_NAMES


def test_parent_workflow_compiles() -> None:
    wf = get_parent()
    assert wf.name == PARENT_WF_NAME
    spec = wf.compile()
    assert PARENT_WF_NAME in str(spec.name) or spec.name.name == PARENT_WF_NAME
    # Entrypoint thread should exist
    assert spec.thread_specs


def test_child_workflow_compiles() -> None:
    wf = get_child()
    assert wf.name == CHILD_WF_NAME
    spec = wf.compile()
    assert spec.thread_specs


def test_select_top_leads_ordering(monkeypatch) -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import select_top_leads_task

    monkeypatch.delenv("MAX_COMPANIES", raising=False)

    companies = [
        {"name": "Low", "icp_score": 0.1},
        {"name": "High", "icp_score": 0.9},
        {"name": "Mid", "icp_score": 0.5},
    ]
    ctx = MagicMock()
    result = asyncio.run(select_top_leads_task(companies, 2, ctx))
    assert isinstance(result, list)
    assert len(result) == 2
    assert [c["name"] for c in result] == ["High", "Mid"]
    assert all(isinstance(c["icp_score"], float) for c in result)


def test_count_companies() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import count_companies_task

    ctx = MagicMock()
    empty = asyncio.run(count_companies_task([], ctx))
    one = asyncio.run(count_companies_task([{"name": "A"}], ctx))
    assert isinstance(empty, int)
    assert isinstance(one, int)
    assert empty == 0
    assert one == 1


def test_build_empty_search_notification() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import build_empty_search_notification_task

    ctx = MagicMock()
    ctx.wf_run_id = "wf-123"
    result = asyncio.run(
        build_empty_search_notification_task(
            "2026-08-26",
            ["primary"],
            "demo-001",
            ctx,
        )
    )
    assert isinstance(result, dict)
    notify = assert_model(
        {"message": result["message"], "details": result["details"]},
        NotifyRequest,
    )
    assert "No companies found" in notify.message
    assert notify.details["kind"] == "empty_search"
    assert notify.details["icp_version"] == "2026-08-26"
    assert notify.details["campaign_id"] == "demo-001"
    assert notify.details["segment_ids"] == ["primary"]
    assert isinstance(notify.details["wf_run_id"], str)


def test_build_campaign_summary_includes_message() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import build_campaign_summary_task

    ctx = MagicMock()
    ctx.wf_run_id = "wf-456"
    result = asyncio.run(
        build_campaign_summary_task("demo-001", [{"name": "Acme"}], True, "", ctx)
    )
    assert isinstance(result, dict)
    notify = assert_model(
        {"message": result["message"], "details": result["details"]},
        NotifyRequest,
    )
    assert "demo-001" in notify.message
    assert "dry-run" in notify.message
    assert "Acme" in notify.message
    assert notify.details["kind"] == "campaign_summary"
    assert notify.details["campaign_id"] == "demo-001"
    assert notify.details["dry_run"] is True
    assert notify.details["leads_processed"] == 1
    assert notify.details["company_names"] == ["Acme"]
    assert isinstance(notify.details["wf_run_id"], str)
    assert notify.details["leads_published"] == 0


def test_build_campaign_summary_counts_child_outcomes() -> None:
    import asyncio
    from unittest.mock import MagicMock

    from workflow.workers import _remember_outcome, build_campaign_summary_task

    ctx = MagicMock()
    ctx.wf_run_id = "wf-789"
    _remember_outcome(
        "run-1",
        {"company_name": "Weekday", "status": "skipped", "contact_count": 0, "note": None},
    )
    _remember_outcome(
        "run-1",
        {"company_name": "Acme", "status": "dry_run", "contact_count": 1, "note": None},
    )
    result = asyncio.run(
        build_campaign_summary_task(
            "demo-001", [{"name": "Weekday"}, {"name": "Acme"}], True, "run-1", ctx
        )
    )
    assert "0 published" in result["message"]
    assert "1 dry-run" in result["message"]
    assert "0 failed" in result["message"]
    assert "1 skipped" in result["message"]
    assert result["details"]["leads_published"] == 0
    assert result["details"]["leads_skipped"] == 1
    assert result["details"]["leads_dry_run"] == 1


def test_lh_id_prefers_protobuf_id() -> None:
    from types import SimpleNamespace

    from workflow.workers import _lh_id

    dump = (
        'id: "20c947ccb1cb47fb888783cc6578938d"\n'
        "parent_wf_run_id {\n"
        '  id: "57a393bbe71149968579ead54dd0afc0"\n'
        "}\n"
    )
    assert _lh_id(dump) == "20c947ccb1cb47fb888783cc6578938d"
    assert _lh_id(SimpleNamespace(id="abc123")) == "abc123"
    assert _lh_id("plain-id") == "plain-id"


def test_wrapped_handler_reports_lh_task_exception() -> None:
    import asyncio
    from unittest.mock import MagicMock, patch

    from littlehorse.exceptions import LHTaskException

    from services.common.catalog_store import CatalogNotFoundError
    from workflow.workers import TASK_HANDLERS

    ctx = MagicMock()
    ctx.wf_run_id = "wf-err-1"
    ctx.task_run_id.task_guid = "guid-abc"
    ctx.log = MagicMock()
    lead = {"company": {"name": "Acme"}}

    with patch(
        "workflow.workers.require_skills_catalog",
        side_effect=CatalogNotFoundError("Skills catalog not found"),
    ):
        with pytest.raises(LHTaskException) as caught:
            asyncio.run(TASK_HANDLERS["match-ioet-skills"](lead, "missing-ref", ctx))

    assert caught.value.exception_name == "STEP_FAILED"
    assert "match-ioet-skills failed" in caught.value.message
    assert "Skills catalog not found" in caught.value.message
    assert "task_guid=guid-abc" in caught.value.message
    ctx.log.assert_called()
