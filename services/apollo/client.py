"""Apollo.io HTTP client (public fields only)."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from services.apollo.mapping import segment_to_apollo_org_search
from services.common.icp import IdealCustomerProfile, Segment, titles_for_company_size
from services.common.limits import max_contacts_per_company
from services.common.sanitize import sanitize_company, sanitize_contact
from services.common.schemas import Company, Contact

logger = logging.getLogger(__name__)

APOLLO_BASE_URL = os.environ.get("APOLLO_BASE_URL", "https://api.apollo.io/api/v1").rstrip("/")
_BULK_MATCH_LIMIT = 10


def enrich_contacts_enabled() -> bool:
    """People search omits email/phone and masks last names; enrichment costs 1 credit/person."""
    return os.environ.get("APOLLO_ENRICH_CONTACTS", "true").strip().lower() in {"1", "true", "yes"}


class ApolloConfigError(RuntimeError):
    pass


class ApolloClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("APOLLO_API_KEY", "")).strip()
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ApolloConfigError("APOLLO_API_KEY is not configured")
        return {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key,
        }

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{APOLLO_BASE_URL}{path}"
        response = self.session.post(url, json=payload, headers=self._headers(), timeout=60)
        if not response.ok:
            logger.error("Apollo %s failed: %s %s", path, response.status_code, response.text[:500])
            response.raise_for_status()
        return response.json()

    def search_companies_for_segment(
        self,
        segment: Segment,
        *,
        max_results: int = 25,
        company_filter: Any | None = None,
    ) -> list[Company]:
        remaining = max_results
        page = 1
        companies: list[Company] = []
        while remaining > 0:
            per_page = min(remaining, 100)
            payload = segment_to_apollo_org_search(
                segment,
                page=page,
                per_page=per_page,
                company_filter=company_filter,
            )
            if page == 1:
                logger.info(
                    "Apollo company search segment=%s locations=%s employee_ranges=%s",
                    segment.id,
                    payload.get("organization_locations"),
                    payload.get("organization_num_employees_ranges"),
                )
            data = self._post("/mixed_companies/search", payload)
            orgs = data.get("organizations") or data.get("accounts") or []
            if not orgs:
                break
            for raw in orgs:
                companies.append(_org_to_company(raw, segment.id))
                if len(companies) >= max_results:
                    return companies
            pagination = data.get("pagination") or {}
            total_pages = int(pagination.get("total_pages") or page)
            if page >= total_pages:
                break
            page += 1
            remaining = max_results - len(companies)
        return companies

    def find_decision_makers(
        self,
        company: Company,
        titles: list[str],
        *,
        max_results: int = 10,
    ) -> list[Contact]:
        if not titles:
            return []
        base: dict[str, Any] = {
            "page": 1,
            "per_page": min(max_results, 100),
            "person_titles": titles,
            "include_similar_titles": True,
        }
        scopes: list[dict[str, Any]] = []
        if company.apollo_organization_id:
            scopes.append({"organization_ids": [company.apollo_organization_id]})
        if company.domain:
            scopes.append({"q_organization_domains_list": [company.domain]})
        if not scopes:
            # api_search has no organization-name filter; keyword is the closest fallback.
            scopes.append({"q_keywords": company.name})

        people: list[dict[str, Any]] = []
        used_scope: dict[str, Any] = {}
        for scope in scopes:
            data = self._post("/mixed_people/api_search", {**base, **scope})
            people = [p for p in data.get("people") or [] if isinstance(p, dict) and _person_name(p)]
            used_scope = scope
            if people:
                break
        people = people[:max_results]
        logger.info(
            "Apollo people search company=%s org_id=%s domain=%s titles=%s scope=%s raw_people=%d",
            company.name,
            company.apollo_organization_id,
            company.domain,
            titles,
            list(used_scope.keys()),
            len(people),
        )

        if people and enrich_contacts_enabled():
            people = self._enrich_people(people)

        contacts: list[Contact] = []
        for raw in people:
            contact = _person_to_contact(raw, titles)
            if contact is not None:
                contacts.append(contact)
        return contacts

    def _enrich_people(self, people: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Merge people/bulk_match results (full name, LinkedIn, work email) into search rows."""
        ids = [str(p["id"]) for p in people if p.get("id")]
        matches: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ids), _BULK_MATCH_LIMIT):
            chunk = ids[start : start + _BULK_MATCH_LIMIT]
            try:
                data = self._post("/people/bulk_match", {"details": [{"id": i} for i in chunk]})
            except requests.HTTPError as exc:
                logger.warning("Apollo bulk_match failed; keeping search-only contacts: %s", exc)
                return people
            for match in data.get("matches") or []:
                if isinstance(match, dict) and match.get("id"):
                    matches[str(match["id"])] = match

        enriched: list[dict[str, Any]] = []
        for raw in people:
            match = matches.get(str(raw.get("id")))
            if match:
                raw = {**raw, **{k: v for k, v in match.items() if v not in (None, "", [])}}
            enriched.append(raw)
        return enriched


