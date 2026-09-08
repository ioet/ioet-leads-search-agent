"""HubSpot upsert + sanitize endpoint tests."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.common.linkedin import linkedin_url_search_variants, normalize_linkedin_url
from services.common.schemas import Company, Contact, LeadResult, LeadStatus, SkillMatch
from services.hubspot.client import HubSpotClient
from tests.helpers import assert_json_response


def _sample_lead() -> LeadResult:
    return LeadResult(
        company=Company(
            name="Acme",
            domain="acme.com",
            industry="fintech",
            linkedin_url="https://linkedin.com/company/acme",
        ),
        contacts=[Contact(full_name="Ada Lovelace", title="CTO", linkedin_url="https://linkedin.com/in/ada")],
        skill_matches=[SkillMatch(skill="Python", person_or_team="Platform", confidence=0.91)],
        notes="Strong ICP fit",
    )


def test_normalize_linkedin_url() -> None:
    assert normalize_linkedin_url("https://www.LinkedIn.com/in/Ada/?trk=x") == (
        "https://www.linkedin.com/in/ada"
    )
    assert normalize_linkedin_url("linkedin.com/in/ada/") == "https://www.linkedin.com/in/ada"
    assert normalize_linkedin_url("https://linkedin.com/company/Acme") == (
        "https://www.linkedin.com/company/acme"
    )
    assert normalize_linkedin_url("https://example.com/in/ada") is None
    assert normalize_linkedin_url("") is None
    variants = linkedin_url_search_variants("http://linkedin.com/in/Ada/")
    assert "https://www.linkedin.com/in/ada" in variants
    assert "https://linkedin.com/in/ada" in variants


def test_dry_run_upsert_reads_only() -> None:
    session = MagicMock()

    def _request(method, url, json=None, headers=None, timeout=None):
        assert method == "GET"
        assert "companies?limit=1" in url
        resp = MagicMock()
        resp.ok = True
        resp.content = b'{"results":[{"id":"1"}]}'
        resp.json.return_value = {"results": [{"id": "1"}]}
        return resp

    session.request.side_effect = _request
    client = HubSpotClient(service_key="token", session=session)
    result = client.upsert_lead(_sample_lead(), dry_run=True)
    validated = assert_json_response(result.model_dump(), LeadResult)
    assert validated.status == LeadStatus.PUBLISHED
    assert validated.hubspot_ids["company"].startswith("dry-run-company-")
    assert validated.hubspot_ids["verify_ok"] == "true"
    assert validated.hubspot_ids["companies_visible"] == "1"
    assert session.request.call_count == 1
    assert all(call.args[0] == "GET" for call in session.request.call_args_list)


def test_upsert_lead_http_flow(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "token")
    session = MagicMock()
    captured: list[tuple[str, str, dict | None]] = []

    def _request(method, url, json=None, headers=None, timeout=None):
        captured.append((method, url, json))
        resp = MagicMock()
        resp.ok = True
        resp.content = b"{}"
        if method == "POST" and url.endswith("/companies/search"):
            resp.json.return_value = {"results": []}
        elif method == "POST" and url.endswith("/companies"):
            resp.json.return_value = {"id": "co-1"}
        elif method == "POST" and url.endswith("/contacts/search"):
            resp.json.return_value = {"results": []}
        elif method == "POST" and url.endswith("/contacts"):
            resp.json.return_value = {"id": "ct-1"}
        elif method == "POST" and url.endswith("/notes"):
            resp.json.return_value = {"id": "note-1"}
        elif method == "PUT":
            resp.json.return_value = {}
        else:
            resp.json.return_value = {}
        return resp

    session.request.side_effect = _request
    client = HubSpotClient(service_key="token", session=session)
    result = client.upsert_lead(_sample_lead(), dry_run=False)
    validated = assert_json_response(result.model_dump(), LeadResult)
    assert validated.hubspot_ids["company"] == "co-1"
    assert validated.hubspot_ids["contact_0"] == "ct-1"
    assert validated.hubspot_ids["note"] == "note-1"
    assert validated.status == LeadStatus.PUBLISHED

    company_create = next(
        (payload for method, url, payload in captured if method == "POST" and url.endswith("/companies")),
        None,
    )
    assert company_create is not None
    assert company_create["properties"]["name"] == "Acme"
    assert company_create["properties"]["domain"] == "acme.com"
    assert company_create["properties"]["industry"] == "fintech"
    assert (
        company_create["properties"]["linkedin_company_page"]
        == "https://www.linkedin.com/company/acme"
    )

    contact_create = next(
        (payload for method, url, payload in captured if method == "POST" and url.endswith("/contacts")),
        None,
    )
    assert contact_create is not None
    assert contact_create["properties"]["firstname"] == "Ada"
    assert contact_create["properties"]["lastname"] == "Lovelace"
    assert contact_create["properties"]["jobtitle"] == "CTO"
    assert contact_create["properties"]["hs_linkedin_url"] == "https://www.linkedin.com/in/ada"

    contact_searches = [
        payload
        for method, url, payload in captured
        if method == "POST" and url.endswith("/contacts/search")
    ]
    assert len(contact_searches) >= 2
    assert any(
        any(f.get("propertyName") == "hs_linkedin_url" for f in (g.get("filters") or []))
        for payload in contact_searches
        for g in (payload or {}).get("filterGroups") or []
    )
    assert any(
        any(f.get("propertyName") == "associations.company" for f in (g.get("filters") or []))
        for payload in contact_searches
        for g in (payload or {}).get("filterGroups") or []
    )


def test_upsert_contact_matches_linkedin_variant(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "token")
    session = MagicMock()

    def _request(method, url, json=None, headers=None, timeout=None):
        resp = MagicMock()
        resp.ok = True
        resp.content = b"{}"
        if method == "POST" and url.endswith("/companies/search"):
            resp.json.return_value = {"results": [{"id": "co-1"}]}
        elif method == "PATCH" and "/companies/" in url:
            resp.json.return_value = {}
        elif method == "POST" and url.endswith("/contacts/search"):
            filters_groups = (json or {}).get("filterGroups") or []
            linkedin_values = {
                f.get("value")
                for g in filters_groups
                for f in (g.get("filters") or [])
                if f.get("propertyName") == "hs_linkedin_url"
            }
            if "https://linkedin.com/in/ada" in linkedin_values:
                resp.json.return_value = {"results": [{"id": "ct-existing"}]}
            else:
                resp.json.return_value = {"results": []}
        elif method == "PATCH" and "/contacts/" in url:
            resp.json.return_value = {}
        elif method == "PUT":
            resp.json.return_value = {}
        elif method == "POST" and url.endswith("/notes"):
            resp.json.return_value = {"id": "note-1"}
        else:
            resp.json.return_value = {}
        return resp

    session.request.side_effect = _request
    lead = _sample_lead()
    # Messy Apollo-style URL should still match after normalize + variants.
    lead.contacts[0].linkedin_url = "HTTP://LinkedIn.com/in/Ada/?trk=public"
    result = HubSpotClient(service_key="token", session=session).upsert_lead(lead, dry_run=False)
    assert result.hubspot_ids["contact_0"] == "ct-existing"
    assert not any(
        call.args[0] == "POST" and call.args[1].endswith("/contacts")
        for call in session.request.call_args_list
    )


def test_upsert_contact_matches_name_and_company(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "token")
    session = MagicMock()

    def _request(method, url, json=None, headers=None, timeout=None):
        resp = MagicMock()
        resp.ok = True
        resp.content = b"{}"
        if method == "POST" and url.endswith("/companies/search"):
            resp.json.return_value = {"results": [{"id": "co-9"}]}
        elif method == "PATCH" and "/companies/" in url:
            resp.json.return_value = {}
        elif method == "POST" and url.endswith("/contacts/search"):
            filters = ((json or {}).get("filterGroups") or [{}])[0].get("filters") or []
            props = {f.get("propertyName"): f.get("value") for f in filters}
            if props.get("associations.company") == "co-9" and props.get("firstname") == "Ada":
                resp.json.return_value = {"results": [{"id": "ct-by-name"}]}
            else:
                resp.json.return_value = {"results": []}
        elif method == "PATCH" and "/contacts/" in url:
            resp.json.return_value = {}
        elif method == "PUT":
            resp.json.return_value = {}
        elif method == "POST" and url.endswith("/notes"):
            resp.json.return_value = {"id": "note-1"}
        else:
            resp.json.return_value = {}
        return resp

    session.request.side_effect = _request
    lead = _sample_lead()
    lead.contacts[0].linkedin_url = None
    result = HubSpotClient(service_key="token", session=session).upsert_lead(lead, dry_run=False)
    assert result.hubspot_ids["contact_0"] == "ct-by-name"
    assert not any(
        call.args[0] == "POST" and call.args[1].endswith("/contacts")
        for call in session.request.call_args_list
    )


def test_verify_credentials(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "token")
    session = MagicMock()

    def _request(method, url, json=None, headers=None, timeout=None):
        assert method == "GET"
        assert "companies?limit=1" in url
        resp = MagicMock()
        resp.ok = True
        resp.content = b'{"results":[{"id":"1"}]}'
        resp.json.return_value = {"results": [{"id": "1"}]}
        return resp

    session.request.side_effect = _request
    assert HubSpotClient(service_key="token", session=session).verify() == {
        "ok": True,
        "portal_reachable": True,
        "companies_visible": 1,
    }


def test_hubspot_http_endpoints(monkeypatch) -> None:
    monkeypatch.setenv("HUBSPOT_SERVICE_KEY", "token")
    monkeypatch.setattr(
        "services.hubspot.client.HubSpotClient.verify",
        lambda self: {"ok": True, "portal_reachable": True, "companies_visible": 2},
    )
    from services.hubspot.app import app

    client = TestClient(app)
    lead = _sample_lead().model_dump()
    sanitize = client.post("/v1/sanitize-public-fields", json={"lead": lead})
    assert sanitize.status_code == 200
    sanitized = assert_json_response(sanitize.json(), LeadResult)
    assert sanitized.company.name == "Acme"
    assert sanitized.contacts[0].full_name == "Ada Lovelace"
    assert "email" not in sanitized.contacts[0].model_dump()

    dry = client.post("/v1/upsert-lead", json={"lead": lead, "dry_run": True})
    assert dry.status_code == 200
    upserted = assert_json_response(dry.json(), LeadResult)
    assert upserted.hubspot_ids["company"].startswith("dry-run-")
    assert upserted.hubspot_ids["verify_ok"] == "true"
    assert upserted.hubspot_ids["companies_visible"] == "2"
    assert upserted.status == LeadStatus.PUBLISHED
