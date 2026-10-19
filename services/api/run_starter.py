"""Start a CampaignRun and kick off the LittleHorse parent workflow."""

from __future__ import annotations

import logging
from typing import Any

from services.api.lh_client import LittleHorseError, start_leads_search_run
from services.api.schemas.campaign_config import CampaignConfig, RunMode
from services.api.schemas.entities import (
    CampaignPublic,
    CampaignRunPublic,
    CampaignStatus,
    RunStatus,
    RunTrigger,
)
from services.api.stores import campaign_runs as run_store
from services.api.stores import icps as icp_store
from services.api.stores.icps import IcpNotFoundError

logger = logging.getLogger(__name__)


class RunStartError(RuntimeError):
    pass


def _outbound_segment_ids(icp_doc: dict[str, Any]) -> list[str]:
    segments = icp_doc.get("segments") or []
    ids = [
        str(s["id"])
        for s in segments
        if isinstance(s, dict) and s.get("in_outbound") and s.get("id")
    ]
    return ids


def build_workflow_variables(
    *,
    campaign: CampaignPublic,
    run_id: str,
    icp_json_uri: str,
    icp_doc: dict[str, Any],
) -> dict[str, Any]:
    segment_ids = _outbound_segment_ids(icp_doc)
    if not segment_ids:
        raise RunStartError("ICP has no outbound segments")

    icp_version = str(
        icp_doc.get("version") or campaign.icp_id
    )
    dry_run = campaign.config.run_mode != RunMode.LIVE
    max_leads = int(campaign.config.companies_per_run)

    return {
        "icp-version": icp_version,
        "segment-ids": segment_ids,
        "campaign-id": campaign.campaign_id,
        "max-leads": max_leads,
        "dry-run": dry_run,
        "run-id": run_id,
        "icp-ref": icp_json_uri,
        "campaign-config": campaign.config.model_dump_storage(),
    }


def start_campaign_run(
    *,
    campaign: CampaignPublic,
    trigger: RunTrigger = RunTrigger.MANUAL,
) -> CampaignRunPublic:
    if campaign.status == CampaignStatus.ENDED:
        raise RunStartError("Cannot start a run for an ended campaign")

    try:
        icp_meta = icp_store.require_icp(campaign.icp_id)
        icp_doc = icp_store.load_icp_document(campaign.icp_id)
    except IcpNotFoundError as exc:
        raise RunStartError("Campaign ICP not found") from exc
    except Exception as exc:
        raise RunStartError(f"Failed to load ICP document: {exc}") from exc

    run = run_store.create_run(
        campaign_id=campaign.campaign_id,
        campaign_name=campaign.name,
        trigger=trigger,
        status=RunStatus.PENDING,
    )

    try:
        variables = build_workflow_variables(
            campaign=campaign,
            run_id=run.run_id,
            icp_json_uri=icp_meta.icp_json_s3_uri,
            icp_doc=icp_doc,
        )
        lh_id = start_leads_search_run(variables)
    except (LittleHorseError, RunStartError) as exc:
        logger.exception("Failed to start LH run for campaign %s", campaign.campaign_id)
        return run_store.complete_run(
            run.run_id,
            status=RunStatus.FAILED,
            result_summary={"error": str(exc)},
        )

    return run_store.mark_running(run.run_id, lh_wf_run_id=lh_id)


def start_unsaved_dry_run(*, name: str, icp_id: str, config: CampaignConfig) -> str:
    """Start the parent workflow from unsaved form state.

    Forces a dry run and an empty run id so the workers do not write a campaign
    run or call HubSpot.
    """
    try:
        icp_meta = icp_store.require_icp(icp_id)
        icp_doc = icp_store.load_icp_document(icp_id)
    except IcpNotFoundError as exc:
        raise RunStartError("Campaign ICP not found") from exc
    except Exception as exc:
        raise RunStartError(f"Failed to load ICP document: {exc}") from exc

    dry_config = config.model_copy(update={"run_mode": RunMode.DRY_RUN})
    campaign = CampaignPublic(
        campaign_id="unsaved-test",
        name=(name or "Unsaved test").strip() or "Unsaved test",
        owner_user_id="",
        icp_id=icp_id,
        status=CampaignStatus.DRAFT,
        config=dry_config,
        created_at="",
        updated_at="",
    )
    variables = build_workflow_variables(
        campaign=campaign,
        run_id="",
        icp_json_uri=icp_meta.icp_json_s3_uri,
        icp_doc=icp_doc,
    )
    try:
        return start_leads_search_run(variables)
    except LittleHorseError as exc:
        raise RunStartError(str(exc)) from exc
