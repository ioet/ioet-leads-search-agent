"""Validate ICP schema, loaders, and helper mapping."""

from pathlib import Path

import pytest

from services.common.icp import (
    IdealCustomerProfile,
    apollo_hard_filters,
    load_icp,
    outbound_segments,
    titles_for_company_size,
)

ROOT = Path(__file__).resolve().parents[1]
ICP_PATH = ROOT / "data" / "icp.json"


@pytest.fixture
def sample_icp() -> IdealCustomerProfile:
    """Stable in-memory ICP for behavior tests — independent of data/icp.json revisions."""
    return IdealCustomerProfile.model_validate(
        {
            "version": "test-1",
            "source": "test-fixture",
            "prepared_by": "test@example.com",
            "campaign": "Test Campaign",
            "segments": [
                {
                    "id": "primary",
                    "priority": 1,
                    "in_outbound": True,
                    "definition": "Primary segment",
                    "industries": ["fintech", "ai_ml"],
                    "employee_count": {"min": 10, "max": 500},
                    "funding_stages": ["seed", "series_a"],
                    "geos": ["US", "CA"],
                    "sourcing": {
                        "yc_batches": ["Fall 2025"],
                        "yc_preferred": True,
                    },
                },
                {
                    "id": "secondary",
                    "priority": 2,
                    "in_outbound": True,
                    "definition": "Secondary segment",
                    "industries": ["ecommerce"],
                    "employee_count": {"min": 10, "max": 500},
                    "geos": ["US"],
                },
                {
                    "id": "excluded_enterprise",
                    "in_outbound": False,
                    "definition": "Out of outbound scope",
                    "examples": ["EY", "HPE"],
                    "reason": "Partnership motion",
                },
            ],
            "buyer_personas": [
                {
                    "tier": 1,
                    "titles": ["Founder", "CEO", "CTO"],
                    "company_size_hint": {"max_employees": 150},
                    "messaging": "exec_roi",
                },
                {
                    "tier": 2,
                    "titles": ["VP Engineering", "Head of Engineering"],
                    "company_size_hint": {"min_employees": 150},
                    "messaging": "exec_roi",
                    "reach_with": [1],
                },
                {
                    "tier": 3,
                    "titles": ["Engineering Manager"],
                    "company_size_hint": {"min_employees": 150},
                    "messaging": "team_capacity",
                    "secondary_contact": True,
                },
            ],
            "prioritization_signals": ["recent_raise"],
            "systems": {
                "company_search": "apollo",
                "contact_enrichment": "apollo",
                "crm": "hubspot",
                "skills": "bamboohr",
                "llm": "bedrock",
            },
            "data_policy": {
                "hubspot_allowlist": ["name", "domain"],
                "hubspot_denylist": ["email", "phone"],
            },
        }
    )


def test_load_icp_validates_canonical_file() -> None:
    """Real data/icp.json must parse; do not pin version or segment content here."""
    icp = load_icp(ICP_PATH)

    assert icp.version.strip()
    assert icp.source.strip()
    assert icp.prepared_by.strip()
    assert icp.campaign.strip()
    assert len(icp.segments) >= 1
    assert len(icp.buyer_personas) >= 1
    assert icp.systems.company_search
    assert icp.systems.contact_enrichment
    assert icp.systems.crm
    assert icp.data_policy.hubspot_allowlist
    assert icp.data_policy.hubspot_denylist

    outbound = outbound_segments(icp)
    assert len(outbound) >= 1
    assert all(s.in_outbound for s in outbound)


def test_outbound_segments_default_and_filter(sample_icp: IdealCustomerProfile) -> None:
    outbound = outbound_segments(sample_icp)
    assert {s.id for s in outbound} == {"primary", "secondary"}

    primary_only = outbound_segments(sample_icp, ["primary"])
    assert len(primary_only) == 1
    assert primary_only[0].id == "primary"

    with pytest.raises(KeyError):
        outbound_segments(sample_icp, ["does-not-exist"])


def test_excluded_enterprise_not_outbound(sample_icp: IdealCustomerProfile) -> None:
    excluded = sample_icp.segment_by_id("excluded_enterprise")
    assert excluded.in_outbound is False
    assert excluded.examples
    with pytest.raises(ValueError):
        apollo_hard_filters(excluded)


def test_apollo_hard_filters_primary(sample_icp: IdealCustomerProfile) -> None:
    filters = apollo_hard_filters(sample_icp.segment_by_id("primary"))
    assert filters["segment_id"] == "primary"
    assert filters["employee_count_min"] == 10
    assert filters["employee_count_max"] == 500
    assert "fintech" in filters["industries"]
    assert filters["geos"] == ["US", "CA"]
    assert filters["yc_preferred"] is True
    assert "Fall 2025" in filters["yc_batches"]


def test_titles_for_company_size(sample_icp: IdealCustomerProfile) -> None:
    small = titles_for_company_size(sample_icp, 80)
    assert "Founder" in small
    assert "VP Engineering" not in small

    large = titles_for_company_size(sample_icp, 200)
    assert "Founder" in large
    assert "VP Engineering" in large
    assert "Engineering Manager" in large

    unknown = titles_for_company_size(sample_icp, None)
    assert unknown == sample_icp.buyer_personas[0].titles


def test_reject_invalid_payload() -> None:
    with pytest.raises(Exception):
        IdealCustomerProfile.model_validate({"version": "x"})
