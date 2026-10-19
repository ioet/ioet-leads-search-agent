"""Re-export campaign config models (canonical defs live in services.common)."""

from services.common.campaign_config import (
    CampaignConfig,
    CompaniesFilterConfig,
    DecisionMakersConfig,
    EmailDraftConfig,
    HiringSignalConfig,
    HiringSignalMode,
    HubspotOutputConfig,
    RunMode,
)

__all__ = [
    "CampaignConfig",
    "CompaniesFilterConfig",
    "DecisionMakersConfig",
    "EmailDraftConfig",
    "HiringSignalConfig",
    "HiringSignalMode",
    "HubspotOutputConfig",
    "RunMode",
]
