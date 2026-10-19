"""Apply campaign skip-rules to HubSpot company signals."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from services.common.campaign_config import CompaniesFilterConfig
from services.common.schemas import Company

logger = logging.getLogger(__name__)

_CUSTOMER_STAGES = {"customer", "evangelist"}


def should_skip_company(
    signals: dict[str, Any],
    filt: CompaniesFilterConfig,
) -> tuple[bool, str | None]:
    if not signals.get("exists"):
        return False, None

    if filt.skip_customers:
        stage = (signals.get("lifecycle_stage") or "").lower()
        if stage in _CUSTOMER_STAGES:
            return True, "customer"

    if filt.skip_has_owner and signals.get("has_owner") is True:
        return True, "has_owner"

    if filt.skip_open_deals and signals.get("has_open_deal") is True:
        return True, "open_deal"

    days = filt.skip_contacted_within_days
    if days is not None and days > 0:
        raw = signals.get("notes_last_contacted")
        if raw:
            try:
                # HubSpot often returns ms epoch or ISO.
                if str(raw).isdigit():
                    ts = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
                else:
                    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - ts).days
                if age_days <= days:
                    return True, "recently_contacted"
            except (TypeError, ValueError, OSError):
                logger.debug("Could not parse notes_last_contacted=%r", raw)

    return False, None


def filter_companies(
    companies: list[Company],
    signals_by_domain: dict[str, dict[str, Any]],
    filt: CompaniesFilterConfig,
) -> list[Company]:
    kept: list[Company] = []
    for company in companies:
        key = (company.domain or "").lower()
        signals = signals_by_domain.get(key) or {"exists": False}
        skip, reason = should_skip_company(signals, filt)
        if skip:
            logger.info(
                "Skipping %s (%s) due to HubSpot filter: %s",
                company.name,
                company.domain,
                reason,
            )
            continue
        kept.append(company)
    return kept
