"""Child workflow: enrich one company and publish to HubSpot."""

from __future__ import annotations

import os

from littlehorse.model.common_wfspec_pb2 import ExponentialBackoffRetryPolicy
from littlehorse.workflow import Workflow, WorkflowThread

CHILD_WF_NAME = "enrich-and-publish-lead"

TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "161"))
TASK_RETRIES = int(os.environ.get("TASK_RETRIES", "3"))


def _retry_policy() -> ExponentialBackoffRetryPolicy:
    return ExponentialBackoffRetryPolicy(
        base_interval_ms=1000,
        max_delay_ms=30_000,
        multiplier=2.0,
    )


def _on_error_notify_and_continue(step_name: str):
    """Notify Slack, then let the ThreadRun continue (do not fail the campaign)."""

    def handler(wf: WorkflowThread) -> None:
        wf.execute(
            "notify-failure",
            step_name,
            "ERROR",
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )

    return handler


def get_workflow() -> Workflow:
    """Build the child WfSpec for a single company lead."""

    def enrich_publish_workflow(wf: WorkflowThread) -> None:
        company = wf.declare_json_obj("company").required()
        dry_run = wf.declare_bool("dry-run").required()
        icp_version = wf.declare_str("icp-version").required()
        # campaign-id kept for observability / future note tagging
        wf.declare_str("campaign-id").required()
        catalog_ref = wf.declare_str("catalog-ref").required()
        icp_ref = wf.declare_str("icp-ref", "")
        campaign_config = wf.declare_json_obj("campaign-config", {})
        run_id = wf.declare_str("run-id", "")

        lead = wf.declare_json_obj("lead")

        prepared = wf.execute(
            "prepare-lead",
            company,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )
        lead.assign(prepared)
        wf.handle_any_failure(prepared, _on_error_notify_and_continue("prepare-lead"))

        job_skills_out = wf.execute(
            "extract-job-skills",
            lead,
            campaign_config,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(job_skills_out)
        wf.handle_any_failure(job_skills_out, _on_error_notify_and_continue("extract-job-skills"))

        find_out = wf.execute(
            "find-decision-makers",
            lead,
            icp_version,
            icp_ref,
            campaign_config,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(find_out)
        wf.handle_any_failure(find_out, _on_error_notify_and_continue("find-decision-makers"))

        sanitize_out = wf.execute(
            "sanitize-public-fields",
            lead,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(sanitize_out)
        wf.handle_any_failure(
            sanitize_out, _on_error_notify_and_continue("sanitize-public-fields")
        )

        match_out = wf.execute(
            "match-ioet-skills",
            lead,
            catalog_ref,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(match_out)
        wf.handle_any_failure(match_out, _on_error_notify_and_continue("match-ioet-skills"))

        email_out = wf.execute(
            "draft-outreach-email",
            lead,
            campaign_config,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(email_out)
        wf.handle_any_failure(email_out, _on_error_notify_and_continue("draft-outreach-email"))

        upsert_out = wf.execute(
            "upsert-hubspot",
            lead,
            dry_run,
            campaign_config,
            icp_ref,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        lead.assign(upsert_out)
        wf.handle_any_failure(upsert_out, _on_error_notify_and_continue("upsert-hubspot"))

        recorded = wf.execute(
            "record-lead-outcome",
            run_id,
            lead,
            dry_run,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )
        lead.assign(recorded)
        wf.handle_any_failure(recorded, _on_error_notify_and_continue("record-lead-outcome"))

        wf.complete(lead)

    return (
        Workflow(CHILD_WF_NAME, enrich_publish_workflow)
        .with_task_timeout_seconds(TASK_TIMEOUT_SECONDS)
        .with_retry_policy(TASK_RETRIES, _retry_policy())
    )
