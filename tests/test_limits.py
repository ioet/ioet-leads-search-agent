"""Env-driven company/contact limits."""

import pytest

from services.common.limits import max_companies, max_contacts_per_company
from services.common.schemas import CompanySearchRequest, WorkflowRunInput


def test_limits_defaults(monkeypatch) -> None:
    monkeypatch.delenv("MAX_COMPANIES", raising=False)
    monkeypatch.delenv("MAX_CONTACTS_PER_COMPANY", raising=False)
    assert max_companies() == 25
    assert max_contacts_per_company() == 10


def test_limits_from_env(monkeypatch) -> None:
    monkeypatch.setenv("MAX_COMPANIES", "3")
    monkeypatch.setenv("MAX_CONTACTS_PER_COMPANY", "2")
    assert max_companies(default=99) == 3
    assert max_contacts_per_company(default=99) == 2
    assert WorkflowRunInput(icp_version="v", campaign_id="c").max_leads == 3
    assert CompanySearchRequest(icp_version="v", segment_ids=["primary"]).max_results == 3


def test_limits_reject_invalid(monkeypatch) -> None:
    monkeypatch.setenv("MAX_COMPANIES", "0")
    with pytest.raises(ValueError):
        max_companies()
