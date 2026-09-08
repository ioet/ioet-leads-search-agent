"""Unit tests for public-field sanitization."""

from services.common.icp import DataPolicy
from services.common.sanitize import hubspot_payload_from_lead, sanitize_lead
from services.common.schemas import Company, Contact, LeadResult, SkillMatch
from tests.helpers import assert_json_response


def test_sanitize_strips_sensitive_extras() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com", industry="fintech"),
        contacts=[
            Contact(full_name="Ada Lovelace", title="CTO", linkedin_url="https://linkedin.com/in/ada")
        ],
        skill_matches=[SkillMatch(skill="Python", person_or_team="Ada Team", confidence=0.9)],
        notes="Good fit",
    )
    # Simulate polluted dict round-trip with email/phone.
    dirty = lead.model_dump()
    dirty["contacts"][0]["email"] = "ada@acme.com"  # type: ignore[index]
    dirty["contacts"][0]["phone"] = "+1-555-0100"  # type: ignore[index]

    clean = sanitize_lead(lead)
    validated = assert_json_response(clean.model_dump(), LeadResult)
    assert validated.company.domain == "acme.com"
    assert validated.contacts[0].full_name == "Ada Lovelace"
    dumped = validated.contacts[0].model_dump()
    assert "email" not in dumped
    assert "phone" not in dumped


def test_hubspot_payload_respects_allowlist() -> None:
    outreach_email = (
        "Subject: Supporting your engineering hiring at Acme\n\n"
        "Hi Ada,\n\n"
        "I noticed Acme is hiring for React talent. ioet can help staff those roles "
        "with nearshore engineers from our Frontend team."
    )
    lead = LeadResult(
        company=Company(
            name="Acme",
            domain="acme.com",
            industry="fintech",
            linkedin_url="https://linkedin.com/company/acme",
        ),
        contacts=[Contact(full_name="Ada", title="CTO", linkedin_url="https://linkedin.com/in/ada")],
        skill_matches=[SkillMatch(skill="React", person_or_team="Frontend", confidence=0.8)],
        notes=outreach_email,
    )
    policy = DataPolicy(
        hubspot_allowlist=["name", "domain", "title", "skill_match_note"],
        hubspot_denylist=["email", "phone", "linkedin_url"],
    )
    payload = hubspot_payload_from_lead(lead, policy)
    assert isinstance(payload, dict)
    assert payload["company"] == {"name": "Acme", "domain": "acme.com"}
    assert "linkedin_url" not in payload["company"]
    assert payload["contacts"][0] == {"name": "Ada", "title": "CTO"}
    assert isinstance(payload["note"], str)
    assert payload["note"] == outreach_email
    assert "skill matches" not in payload["note"].lower()
