#!/usr/bin/env python3
"""E2E through HubSpot with read-only CRM checks (no writes).

Uses real Apollo/Bamboo/HubSpot when those services are up.
Stubs Bedrock agent steps when Anthropic use-case form blocks scoring.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.common.icp import load_icp

APOLLO = "http://127.0.0.1:8001"
BAMBOO = "http://127.0.0.1:8003"
HUBSPOT = "http://127.0.0.1:8004"
JOBS = "http://127.0.0.1:8006"
AGENT = "http://127.0.0.1:8002"


def _pp(title: str, payload: Any) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2, default=str)[:4000])


def post(base: str, path: str, payload: dict, timeout: int = 120) -> Any:
    r = requests.post(f"{base}{path}", json=payload, timeout=timeout)
    print(f"POST {path} -> {r.status_code}")
    if not r.ok:
        print(r.text[:1000])
        r.raise_for_status()
    return r.json()


def get(base: str, path: str, timeout: int = 120) -> Any:
    r = requests.get(f"{base}{path}", timeout=timeout)
    print(f"GET {path} -> {r.status_code}")
    if not r.ok:
        print(r.text[:1000])
        r.raise_for_status()
    return r.json()


def try_score(icp_version: str, companies: list[dict]) -> list[dict]:
    try:
        return post(AGENT, "/v1/score-companies", {"icp_version": icp_version, "companies": companies})
    except (requests.HTTPError, requests.ConnectionError) as exc:
        print(f"Bedrock score unavailable ({exc}); stubbing ICP scores")
        out = []
        for i, c in enumerate(companies):
            row = dict(c)
            row["icp_score"] = round(0.95 - i * 0.05, 2)
            row["rationale"] = "Stubbed — Bedrock Anthropic use-case form not approved"
            row["signals"] = ["integration-test-stub"]
            out.append(row)
        return out


def try_match_and_draft(lead: dict, catalog: list) -> dict:
    try:
        matched = post(AGENT, "/v1/match-skills", {"lead": lead, "skills_catalog": catalog})
        return post(AGENT, "/v1/draft-outreach-email", {"lead": matched})
    except (requests.HTTPError, requests.ConnectionError) as exc:
        print(f"Bedrock match/draft unavailable ({exc}); stubbing outreach")
        contacts = [dict(row) for row in (lead.get("contacts") or [])]
        contact = contacts[0] if contacts else {}
        name = (contact.get("full_name") or "").split()[0] or "there"
        company = (lead.get("company") or {}).get("name") or "your team"
        if contacts:
            contacts[0]["notes"] = (
                f"Subject: Quick intro — ioet x {company}\n\n"
                f"Hi {name},\n\n"
                "Stubbed outreach email for HubSpot dry-run (Bedrock blocked).\n"
            )
        lead = dict(lead)
        lead["contacts"] = contacts
        lead["skill_matches"] = [
            {"skill": "Python", "person_or_team": "Engineering", "confidence": 0.8}
        ]
        lead["status"] = "matched"
        return lead


def main() -> None:
    icp = load_icp()
    print(f"ICP {icp.version}")

    companies = post(
        APOLLO,
        "/v1/search-companies",
        {"icp_version": icp.version, "segment_ids": ["primary"], "max_results": 2},
    )
    print("companies:", [c.get("name") for c in companies])

    scored = try_score(icp.version, companies)
    top = max(scored, key=lambda c: float(c.get("icp_score") or 0))
    print(f"top: {top.get('name')} score={top.get('icp_score')}")

    contacts = post(APOLLO, "/v1/find-decision-makers", {"company": top, "icp_version": icp.version})
    print("contacts:", [(c.get("full_name"), c.get("title")) for c in contacts])

    lead = {
        "company": top,
        "contacts": contacts,
        "skill_matches": [],
        "hubspot_ids": {},
        "status": "enriched",
        "notes": None,
    }
    lead = post(HUBSPOT, "/v1/sanitize-public-fields", {"lead": lead})
    lead = post(JOBS, "/v1/extract-job-skills", lead)
    print("job note:", (lead.get("job_context") or {}).get("note"))

    catalog = get(BAMBOO, "/v1/catalog")
    print(f"bamboo catalog employees: {len(catalog)}")
    if catalog:
        sample = catalog[0]
        _pp(
            "bamboo sample employee",
            {
                "employee_id": sample.get("employee_id"),
                "display_name": sample.get("display_name"),
                "job_title": sample.get("job_title"),
                "department": sample.get("department"),
                "skills_count": len(sample.get("skills") or []),
            },
        )

    lead = try_match_and_draft(lead, catalog)

    verify = get(HUBSPOT, "/v1/verify")
    _pp("HubSpot read verify", verify)

    published = post(HUBSPOT, "/v1/upsert-lead", {"lead": lead, "dry_run": True})
    _pp("HubSpot dry_run upsert (read + synthetic ids)", published.get("hubspot_ids"))

    assert verify.get("ok") is True
    assert published["hubspot_ids"].get("verify_ok") == "true"
    print("\nSUCCESS: flow through HubSpot read-only (no CRM writes)")


if __name__ == "__main__":
    main()