def search_companies(
    icp: IdealCustomerProfile,
    segment_ids: list[str],
    max_results: int,
    client: ApolloClient | None = None,
    *,
    company_filter: Any | None = None,
) -> list[Company]:
    apollo = client or ApolloClient()
    per_segment = max(1, max_results // max(len(segment_ids), 1))
    results: list[Company] = []
    seen_domains: set[str] = set()

    for segment_id in segment_ids:
        segment = icp.segment_by_id(segment_id)
        if not segment.in_outbound:
            logger.warning("Skipping non-outbound segment %s", segment_id)
            continue
        found = apollo.search_companies_for_segment(
            segment,
            max_results=per_segment,
            company_filter=company_filter,
        )
        for company in found:
            key = (company.domain or company.name).lower()
            if key in seen_domains:
                continue
            seen_domains.add(key)
            results.append(company)
            if len(results) >= max_results:
                return results
    return results


def find_decision_makers(
    icp: IdealCustomerProfile,
    company: Company,
    titles: list[str] | None = None,
    client: ApolloClient | None = None,
    *,
    max_results: int | None = None,
) -> list[Contact]:
    apollo = client or ApolloClient()
    resolved = titles or titles_for_company_size(icp, company.employee_count)
    limit = max_results if max_results is not None else max_contacts_per_company()
    return apollo.find_decision_makers(company, resolved, max_results=limit)


def _org_to_company(raw: dict[str, Any], segment_id: str) -> Company:
    linkedin = raw.get("linkedin_url") or raw.get("organization_linkedin_url")
    industry = None
    industries = raw.get("industries") or raw.get("industry")
    if isinstance(industries, list) and industries:
        industry = str(industries[0])
    elif isinstance(industries, str):
        industry = industries

    # Saved "accounts" carry the org under organization_id; plain organizations use id.
    org_id = raw.get("organization_id") or raw.get("id")
    company = Company(
        name=str(raw.get("name") or raw.get("organization_name") or "Unknown"),
        domain=_normalize_domain(raw.get("primary_domain") or raw.get("website_url") or raw.get("domain")),
        industry=industry,
        linkedin_url=linkedin,
        employee_count=_as_int(raw.get("estimated_num_employees") or raw.get("employee_count")),
        segment_id=segment_id,
        apollo_organization_id=str(org_id) if org_id else None,
    )
    return sanitize_company(company)


def _person_name(raw: dict[str, Any]) -> str:
    first = (raw.get("first_name") or "").strip()
    last = (raw.get("last_name") or "").strip()
    return f"{first} {last}".strip() or str(raw.get("name") or "").strip()


def _person_to_contact(raw: dict[str, Any], titles: list[str]) -> Contact | None:
    full_name = _person_name(raw)
    if not full_name:
        return None
    title = raw.get("title") or raw.get("headline")
    linkedin = raw.get("linkedin_url")
    contact = Contact(
        full_name=full_name,
        title=str(title) if title else None,
        linkedin_url=str(linkedin) if linkedin else None,
        email=_person_email(raw),
        phone=_person_phone(raw),
        persona_tier=_guess_persona_tier(str(title) if title else None, titles),
    )
    return sanitize_contact(contact)


def _usable_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip()
    # Apollo returns placeholders like email_not_unlocked@domain.com for locked emails.
    if "@" not in email or "not_unlocked" in email.lower():
        return None
    return email


def _person_email(raw: dict[str, Any]) -> str | None:
    email = _usable_email(raw.get("email"))
    if email:
        return email
    emails = raw.get("emails") or raw.get("contact_emails") or raw.get("personal_emails")
    if isinstance(emails, list):
        for item in emails:
            value = (item.get("email") or item.get("address")) if isinstance(item, dict) else item
            email = _usable_email(value)
            if email:
                return email
    return None


def _person_phone(raw: dict[str, Any]) -> str | None:
    phone = raw.get("phone") or raw.get("sanitized_phone")
    if isinstance(phone, str) and phone.strip():
        return phone.strip()
    numbers = raw.get("phone_numbers") or raw.get("phones")
    if isinstance(numbers, list):
        for item in numbers:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                value = item.get("sanitized_number") or item.get("raw_number") or item.get("number")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _guess_persona_tier(title: str | None, requested_titles: list[str]) -> int | None:
    if not title:
        return None
    lowered = title.lower()
    for idx, candidate in enumerate(requested_titles):
        if candidate.lower() in lowered:
            # Rough: earlier ICP titles tend to be higher tier; caller can refine later.
            if idx < 5:
                return 1
            if idx < 8:
                return 2
            return 3
    return None


def _normalize_domain(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    text = text.removeprefix("https://").removeprefix("http://")
    text = text.split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
