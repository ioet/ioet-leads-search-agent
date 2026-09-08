"""Prompt templates for agent-service Bedrock calls."""

from __future__ import annotations

import json
from typing import Any

from services.common.icp import IdealCustomerProfile
from services.common.schemas import Company, LeadResult


def score_companies_system(icp: IdealCustomerProfile) -> str:
    return (
        "You are a B2B sales development analyst for ioet, a nearshore engineering partner. "
        "Score companies against the Ideal Customer Profile using hard segment fit and soft signals. "
        "Return ONLY valid JSON — no markdown, no commentary outside the JSON object."
    )


def score_companies_user(icp: IdealCustomerProfile, companies: list[Company]) -> str:
    icp_context = {
        "campaign": icp.campaign,
        "segments": [
            {
                "id": s.id,
                "priority": s.priority,
                "in_outbound": s.in_outbound,
                "definition": s.definition,
                "industries": s.industries,
                "examples": s.examples,
                "reason": s.reason,
            }
            for s in icp.segments
        ],
        "prioritization_signals": icp.prioritization_signals,
        "buyer_personas": [
            {"tier": p.tier, "titles": p.titles, "messaging": p.messaging.value}
            for p in icp.buyer_personas
        ],
    }
    payload = {
        "icp": icp_context,
        "companies": [c.model_dump(exclude_none=True) for c in companies],
        "instructions": (
            "For each company assign icp_score 0.0-1.0, a one-sentence rationale, "
            "and signals[] from prioritization_signals when plausible. "
            "Penalize excluded_enterprise patterns. Prefer primary segment fit."
        ),
        "output_schema": {
            "companies": [
                {
                    "name": "string",
                    "domain": "string|null",
                    "icp_score": "float 0-1",
                    "rationale": "string",
                    "signals": ["string"],
                    "segment_id": "string|null",
                }
            ]
        },
    }
    return json.dumps(payload, indent=2)


def match_skills_system() -> str:
    return (
        "You match outbound leads to ioet employee skills for staffing conversations. "
        "Use ONLY employees and skills from the provided catalog. "
        "Do not invent people or skills. Return ONLY valid JSON."
    )


def match_skills_user(lead: LeadResult, catalog: list[dict[str, Any]]) -> str:
    slim_catalog = [
        {
            "employee_id": row.get("employee_id"),
            "display_name": row.get("display_name"),
            "job_title": row.get("job_title"),
            "department": row.get("department"),
            "skills": row.get("skills") or [],
        }
        for row in catalog
    ]
    required_skills: list[str] = []
    job_note: str | None = None
    if lead.job_context:
        required_skills = list(lead.job_context.required_skills)
        job_note = lead.job_context.note

    if required_skills:
        instructions = (
            "Match ioet employees to each skill in required_skills using the skills catalog. "
            "Use ONLY skills listed in required_skills — do not infer additional needs. "
            "Each skill_match.skill must be one of required_skills. "
            "Prefer strong overlap; omit weak matches."
        )
    else:
        instructions = (
            "required_skills is empty (no job postings or none extracted). "
            "Return an empty skill_matches array — do not infer skills from industry alone."
        )

    payload = {
        "lead": lead.model_dump(exclude_none=True),
        "required_skills": required_skills,
        "job_posting_note": job_note,
        "skills_catalog": slim_catalog,
        "instructions": instructions,
        "output_schema": {
            "skill_matches": [
                {
                    "skill": "string (must be in required_skills when that list is non-empty)",
                    "person_or_team": "employee display_name",
                    "confidence": "float 0-1",
                }
            ]
        },
    }
    return json.dumps(payload, indent=2)


def draft_outreach_email_system() -> str:
    return (
        "You draft customer-centric outbound emails for ioet, a nearshore engineering partner. "
        "Write to the primary contact about their hiring needs and how ioet can staff those openings. "
        "Focus on the customer's goals — not internal staffing logistics. "
        "No email addresses, phone numbers, or other sensitive PII. "
        "Professional, warm B2B tone. Return ONLY valid JSON."
    )


def draft_outreach_email_user(lead: LeadResult) -> str:
    primary_contact = lead.contacts[0].model_dump(exclude_none=True) if lead.contacts else None
    job_postings = []
    required_skills: list[str] = []
    job_note: str | None = None
    if lead.job_context:
        job_postings = [p.model_dump(exclude_none=True) for p in lead.job_context.postings]
        required_skills = list(lead.job_context.required_skills)
        job_note = lead.job_context.note

    payload = {
        "lead": lead.model_dump(exclude_none=True),
        "primary_contact": primary_contact,
        "job_postings": job_postings,
        "required_skills": required_skills,
        "job_posting_note": job_note,
        "ioet_skill_matches": [
            {
                "skill": m.skill,
                "person_or_team": m.person_or_team,
                "confidence": m.confidence,
            }
            for m in lead.skill_matches
        ],
        "instructions": (
            "Draft a short outreach email to the primary contact. "
            "Open with their context (role, company, hiring needs from job postings when available). "
            "Explain how ioet can help cover their open roles with nearshore engineers who match "
            "the required skills — mention specific ioet people/teams from ioet_skill_matches when present. "
            "If no job postings were found, acknowledge that and offer ioet as a flexible engineering "
            "partner aligned to their stack. "
            "Keep it customer-centric: their needs first, then how we help. "
            "Do not list internal match scores or write an AE summary."
        ),
        "output_schema": {
            "subject": "string — concise email subject",
            "body": "string — email body, 3-6 short paragraphs, ready to send",
        },
    }
    return json.dumps(payload, indent=2)


def draft_crm_note_system() -> str:
    return draft_outreach_email_system()


def draft_crm_note_user(lead: LeadResult) -> str:
    return draft_outreach_email_user(lead)
