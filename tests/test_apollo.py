"""Apollo mapping + client tests (HTTP mocked)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from services.apollo.client import ApolloClient, _org_to_company, _person_to_contact, find_decision_makers
from services.apollo.mapping import employee_ranges, industry_keywords, segment_to_apollo_org_search
from services.common.icp import load_icp
from services.common.schemas import Company, CompanySearchRequest, Contact
from tests.helpers import assert_http_call_json, assert_json_response, assert_json_response_list


def test_employee_ranges_overlap() -> None:
    ranges = employee_ranges(10, 500)
    assert isinstance(ranges, list)
    assert all(isinstance(r, str) for r in ranges)
    assert "11,20" in ranges
    assert "201,500" in ranges
    assert "5001,10000" not in ranges


def test_industry_keywords_primary() -> None:
    kws = industry_keywords(["fintech", "ai_ml"])
    assert isinstance(kws, list)
    assert all(isinstance(k, str) for k in kws)
    assert any("fintech" in k.lower() for k in kws)
    assert any("artificial intelligence" in k.lower() for k in kws)


def test_segment_to_apollo_payload() -> None:
    icp = load_icp()
    segment = icp.segment_by_id("primary")
    payload = segment_to_apollo_org_search(segment, per_page=10)
    assert isinstance(payload, dict)
    assert payload["per_page"] == 10
    assert isinstance(payload["per_page"], int)
    assert "United States" in payload["organization_locations"]
    assert isinstance(payload["organization_num_employees_ranges"], list)
    assert isinstance(payload["q_organization_keyword_tags"], list)


def test_org_and_person_mappers_drop_sensitive() -> None:
    company = _org_to_company(
        {
            "name": "Acme",
            "primary_domain": "https://www.acme.com/about",
            "industries": ["fintech"],
            "linkedin_url": "https://linkedin.com/company/acme",
            "estimated_num_employees": 42,
            "email": "should-not-appear@acme.com",
        },
        "primary",
    )
    validated = assert_json_response(company.model_dump(), Company)
    assert validated.name == "Acme"
    assert validated.domain == "acme.com"
    assert validated.segment_id == "primary"
    assert validated.employee_count == 42
    assert isinstance(validated.employee_count, int)
    assert "email" not in validated.model_dump()

    contact = _person_to_contact(
        {
            "first_name": "Ada",
            "last_name": "Lovelace",
            "title": "CTO",
            "linkedin_url": "https://linkedin.com/in/ada",
            "email": "ada@acme.com",
            "phone": "555",
        },
        ["CTO", "CEO"],
    )
    assert contact is not None
    validated_contact = assert_json_response(contact.model_dump(), Contact)
    assert validated_contact.full_name == "Ada Lovelace"
    assert validated_contact.title == "CTO"
    assert validated_contact.email == "ada@acme.com"
    assert validated_contact.phone == "555"

    from_numbers = _person_to_contact(
        {
            "name": "Grace Hopper",
            "title": "CEO",
            "contact_emails": [{"email": "grace@acme.com"}],
            "phone_numbers": [{"sanitized_number": "+1-555-0199"}],
        },
        ["CEO"],
    )
    assert from_numbers is not None
    assert from_numbers.email == "grace@acme.com"
    assert from_numbers.phone == "+1-555-0199"


def test_search_companies_http_mocked(monkeypatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "organizations": [
            {
                "name": "Acme AI",
                "primary_domain": "acme.ai",
                "industries": ["artificial intelligence"],
                "estimated_num_employees": 30,
            }
        ],
        "pagination": {"total_pages": 1},
    }
    session.post.return_value = response

    client = ApolloClient(api_key="test-key", session=session)
    icp = load_icp()
    from services.apollo.client import search_companies

    results = search_companies(icp, ["primary"], max_results=5, client=client)
    assert len(results) == 1
    company = assert_json_response_list([c.model_dump() for c in results], Company)[0]
    assert company.name == "Acme AI"
    assert company.domain == "acme.ai"
    assert company.employee_count == 30

    payload = assert_http_call_json(session, expected={"per_page": 5})
    assert isinstance(payload["organization_locations"], list)
    assert isinstance(payload["organization_num_employees_ranges"], list)
    _, kwargs = session.post.call_args
    assert kwargs["headers"]["X-Api-Key"] == "test-key"
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_find_decision_makers_request_payload(monkeypatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {
        "people": [
            {
                "first_name": "Ada",
                "last_name": "Lovelace",
                "title": "CTO",
                "linkedin_url": "https://linkedin.com/in/ada",
            }
        ]
    }
    session.post.return_value = response

    icp = load_icp()
    company = Company(name="Acme AI", domain="acme.ai", employee_count=30)
    contacts = find_decision_makers(
        icp,
        company,
        titles=["CTO", "VP Engineering"],
        client=ApolloClient(api_key="test-key", session=session),
    )
    assert len(contacts) == 1
    contact = assert_json_response(contacts[0].model_dump(), Contact)
    assert contact.full_name == "Ada Lovelace"
    assert contact.title == "CTO"

    payload = assert_http_call_json(
        session,
        call_index=0,
        expected={
            "page": 1,
            "person_titles": ["CTO", "VP Engineering"],
            "include_similar_titles": True,
            "q_organization_domains_list": ["acme.ai"],
        },
    )
    assert isinstance(payload["per_page"], int)
    args, _ = session.post.call_args_list[0]
    assert str(args[0]).endswith("/mixed_people/api_search")


def test_find_decision_makers_uses_org_id_and_enriches(monkeypatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    monkeypatch.delenv("APOLLO_ENRICH_CONTACTS", raising=False)
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        resp = MagicMock()
        resp.ok = True
        if url.endswith("/mixed_people/api_search"):
            if json.get("organization_ids") == ["org-123"]:
                resp.json.return_value = {
                    "people": [
                        {
                            "id": "p-1",
                            "first_name": "Marcus",
                            "last_name_obfuscated": "El***y",
                            "title": "Co-Founder",
                            "has_email": True,
                        }
                    ]
                }
            else:
                resp.json.return_value = {"people": []}
        elif url.endswith("/people/bulk_match"):
            resp.json.return_value = {
                "matches": [
                    {
                        "id": "p-1",
                        "first_name": "Marcus",
                        "last_name": "Ellery",
                        "linkedin_url": "http://www.linkedin.com/in/marcus-ellery",
                        "email": "marcus@acme.ai",
                        "phone_numbers": [{"sanitized_number": "+15550100"}],
                    }
                ]
            }
        return resp

    session = MagicMock()
    session.post.side_effect = fake_post
    company = Company(
        name="Acme AI",
        domain="acme.ai",
        apollo_organization_id="org-123",
    )
    contacts = ApolloClient(api_key="test-key", session=session).find_decision_makers(
        company, ["Co-Founder"], max_results=1
    )

    assert calls[0][1]["organization_ids"] == ["org-123"]
    assert "q_organization_domains_list" not in calls[0][1]
    assert calls[1][0].endswith("/people/bulk_match")
    assert calls[1][1] == {"details": [{"id": "p-1"}]}
    assert len(contacts) == 1
    assert contacts[0].full_name == "Marcus Ellery"
    assert contacts[0].email == "marcus@acme.ai"
    assert contacts[0].phone == "+15550100"
    assert contacts[0].linkedin_url == "http://www.linkedin.com/in/marcus-ellery"


def test_find_decision_makers_falls_back_to_domain_and_skips_locked_email(monkeypatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    calls: list[dict] = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(json)
        resp = MagicMock()
        resp.ok = True
        if url.endswith("/mixed_people/api_search"):
            people = [{"id": "p-2", "first_name": "Ana", "title": "CTO"}]
            resp.json.return_value = {"people": people if "q_organization_domains_list" in json else []}
        else:
            resp.json.return_value = {
                "matches": [{"id": "p-2", "last_name": "Diaz", "email": "email_not_unlocked@acme.ai"}]
            }
        return resp

    session = MagicMock()
    session.post.side_effect = fake_post
    company = Company(name="Acme AI", domain="acme.ai", apollo_organization_id="org-x")
    contacts = ApolloClient(api_key="test-key", session=session).find_decision_makers(
        company, ["CTO"], max_results=1
    )

    assert "organization_ids" in calls[0]
    assert calls[1]["q_organization_domains_list"] == ["acme.ai"]
    assert contacts[0].full_name == "Ana Diaz"
    assert contacts[0].email is None


def test_find_decision_makers_enrichment_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("APOLLO_API_KEY", "test-key")
    monkeypatch.setenv("APOLLO_ENRICH_CONTACTS", "false")
    session = MagicMock()
    response = MagicMock()
    response.ok = True
    response.json.return_value = {"people": [{"id": "p-3", "first_name": "Lee", "title": "CEO"}]}
    session.post.return_value = response

    contacts = ApolloClient(api_key="test-key", session=session).find_decision_makers(
        Company(name="Acme", domain="acme.ai"), ["CEO"], max_results=1
    )
    assert contacts[0].full_name == "Lee"
    assert session.post.call_count == 1


def test_org_to_company_keeps_apollo_org_id() -> None:
    company = _org_to_company({"id": "org-9", "name": "Acme", "primary_domain": "acme.ai"}, "primary")
    assert company.apollo_organization_id == "org-9"
    account = _org_to_company(
        {"id": "acct-1", "organization_id": "org-10", "name": "Beta", "domain": "beta.io"},
        "primary",
    )
    assert account.apollo_organization_id == "org-10"


def test_apollo_endpoints_require_api_key(monkeypatch) -> None:
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    from services.apollo.app import app

    client = TestClient(app)
    request_body = {
        "icp_version": load_icp().version,
        "segment_ids": ["primary"],
        "max_results": 5,
    }
    assert_json_response(request_body, CompanySearchRequest)
    response = client.post("/v1/search-companies", json=request_body)
    assert response.status_code == 503
