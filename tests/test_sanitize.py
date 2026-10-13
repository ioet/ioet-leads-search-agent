"""Unit tests for public-field sanitization."""

from services.common.icp import DataPolicy
from services.common.sanitize import hubspot_payload_from_lead, sanitize_lead
from services.common.schemas import Company, Contact, LeadResult, SkillMatch
from tests.helpers import assert_json_response


def test_sanitize_keeps_contact_email_and_phone() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com", industry="fintech"),
        contacts=[
            Contact(
                full_name="Ada Lovelace",
                title="CTO",
                linkedin_url="https://linkedin.com/in/ada",
                email="ada@acme.com",
                phone="+1-555-0100",
            )
        ],
        skill_matches=[SkillMatch(skill="Python", person_or_team="Ada Team", confidence=0.9)],
        notes="Good fit",
    )
    clean = sanitize_lead(lead)
    validated = assert_json_response(clean.model_dump(), LeadResult)
    assert validated.company.domain == "acme.com"
    assert validated.contacts[0].full_name == "Ada Lovelace"
    assert validated.contacts[0].email == "ada@acme.com"
    assert validated.contacts[0].phone == "+1-555-0100"
    assert "salary" not in validated.contacts[0].model_dump()


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
            notes="Job postings:\n- Engineer: https://acme.com/jobs/1",
        ),
        contacts=[
            Contact(
                full_name="Ada",
                title="CTO",
                linkedin_url="https://linkedin.com/in/ada",
                email="ada@acme.com",
                phone="+1-555-0100",
                notes=outreach_email,
            )
        ],
        skill_matches=[SkillMatch(skill="React", person_or_team="Frontend", confidence=0.8)],
    )
    policy = DataPolicy(
        hubspot_allowlist=["name", "domain", "title", "skill_match_note"],
        hubspot_denylist=["email", "phone", "linkedin_url"],
    )
    payload = hubspot_payload_from_lead(lead, policy)
    assert isinstance(payload, dict)
    assert payload["company"] == {"name": "Acme", "domain": "acme.com"}
    assert "linkedin_url" not in payload["company"]
    assert payload["contacts"][0]["name"] == "Ada"
    assert payload["contacts"][0]["title"] == "CTO"
    assert "email" not in payload["contacts"][0]
    assert "phone" not in payload["contacts"][0]
    assert payload["contacts"][0]["note"] == outreach_email
    assert payload["company_note"] == "Job postings:\n- Engineer: https://acme.com/jobs/1"
    assert "skill matches" not in payload["contacts"][0]["note"].lower()


def test_hubspot_payload_includes_email_and_phone_when_allowed() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        contacts=[
            Contact(
                full_name="Ada",
                email="ada@acme.com",
                phone="+1-555-0100",
                notes="Hi Ada,",
            )
        ],
    )
    policy = DataPolicy(
        hubspot_allowlist=["name", "email", "phone", "skill_match_note"],
        hubspot_denylist=["ssn", "salary"],
    )
    payload = hubspot_payload_from_lead(lead, policy)
    assert payload["contacts"][0]["email"] == "ada@acme.com"
    assert payload["contacts"][0]["phone"] == "+1-555-0100"
    assert payload["contacts"][0]["note"] == "Hi Ada,"
