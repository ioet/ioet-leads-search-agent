"""Public-field allowlist enforcement for CRM / outbound payloads."""

from __future__ import annotations

from typing import Any

from services.common.icp import DataPolicy, IdealCustomerProfile, load_icp
from services.common.schemas import Company, Contact, LeadResult, SkillMatch

# Fields we never persist to HubSpot even if somehow present on models.
_SENSITIVE_KEYS = frozenset(
    {
        "email",
        "emails",
        "phone",
        "phones",
        "mobile",
        "mobile_phone",
        "personal_email",
        "work_email",
        "ssn",
        "salary",
        "compensation",
    }
)

_COMPANY_PUBLIC = frozenset(
    {"name", "domain", "industry", "linkedin_url", "employee_count", "segment_id"}
)
_CONTACT_PUBLIC = frozenset({"full_name", "title", "linkedin_url", "persona_tier"})


def _strip_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k.lower() not in _SENSITIVE_KEYS}


def sanitize_company(company: Company) -> Company:
    data = _strip_sensitive(company.model_dump())
    keep = {k: v for k, v in data.items() if k in _COMPANY_PUBLIC or k in {"icp_score", "rationale", "signals"}}
    # Scoring fields stay internal; HubSpot allowlist is applied at publish time.
    return Company.model_validate(keep)


def sanitize_contact(contact: Contact) -> Contact:
    data = _strip_sensitive(contact.model_dump())
    keep = {k: v for k, v in data.items() if k in _CONTACT_PUBLIC}
    return Contact.model_validate(keep)


def hubspot_payload_from_lead(
    lead: LeadResult,
    policy: DataPolicy | None = None,
) -> dict[str, Any]:
    """Build a HubSpot-facing dict using ICP data_policy allowlist/denylist."""
    if policy is None:
        policy = load_icp().data_policy

    allow = {f.lower() for f in policy.hubspot_allowlist}
    deny = {f.lower() for f in policy.hubspot_denylist} | _SENSITIVE_KEYS

    company = sanitize_company(lead.company)
    contacts = [sanitize_contact(c) for c in lead.contacts]

    company_props: dict[str, Any] = {}
    mapping = {
        "name": company.name,
        "domain": company.domain,
        "industry": company.industry,
        "linkedin_url": company.linkedin_url,
    }
    for key, value in mapping.items():
        if key in allow and key not in deny and value is not None:
            company_props[key] = value

    contact_props: list[dict[str, Any]] = []
    for contact in contacts:
        props: dict[str, Any] = {}
        cmap = {
            "name": contact.full_name,
            "title": contact.title,
            "linkedin_url": contact.linkedin_url,
        }
        for key, value in cmap.items():
            if key in allow and key not in deny and value is not None:
                props[key] = value
        if props:
            contact_props.append(props)

    note: str | None = None
    if "skill_match_note" in allow and "skill_match_note" not in deny:
        note = format_lead_note(lead)

    return {
        "company": company_props,
        "contacts": contact_props,
        "note": note,
    }


def sanitize_lead(lead: LeadResult, icp: IdealCustomerProfile | None = None) -> LeadResult:
    """Return a lead with sensitive fields stripped from company/contacts."""
    _ = icp  # reserved for policy-driven field pruning later
    return LeadResult(
        company=sanitize_company(lead.company),
        contacts=[sanitize_contact(c) for c in lead.contacts],
        skill_matches=list(lead.skill_matches),
        job_context=lead.job_context,
        hubspot_ids=dict(lead.hubspot_ids),
        status=lead.status,
        notes=lead.notes,
    )


def _format_skill_note(matches: list[SkillMatch], extra: str | None) -> str | None:
    parts: list[str] = []
    if matches:
        lines = [
            f"- {m.skill} → {m.person_or_team} (confidence {m.confidence:.2f})"
            for m in matches
        ]
        parts.append("ioet skill matches:\n" + "\n".join(lines))
    if extra:
        parts.append(extra.strip())
    return "\n\n".join(parts) if parts else None


def format_lead_note(lead: LeadResult) -> str | None:
    """HubSpot note body — the drafted outreach email when present."""
    if lead.notes and lead.notes.strip():
        return lead.notes.strip()
    return None
