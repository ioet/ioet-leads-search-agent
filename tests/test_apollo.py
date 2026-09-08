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
    assert "email" not in validated_contact.model_dump()


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
        expected={
            "page": 1,
            "person_titles": ["CTO", "VP Engineering"],
            "include_similar_titles": True,
            "q_organization_domains_list": ["acme.ai"],
        },
    )
    assert isinstance(payload["per_page"], int)
    args, _ = session.post.call_args
    assert str(args[0]).endswith("/mixed_people/api_search")


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
