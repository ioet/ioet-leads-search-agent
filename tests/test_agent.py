"""Agent-service tests (Bedrock + skills catalog mocked)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from services.agent.bedrock import (
    DEFAULT_MODEL_HIGH,
    DEFAULT_MODEL_LOW,
    BedrockClient,
    parse_json_from_text,
    resolve_model_id,
)
from services.agent.logic import draft_crm_note, draft_outreach_email, match_ioet_skills, score_companies
from services.common.icp import load_icp
from services.common.schemas import (
    Company,
    Contact,
    JobPosting,
    JobPostingContext,
    LeadResult,
    LeadStatus,
    SkillMatch,
)
from tests.helpers import assert_http_call_json, assert_json_response_list


def test_parse_json_from_fenced_block() -> None:
    raw = 'Here you go:\n```json\n{"note": "hello"}\n```'
    parsed = parse_json_from_text(raw)
    assert isinstance(parsed, dict)
    assert parsed == {"note": "hello"}
    assert isinstance(parsed["note"], str)


def test_parse_json_from_unclosed_fence() -> None:
    parsed = parse_json_from_text('```json\n{"note": "hello"}')
    assert parsed == {"note": "hello"}


def test_parse_json_from_truncated_output() -> None:
    raw = (
        "```json\n"
        '{"skill_matches": [{"skill": "Python", "person_or_team": "Ada", "co'
    )
    parsed = parse_json_from_text(raw)
    assert isinstance(parsed, dict)
    assert parsed["skill_matches"][0]["skill"] == "Python"
    assert parsed["skill_matches"][0]["person_or_team"] == "Ada"


def test_bedrock_converse_http() -> None:
    from services.agent.bedrock import converse_url

    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "output": {"message": {"content": [{"text": '{"note": "ok"}'}]}}
    }
    session.post.return_value = response

    client = BedrockClient(
        api_key="test-key",
        model_id="google.gemma-3-4b-it",
        region="us-east-1",
        session=session,
    )
    result = client.converse_json("system prompt", "user prompt")
    assert isinstance(result, dict)
    assert result == {"note": "ok"}

    args, kwargs = session.post.call_args
    assert args[0] == converse_url("google.gemma-3-4b-it", "us-east-1")
    assert kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    payload = kwargs["json"]
    assert payload["system"] == [{"text": "system prompt"}]
    assert payload["messages"] == [{"role": "user", "content": [{"text": "user prompt"}]}]
    assert payload["inferenceConfig"]["maxTokens"] == 4096
    assert payload["inferenceConfig"]["temperature"] == 0.2


def test_bedrock_requires_api_key() -> None:
    from services.agent.bedrock import BedrockClient, BedrockConfigError

    client = BedrockClient(api_key="", model_id="google.gemma-3-4b-it")
    with pytest.raises(BedrockConfigError, match="AWS_BEDROCK_API_KEY"):
        client.converse_text(system="s", user="u")


def test_resolve_model_id_defaults(monkeypatch) -> None:
    for key in (
        "AWS_BEDROCK_MODEL_ID_HIGH",
        "AWS_BEDROCK_MODEL_ID_LOW",
        "AWS_BEDROCK_MODEL_ID",
        "BEDROCK_MODEL_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    assert resolve_model_id(complexity="high") == DEFAULT_MODEL_HIGH
    assert resolve_model_id(complexity="low") == DEFAULT_MODEL_LOW
    assert resolve_model_id("  custom.model  ", complexity="low") == "custom.model"


def test_bedrock_client_uses_complexity_env(monkeypatch) -> None:
    monkeypatch.setenv("AWS_BEDROCK_MODEL_ID_HIGH", "env-high-model")
    monkeypatch.setenv("AWS_BEDROCK_MODEL_ID_LOW", "env-low-model")
    monkeypatch.delenv("AWS_BEDROCK_MODEL_ID", raising=False)
    high = BedrockClient(api_key="k", complexity="high")
    low = BedrockClient(api_key="k", complexity="low")
    assert high.model_id == "env-high-model"
    assert low.model_id == "env-low-model"
    override = BedrockClient(api_key="k", model_id="request-model", complexity="high")
    assert override.model_id == "request-model"


def test_score_companies_uses_high_complexity_client() -> None:
    icp = load_icp()
    companies = [Company(name="Acme", domain="acme.ai")]
    with patch("services.agent.logic.BedrockClient") as client_cls:
        client_cls.return_value.converse_json.return_value = {"companies": []}
        score_companies(icp, companies, model_id="custom-high")
        client_cls.assert_called_once_with(model_id="custom-high", complexity="high")


def test_match_ioet_skills_uses_low_complexity_client() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        job_context=JobPostingContext(required_skills=["Python"]),
    )
    catalog = [{"employee_id": "1", "display_name": "Ada", "skills": ["Python"]}]
    with patch("services.agent.logic.BedrockClient") as client_cls:
        client_cls.return_value.converse_json.return_value = {"skill_matches": []}
        match_ioet_skills(lead, catalog=catalog, model_id="custom-low")
        client_cls.assert_called_once_with(model_id="custom-low", complexity="low")


def test_score_companies_merges_bedrock_output() -> None:
    icp = load_icp()
    companies = [
        Company(name="Acme AI", domain="acme.ai", industry="fintech"),
        Company(name="Other Co", domain="other.co"),
    ]
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {
        "companies": [
            {
                "name": "Acme AI",
                "domain": "acme.ai",
                "icp_score": 0.92,
                "rationale": "Strong fintech fit",
                "signals": ["recent_raise"],
                "segment_id": "primary",
            }
        ]
    }
    result = score_companies(icp, companies, bedrock=bedrock)
    assert len(result) == 2
    scored = assert_json_response_list([c.model_dump() for c in result], Company)
    assert scored[0].name == "Acme AI"
    assert scored[0].domain == "acme.ai"
    assert scored[0].icp_score == 0.92
    assert isinstance(scored[0].icp_score, float)
    assert scored[0].rationale == "Strong fintech fit"
    assert scored[0].signals == ["recent_raise"]
    assert all(isinstance(s, str) for s in scored[0].signals)
    assert scored[0].segment_id == "primary"
    assert scored[1].icp_score is None

    system_arg, user_arg = bedrock.converse_json.call_args[0]
    assert isinstance(system_arg, str) and system_arg
    assert isinstance(user_arg, str) and "Acme AI" in user_arg


def test_match_ioet_skills_uses_catalog() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com", industry="fintech"),
        contacts=[Contact(full_name="Ada", title="CTO")],
        status=LeadStatus.ENRICHED,
        job_context=JobPostingContext(
            required_skills=["Python"],
            note="Found 1 job posting(s) via linkedin; extracted 1 required skill(s).",
            postings=[
                JobPosting(
                    title="Engineer",
                    source="company_website",
                    description="<script>window.reBambooDomains</script> Lato Vollkorn",
                )
            ],
        ),
    )
    catalog = [
        {
            "employee_id": "1",
            "display_name": "Grace Hopper",
            "job_title": "Engineer",
            "department": "Delivery",
            "skills": ["Python", "AWS"],
        }
    ]
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {
        "skill_matches": [
            {"skill": "Python", "person_or_team": "Grace Hopper", "confidence": 0.88}
        ]
    }
    result = match_ioet_skills(lead, catalog=catalog, bedrock=bedrock)
    assert result.status == LeadStatus.MATCHED
    assert len(result.skill_matches) == 1
    match = assert_json_response_list([m.model_dump() for m in result.skill_matches], SkillMatch)[0]
    assert match.skill == "Python"
    assert match.person_or_team == "Grace Hopper"
    assert match.confidence == 0.88
    assert isinstance(match.confidence, float)
    assert bedrock.converse_json.call_args.kwargs["allow_repair"] is False

    user_arg = bedrock.converse_json.call_args[0][1]
    assert "Grace Hopper" in user_arg
    assert "Python" in user_arg
    assert "reBambooDomains" not in user_arg
    assert "Vollkorn" not in user_arg


def test_match_ioet_skills_skips_when_no_required_skills() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        job_context=JobPostingContext(
            required_skills=[],
            note="No job postings found (searched: linkedin, company_website).",
        ),
    )
    bedrock = MagicMock()
    result = match_ioet_skills(lead, catalog=[{"employee_id": "1", "display_name": "A", "skills": ["Python"]}], bedrock=bedrock)
    assert result.skill_matches == []
    assert result.status == LeadStatus.MATCHED
    bedrock.converse_json.assert_not_called()


def test_match_ioet_skills_skips_empty_skill_values() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        job_context=JobPostingContext(required_skills=["Python"]),
    )
    bedrock = MagicMock()
    result = match_ioet_skills(
        lead,
        catalog=[{"employee_id": "1", "display_name": "A", "skills": []}],
        bedrock=bedrock,
    )
    assert result.skill_matches == []
    assert result.status == LeadStatus.MATCHED
    bedrock.converse_json.assert_not_called()


def test_draft_outreach_email() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        contacts=[Contact(full_name="Ada Lovelace", title="CTO")],
        skill_matches=[SkillMatch(skill="Python", person_or_team="Platform", confidence=0.9)],
        job_context=JobPostingContext(
            required_skills=["Python"],
            note="Found 1 job posting(s) via linkedin; extracted 1 required skill(s).",
        ),
    )
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {
        "subject": "Staffing Python engineers for Acme",
        "body": "Hi Ada,\n\nWe can help cover your Python openings with nearshore talent.",
    }
    email = draft_outreach_email(lead, bedrock=bedrock)
    assert isinstance(email, str)
    assert email.startswith("Subject: Staffing Python engineers for Acme")
    assert "Hi Ada" in email
    assert "Python" in email

    user_arg = bedrock.converse_json.call_args[0][1]
    assert "Ada Lovelace" in user_arg
    assert "greeting_name" in user_arg
    assert "ioet_skill_matches" in user_arg


def test_draft_outreach_email_replaces_generic_greeting() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        contacts=[Contact(full_name="Ada Lovelace", title="CTO")],
    )
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {"body": "Hello there, we can help your team."}
    email = draft_outreach_email(lead, bedrock=bedrock)
    assert email.startswith("Hi Ada,")
    assert "there" not in email.lower()


def test_draft_crm_note_alias() -> None:
    lead = LeadResult(
        company=Company(name="Acme", domain="acme.com"),
        skill_matches=[],
    )
    bedrock = MagicMock()
    bedrock.converse_json.return_value = {"body": "Hi there — ioet can support your team."}
    note = draft_crm_note(lead, bedrock=bedrock)
    assert isinstance(note, str)
    assert note == "Hi there — ioet can support your team."


def test_agent_endpoints_with_mocks() -> None:
    icp = load_icp()
    with patch("services.agent.handler.score_companies") as score_mock:
        score_mock.return_value = [Company(name="Acme", domain="acme.com", icp_score=0.8)]
        from services.agent.app import app

        client = TestClient(app)
        request_body = {
            "icp_version": icp.version,
            "companies": [{"name": "Acme", "domain": "acme.com"}],
        }
        response = client.post("/v1/score-companies", json=request_body)
        assert response.status_code == 200
        companies = assert_json_response_list(response.json(), Company)
        assert companies[0].name == "Acme"
        assert companies[0].domain == "acme.com"
        assert companies[0].icp_score == 0.8

        score_mock.assert_called_once()
        call_icp, call_companies = score_mock.call_args[0]
        assert call_icp.version == icp.version
        assert len(call_companies) == 1
        assert call_companies[0].name == request_body["companies"][0]["name"]
        assert call_companies[0].domain == request_body["companies"][0]["domain"]
        assert score_mock.call_args.kwargs.get("model_id") is None


def test_agent_endpoints_forward_model_id() -> None:
    icp = load_icp()
    lead_body = {
        "company": {"name": "Acme", "domain": "acme.com"},
        "contacts": [{"full_name": "Ada Lovelace", "title": "CTO"}],
        "skill_matches": [],
        "hubspot_ids": {},
        "status": "enriched",
        "notes": None,
    }
    from services.agent.app import app

    client = TestClient(app)

    with patch("services.agent.handler.score_companies") as score_mock:
        score_mock.return_value = [Company(name="Acme", domain="acme.com", icp_score=0.8)]
        response = client.post(
            "/v1/score-companies",
            json={
                "icp_version": icp.version,
                "companies": [{"name": "Acme", "domain": "acme.com"}],
                "model_id": "us.anthropic.claude-sonnet-4-6",
            },
        )
        assert response.status_code == 200
        assert score_mock.call_args.kwargs["model_id"] == "us.anthropic.claude-sonnet-4-6"

    with patch("services.agent.handler.match_ioet_skills") as match_mock:
        match_mock.return_value = LeadResult(
            company=Company(name="Acme", domain="acme.com"),
            status=LeadStatus.MATCHED,
        )
        response = client.post(
            "/v1/match-skills",
            json={
                "lead": lead_body,
                "model_id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            },
        )
        assert response.status_code == 200
        assert (
            match_mock.call_args.kwargs["model_id"]
            == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )

    with patch("services.agent.handler.draft_outreach_email") as draft_mock:
        draft_mock.return_value = "Subject: Hello\n\nBody"
        response = client.post(
            "/v1/draft-outreach-email",
            json={"lead": lead_body, "model_id": "us.anthropic.claude-sonnet-4-6"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["notes"] is None
        assert body["contacts"][0]["notes"] == "Subject: Hello\n\nBody"
        assert draft_mock.call_args.kwargs["model_id"] == "us.anthropic.claude-sonnet-4-6"

        # Bare lead payload (legacy / some worker shapes)
        response = client.post("/v1/draft-outreach-email", json=lead_body)
        assert response.status_code == 200
        assert response.json()["contacts"][0]["notes"] == "Subject: Hello\n\nBody"


def test_score_endpoint_rejects_unknown_icp_version() -> None:
    from services.agent.app import app

    client = TestClient(app)
    response = client.post(
        "/v1/score-companies",
        json={"icp_version": "does-not-exist", "companies": []},
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
