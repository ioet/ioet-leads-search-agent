"""HubSpot CRM client — allowlisted public fields only."""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import requests

from services.common.campaign_config import HubspotOutputConfig
from services.common.icp import load_icp
from services.common.icp_ref import load_icp_for_request
from services.common.linkedin import linkedin_url_search_variants, normalize_linkedin_url
from services.common.sanitize import hubspot_payload_from_lead, sanitize_lead
from services.common.schemas import Company, LeadResult, LeadStatus

logger = logging.getLogger(__name__)

HUBSPOT_BASE_URL = os.environ.get("HUBSPOT_BASE_URL", "https://api.hubapi.com").rstrip("/")


class HubSpotConfigError(RuntimeError):
    pass


class HubSpotClient:
    def __init__(self, service_key: str | None = None, session: requests.Session | None = None) -> None:
        self.service_key = (
            service_key if service_key is not None else os.environ.get("HUBSPOT_SERVICE_KEY", "")
        ).strip()
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        if not self.service_key:
            raise HubSpotConfigError("HUBSPOT_SERVICE_KEY is not configured")
        return {
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }

    def verify(self) -> dict[str, Any]:
        """Read-only credential check — lists one company; never writes."""
        data = self._request("GET", "/crm/v3/objects/companies?limit=1")
        results = data.get("results") or []
        return {
            "ok": True,
            "portal_reachable": True,
            "companies_visible": len(results),
        }

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{HUBSPOT_BASE_URL}{path}"
        response = self.session.request(
            method,
            url,
            json=payload,
            headers=self._headers(),
            timeout=60,
        )
        if not response.ok:
            logger.error("HubSpot %s %s failed: %s %s", method, path, response.status_code, response.text[:500])
            response.raise_for_status()
        if not response.content:
            return {}
        return response.json()

    def company_signals(self, company: Company) -> dict[str, Any]:
        """Best-effort CRM signals for pre-filtering. Missing scopes → warnings, not errors."""
        signals: dict[str, Any] = {
            "domain": company.domain,
            "exists": False,
            "hubspot_company_id": None,
            "lifecycle_stage": None,
            "has_owner": None,
            "notes_last_contacted": None,
            "has_open_deal": None,
            "warnings": [],
        }
        if not company.domain:
            signals["warnings"].append("no_domain")
            return signals

        try:
            company_id = self._search_company_by_domain(company.domain)
        except Exception as exc:  # noqa: BLE001
            signals["warnings"].append(f"company_search_failed:{exc}")
            return signals

        if not company_id:
            return signals

        signals["exists"] = True
        signals["hubspot_company_id"] = company_id
        try:
            data = self._request(
                "GET",
                f"/crm/v3/objects/companies/{company_id}"
                "?properties=lifecyclestage,hubspot_owner_id,notes_last_contacted",
            )
            props = data.get("properties") or {}
            signals["lifecycle_stage"] = props.get("lifecyclestage")
            owner = props.get("hubspot_owner_id")
            signals["has_owner"] = bool(owner)
            signals["notes_last_contacted"] = props.get("notes_last_contacted")
        except Exception as exc:  # noqa: BLE001
            signals["warnings"].append(f"company_props_failed:{exc}")

        try:
            deals = self._request(
                "GET",
                f"/crm/v4/objects/companies/{company_id}/associations/deals",
            )
            results = deals.get("results") or []
            signals["has_open_deal"] = bool(results)
        except Exception as exc:  # noqa: BLE001
            signals["warnings"].append(f"deals_lookup_failed:{exc}")
            signals["has_open_deal"] = None

        return signals

    def upsert_lead(
        self,
        lead: LeadResult,
        *,
        dry_run: bool = False,
        output_config: HubspotOutputConfig | None = None,
        icp_ref: str | None = None,
    ) -> LeadResult:
        clean = sanitize_lead(lead)
        out = output_config or HubspotOutputConfig()
        try:
            policy = load_icp_for_request(icp_ref=icp_ref).data_policy
        except Exception:
            policy = load_icp().data_policy
        payload = hubspot_payload_from_lead(clean, policy)

        if dry_run:
            # Exercise auth/scopes with a read-only call; never create/update CRM objects.
            verify = self.verify()
            ids = {
                "company": f"dry-run-company-{uuid.uuid4().hex[:8]}",
                "verify_ok": "true" if verify.get("ok") else "false",
                "companies_visible": str(verify.get("companies_visible", 0)),
            }
            if payload.get("company_note"):
                ids["note"] = f"dry-run-note-{uuid.uuid4().hex[:8]}"
            for idx, contact in enumerate(payload.get("contacts") or []):
                ids[f"contact_{idx}"] = f"dry-run-contact-{uuid.uuid4().hex[:8]}"
                if isinstance(contact, dict) and contact.get("note"):
                    ids[f"contact_note_{idx}"] = f"dry-run-contact-note-{uuid.uuid4().hex[:8]}"
            return clean.model_copy(
                update={"hubspot_ids": ids, "status": LeadStatus.PUBLISHED}
            )

        company_props = payload.get("company") or {}
        if out.lifecycle_stage:
            company_props = {**company_props, "lifecyclestage": out.lifecycle_stage}

        company_id, company_created = self._upsert_company(
            company_props,
            if_exists=out.if_company_exists,
        )
        ids: dict[str, str] = {"company": company_id}

        for idx, contact in enumerate(payload.get("contacts") or []):
            contact_note = contact.get("note")
            if out.lead_status:
                contact = {**contact, "hs_lead_status": out.lead_status}
            contact_id = self._upsert_contact(
                contact,
                company_id,
                if_exists=out.if_contact_exists,
            )
            if contact_id:
                ids[f"contact_{idx}"] = contact_id
            if contact_id and contact_note:
                note_id = self._create_note(str(contact_note), contact_id=contact_id)
                ids[f"contact_note_{idx}"] = note_id

        company_note = payload.get("company_note")
        # Always allow job/company notes; "add_job_note_only" still writes notes on existing companies.
        if company_note and (company_created or out.if_company_exists in {
            "add_job_note_only",
            "update",
        }):
            note_id = self._create_note(str(company_note), company_id=company_id)
            ids["note"] = note_id

        return clean.model_copy(update={"hubspot_ids": ids, "status": LeadStatus.PUBLISHED})

    def _upsert_company(
        self,
        props: dict[str, Any],
        *,
        if_exists: str = "update",
    ) -> tuple[str, bool]:
        domain = props.get("domain")
        name = props.get("name")
        if not name and not domain:
            raise ValueError("Company upsert requires name or domain")

        hs_props: dict[str, Any] = {}
        if name:
            hs_props["name"] = name
        if domain:
            hs_props["domain"] = domain
        if props.get("industry"):
            hs_props["industry"] = props["industry"]
        if props.get("lifecyclestage"):
            hs_props["lifecyclestage"] = props["lifecyclestage"]
        company_linkedin = normalize_linkedin_url(props.get("linkedin_url"))
        if company_linkedin:
            hs_props["linkedin_company_page"] = company_linkedin

        if domain:
            existing = self._search_company_by_domain(domain)
            if existing:
                if if_exists == "add_job_note_only":
                    return existing, False
                self._request(
                    "PATCH",
                    f"/crm/v3/objects/companies/{existing}",
                    {"properties": hs_props},
                )
                return existing, False

        created = self._request("POST", "/crm/v3/objects/companies", {"properties": hs_props})
        return str(created["id"]), True

    def _search_company_by_domain(self, domain: str) -> str | None:
        body = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "domain",
                            "operator": "EQ",
                            "value": domain,
                        }
                    ]
                }
            ],
            "properties": ["domain", "name"],
            "limit": 1,
        }
        data = self._request("POST", "/crm/v3/objects/companies/search", body)
        results = data.get("results") or []
        if not results:
            return None
        return str(results[0]["id"])

    def _upsert_contact(
        self,
        props: dict[str, Any],
        company_id: str,
        *,
        if_exists: str = "update",
    ) -> str | None:
        full_name = props.get("name") or ""
        parts = full_name.split(None, 1)
        first = parts[0] if parts else "Unknown"
        last = parts[1] if len(parts) > 1 else ""
        linkedin = normalize_linkedin_url(props.get("linkedin_url"))

        hs_props: dict[str, Any] = {
            "firstname": first,
            "lastname": last,
        }
        if props.get("title"):
            hs_props["jobtitle"] = props["title"]
        if linkedin:
            hs_props["hs_linkedin_url"] = linkedin
        if props.get("email"):
            hs_props["email"] = props["email"]
        if props.get("phone"):
            hs_props["phone"] = props["phone"]
        if props.get("hs_lead_status"):
            hs_props["hs_lead_status"] = props["hs_lead_status"]

        # Prefer normalized LinkedIn; fall back to firstname+lastname at this company.
        existing = None
        if linkedin:
            existing = self._search_contact_by_linkedin(linkedin)
        if not existing:
            existing = self._search_contact_by_name_and_company(first, last, company_id)

        if existing:
            if if_exists == "skip":
                return existing
            contact_id = existing
            self._request(
                "PATCH",
                f"/crm/v3/objects/contacts/{contact_id}",
                {"properties": hs_props},
            )
        else:
            created = self._request("POST", "/crm/v3/objects/contacts", {"properties": hs_props})
            contact_id = str(created["id"])

        self._associate_contact_company(contact_id, company_id)
        return contact_id

    def _search_contact_by_linkedin(self, linkedin_url: str) -> str | None:
        variants = linkedin_url_search_variants(linkedin_url)
        if not variants:
            return None
        # HubSpot ORs filterGroups — one search covers common URL forms already in CRM.
        body = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "hs_linkedin_url",
                            "operator": "EQ",
                            "value": candidate,
                        }
                    ]
                }
                for candidate in variants
            ],
            "properties": ["hs_linkedin_url", "firstname", "lastname"],
            "limit": 1,
        }
        try:
            data = self._request("POST", "/crm/v3/objects/contacts/search", body)
        except requests.HTTPError:
            # Property may not exist in all portals — soft-fail to name+company.
            return None
        results = data.get("results") or []
        if not results:
            return None
        return str(results[0]["id"])

    def _search_contact_by_name_and_company(
        self,
        firstname: str,
        lastname: str,
        company_id: str,
    ) -> str | None:
        filters: list[dict[str, str]] = [
            {"propertyName": "firstname", "operator": "EQ", "value": firstname},
            {
                "propertyName": "associations.company",
                "operator": "EQ",
                "value": company_id,
            },
        ]
        if lastname:
            filters.insert(
                1,
                {"propertyName": "lastname", "operator": "EQ", "value": lastname},
            )
        body = {
            "filterGroups": [{"filters": filters}],
            "properties": ["firstname", "lastname", "hs_linkedin_url"],
            "limit": 1,
        }
        try:
            data = self._request("POST", "/crm/v3/objects/contacts/search", body)
        except requests.HTTPError:
            logger.warning(
                "HubSpot name+company contact search failed for %s %s @ %s",
                firstname,
                lastname,
                company_id,
            )
            return None
        results = data.get("results") or []
        if not results:
            return None
        return str(results[0]["id"])

    def _associate_contact_company(self, contact_id: str, company_id: str) -> None:
        path = (
            f"/crm/v4/objects/contacts/{contact_id}/associations/companies/{company_id}"
        )
        try:
            self._request(
                "PUT",
                path,
                [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 1}],
            )
        except requests.HTTPError:
            logger.warning("Failed to associate contact %s with company %s", contact_id, company_id)

    def _create_note(
        self,
        body: str,
        *,
        company_id: str | None = None,
        contact_id: str | None = None,
    ) -> str:
        created = self._request(
            "POST",
            "/crm/v3/objects/notes",
            {
                "properties": {
                    "hs_note_body": body,
                    "hs_timestamp": str(int(time.time() * 1000)),
                },
            },
        )
        note_id = str(created["id"])
        if company_id:
            try:
                self._request(
                    "PUT",
                    f"/crm/v4/objects/notes/{note_id}/associations/companies/{company_id}",
                    [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 190}],
                )
            except requests.HTTPError:
                logger.warning("Failed to associate note %s with company %s", note_id, company_id)
        if contact_id:
            try:
                self._request(
                    "PUT",
                    f"/crm/v4/objects/notes/{note_id}/associations/contacts/{contact_id}",
                    [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}],
                )
            except requests.HTTPError:
                logger.warning("Failed to associate note %s with contact %s", note_id, contact_id)
        return note_id
