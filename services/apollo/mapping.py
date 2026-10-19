"""Map ICP segment filters to Apollo search parameters."""

from __future__ import annotations

from typing import Any

from services.common.icp import Segment, apollo_hard_filters

# ICP industry ids → Apollo keyword / tag phrases.
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "ai_ml": ["artificial intelligence", "machine learning", "AI"],
    "ai_agentic_tooling": ["AI agents", "agentic AI", "LLM tooling"],
    "infrastructure": ["infrastructure", "cloud infrastructure", "devtools"],
    "data": ["data platform", "data infrastructure", "analytics"],
    "fintech": ["fintech", "financial technology"],
    "payments": ["payments", "payment processing"],
    "lending": ["lending", "consumer lending"],
    "insurance": ["insurtech", "insurance technology"],
    "banking": ["banking", "neobank"],
    "ecommerce": ["ecommerce", "e-commerce"],
    "dtc": ["DTC", "direct to consumer"],
    "consumer_brand_tech": ["consumer brand", "consumer tech"],
    "govtech": ["govtech", "government technology"],
    "security": ["cybersecurity", "security"],
    "networking": ["networking", "network infrastructure"],
}

GEO_TO_APOLLO: dict[str, str] = {
    "US": "United States",
    "CA": "Canada",
}

# Apollo expects closed ranges like "11,50".
EMPLOYEE_RANGE_BUCKETS: list[tuple[int, int, str]] = [
    (1, 10, "1,10"),
    (11, 20, "11,20"),
    (21, 50, "21,50"),
    (51, 100, "51,100"),
    (101, 200, "101,200"),
    (201, 500, "201,500"),
    (501, 1000, "501,1000"),
    (1001, 2000, "1001,2000"),
    (2001, 5000, "2001,5000"),
    (5001, 10000, "5001,10000"),
]

FUNDING_STAGE_LABELS: dict[str, str] = {
    "pre_seed": "Pre-Seed",
    "seed": "Seed",
    "series_a": "Series A",
    "series_b": "Series B",
    "series_c": "Series C",
}


def employee_ranges(min_count: int | None, max_count: int | None) -> list[str]:
    if min_count is None and max_count is None:
        return []
    lo = min_count or 1
    hi = max_count or 100_000
    selected: list[str] = []
    for bucket_lo, bucket_hi, label in EMPLOYEE_RANGE_BUCKETS:
        if bucket_hi < lo or bucket_lo > hi:
            continue
        selected.append(label)
    return selected


def industry_keywords(industries: list[str]) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()
    for industry in industries:
        for phrase in INDUSTRY_KEYWORDS.get(industry, [industry.replace("_", " ")]):
            if phrase not in seen:
                seen.add(phrase)
                keywords.append(phrase)
    return keywords


def segment_to_apollo_org_search(
    segment: Segment,
    page: int = 1,
    per_page: int = 25,
    *,
    company_filter: Any | None = None,
) -> dict[str, Any]:
    filters = apollo_hard_filters(segment)
    payload: dict[str, Any] = {
        "page": page,
        "per_page": min(per_page, 100),
    }

    ranges = employee_ranges(
        filters.get("employee_count_min"),
        filters.get("employee_count_max"),
    )
    if ranges:
        payload["organization_num_employees_ranges"] = ranges

    geos = [GEO_TO_APOLLO.get(g, g) for g in filters.get("geos") or []]
    if geos:
        payload["organization_locations"] = geos

    keywords = industry_keywords(filters.get("industries") or [])
    if filters.get("yc_preferred"):
        keywords = list(keywords) + ["Y Combinator", "YC"]
        for batch in filters.get("yc_batches") or []:
            keywords.append(f"YC {batch}")
    if keywords:
        # Apollo accepts a single q_keywords string for mixed org search.
        payload["q_organization_keyword_tags"] = keywords

    funding = [
        FUNDING_STAGE_LABELS.get(stage, stage)
        for stage in filters.get("funding_stages") or []
    ]
    if funding:
        payload["organization_latest_funding_stage_cd"] = funding

    if company_filter is not None:
        from services.common.campaign_config import apply_company_filter_to_apollo_payload

        payload = apply_company_filter_to_apollo_payload(payload, company_filter)

    return payload
