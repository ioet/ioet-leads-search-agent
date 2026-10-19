"""Campaign config override helpers."""

from __future__ import annotations

from services.common.campaign_config import (
    CompaniesFilterConfig,
    DecisionMakersConfig,
    apply_company_filter_to_apollo_payload,
    parse_campaign_config,
    persona_titles,
)
from services.common.schemas import Company
from services.hubspot.filter import filter_companies, should_skip_company


def test_parse_campaign_config_defaults() -> None:
    cfg = parse_campaign_config(None)
    assert cfg.run_mode.value == "dry_run"
    assert cfg.email_owner is True
    assert cfg.companies_per_run == 25


def test_review_mode_and_email_owner() -> None:
    cfg = parse_campaign_config({"run_mode": "review", "email_owner": False})
    assert cfg.run_mode.value == "review"
    assert cfg.email_owner is False


def test_apollo_filter_overrides() -> None:
    base = {
        "organization_num_employees_ranges": ["1,10"],
        "organization_locations": ["Canada"],
        "q_organization_keyword_tags": ["fintech"],
    }
    filt = CompaniesFilterConfig(
        employee_ranges=["51–200"],
        hq_locations=["United States"],
        tech_stack=["React", "AWS"],
    )
    out = apply_company_filter_to_apollo_payload(base, filt)
    assert "51,100" in out["organization_num_employees_ranges"]
    assert out["organization_locations"] == ["United States"]
    assert "React" in out["q_organization_keyword_tags"]
    assert "fintech" in out["q_organization_keyword_tags"]


def test_persona_titles() -> None:
    assert persona_titles(DecisionMakersConfig(personas=["CTO", " VP Engineering "])) == [
        "CTO",
        "VP Engineering",
    ]
    assert persona_titles(DecisionMakersConfig(personas=[])) is None


def test_hubspot_skip_rules() -> None:
    filt = CompaniesFilterConfig(
        skip_customers=True,
        skip_open_deals=True,
        skip_has_owner=True,
        skip_contacted_within_days=60,
    )
    skip, reason = should_skip_company(
        {"exists": True, "lifecycle_stage": "customer"},
        filt,
    )
    assert skip and reason == "customer"

    skip, reason = should_skip_company(
        {"exists": True, "has_open_deal": True, "lifecycle_stage": "lead"},
        filt,
    )
    assert skip and reason == "open_deal"

    companies = [
        Company(name="A", domain="a.com"),
        Company(name="B", domain="b.com"),
    ]
    signals = {
        "a.com": {"exists": True, "lifecycle_stage": "customer"},
        "b.com": {"exists": False},
    }
    kept = filter_companies(companies, signals, filt)
    assert [c.domain for c in kept] == ["b.com"]
