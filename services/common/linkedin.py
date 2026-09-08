"""LinkedIn URL normalization for CRM matching."""

from __future__ import annotations

from urllib.parse import urlparse

_PROFILE_KINDS = frozenset({"in", "company", "school", "pub"})


def normalize_linkedin_url(value: str | None) -> str | None:
    """Canonicalize a LinkedIn profile/company URL for storage and matching.

    Returns ``https://www.linkedin.com/{in|company|school|pub}/{slug}`` or ``None``.
    Strips scheme/host variants, ``www``, trailing slashes, query, and fragment.
    """
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if not raw.lower().startswith(("http://", "https://")):
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in ("linkedin.com", "linkedin.cn"):
        return None

    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        return None
    kind = parts[0].lower()
    slug = parts[1].split("?")[0].rstrip("/").lower()
    if kind not in _PROFILE_KINDS or not slug:
        return None
    return f"https://www.linkedin.com/{kind}/{slug}"


def linkedin_url_search_variants(normalized: str) -> list[str]:
    """EQ search values that may already exist in HubSpot for the same profile."""
    canon = normalize_linkedin_url(normalized)
    if not canon:
        return []
    # path is /in/slug after www.linkedin.com
    path = canon.removeprefix("https://www.linkedin.com")
    variants = [
        canon,
        f"https://linkedin.com{path}",
        f"http://www.linkedin.com{path}",
        f"http://linkedin.com{path}",
        f"{canon}/",
        f"https://linkedin.com{path}/",
        path.lstrip("/"),  # bare path sometimes stored
        f"www.linkedin.com{path}",
    ]
    # Preserve order, drop empties/dupes
    seen: set[str] = set()
    out: list[str] = []
    for item in variants:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
