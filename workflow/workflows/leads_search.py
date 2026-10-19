"""Parent workflow: discover, score, fan-out per lead, aggregate."""

from __future__ import annotations

import os

from littlehorse.model.common_wfspec_pb2 import ExponentialBackoffRetryPolicy
from littlehorse.workflow import Workflow, WorkflowThread

from workflow.workflows.enrich_publish import CHILD_WF_NAME

PARENT_WF_NAME = "leads-search-workflow"

TASK_TIMEOUT_SECONDS = int(os.environ.get("TASK_TIMEOUT_SECONDS", "161"))
TASK_RETRIES = int(os.environ.get("TASK_RETRIES", "3"))


def _retry_policy() -> ExponentialBackoffRetryPolicy:
    return ExponentialBackoffRetryPolicy(
        base_interval_ms=1000,
        max_delay_ms=30_000,
        multiplier=2.0,
    )


def _on_error_notify_and_continue(run_id, step_name: str):
    """Record the campaign run as failed, notify, then stop the parent thread.

    ``record-campaign-run`` runs first so a down notify service cannot leave the
    UI stuck on "running". ``run_id`` is the parent variable — re-declaring it
    inside each handler is rejected by LittleHorse.
    """

    def handler(wf: WorkflowThread) -> None:
        wf.execute(
            "record-campaign-run",
            run_id,
            {"step": step_name, "error": "task failed"},
            "failed",
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )
        wf.execute(
            "notify-failure",
            step_name,
            "ERROR",
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )
        wf.fail(step_name, f"{step_name} failed")

    return handler


def _enrich_one_company(wf: WorkflowThread) -> None:
    """Per-item thread: launch child WfSpec for one company from the JSON_ARR."""
    company = wf.declare_json_obj("INPUT")
    dry_run = wf.declare_bool("enrich-dry-run")
    icp_version = wf.declare_str("enrich-icp-version")
    campaign_id = wf.declare_str("enrich-campaign-id")
    catalog_ref = wf.declare_str("enrich-catalog-ref")
    icp_ref = wf.declare_str("enrich-icp-ref")
    campaign_config = wf.declare_json_obj("enrich-campaign-config")
    run_id = wf.declare_str("enrich-run-id")

    child = wf.run_wf(
        CHILD_WF_NAME,
        inputs={
            "company": company,
            "dry-run": dry_run,
            "icp-version": icp_version,
            "campaign-id": campaign_id,
            "catalog-ref": catalog_ref,
            "icp-ref": icp_ref,
            "campaign-config": campaign_config,
            "run-id": run_id,
        },
    )
    wf.wait_for_child_wf(child)


def get_workflow() -> Workflow:
    """Build the parent WfSpec."""

    def leads_search_workflow(wf: WorkflowThread) -> None:
        icp_version = wf.declare_str("icp-version").required().searchable()
        segment_ids = wf.declare_json_arr("segment-ids").required()
        campaign_id = wf.declare_str("campaign-id").required().searchable()
        max_leads = wf.declare_int("max-leads").required()
        dry_run = wf.declare_bool("dry-run").required().searchable()
        # Optional when started via lhctl; set by the campaign API for tracked runs.
        run_id = wf.declare_str("run-id", "").searchable()
        icp_ref = wf.declare_str("icp-ref", "")
        campaign_config = wf.declare_json_obj("campaign-config", {})

        companies = wf.declare_json_arr("companies")
        selected = wf.declare_json_arr("selected-companies")
        notification = wf.declare_json_obj("notification")
        search_count = wf.declare_int("search-count")
        catalog_ref = wf.declare_str("catalog-ref")

        search_out = wf.execute(
            "search-companies",
            icp_version,
            segment_ids,
            max_leads,
            icp_ref,
            campaign_config,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            retries=TASK_RETRIES,
            exponential_backoff=_retry_policy(),
        )
        companies.assign(search_out)
        wf.handle_any_failure(search_out, _on_error_notify_and_continue(run_id, "search-companies"))

        count_out = wf.execute(
            "count-companies",
            companies,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
        )
        search_count.assign(count_out)

        def _notify_empty_and_exit(thread: WorkflowThread) -> None:
            notify_payload = thread.execute(
                "build-empty-search-notification",
                icp_version,
                segment_ids,
                campaign_id,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
            )
            notification.assign(notify_payload)
            notify_out = thread.execute(
                "notify",
                notification,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
            )
            thread.handle_any_failure(notify_out, _on_error_notify_and_continue(run_id, "notify"))
            record_out = thread.execute(
                "record-campaign-run",
                run_id,
                notification,
                "completed",
                timeout_seconds=TASK_TIMEOUT_SECONDS,
            )
            thread.handle_any_failure(
                record_out, _on_error_notify_and_continue(run_id, "record-campaign-run")
            )
            thread.complete()

        def _continue_after_search(thread: WorkflowThread) -> None:
            filter_out = thread.execute(
                "filter-hubspot-companies",
                companies,
                campaign_config,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
                exponential_backoff=_retry_policy(),
            )
            companies.assign(filter_out)
            thread.handle_any_failure(
                filter_out, _on_error_notify_and_continue(run_id, "filter-hubspot-companies")
            )

            score_out = thread.execute(
                "score-companies-icp",
                icp_version,
                companies,
                icp_ref,
                campaign_config,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
                exponential_backoff=_retry_policy(),
            )
            companies.assign(score_out)
            thread.handle_any_failure(
                score_out, _on_error_notify_and_continue(run_id, "score-companies-icp")
            )

            select_out = thread.execute(
                "select-top-leads",
                companies,
                max_leads,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
            )
            selected.assign(select_out)
            thread.handle_any_failure(
                select_out, _on_error_notify_and_continue(run_id, "select-top-leads")
            )

            catalog_out = thread.execute(
                "fetch-ioet-skills-catalog",
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
            )
            catalog_ref.assign(catalog_out)
            thread.handle_any_failure(
                catalog_out, _on_error_notify_and_continue(run_id, "fetch-ioet-skills-catalog")
            )

            spawned = thread.spawn_thread_for_each(
                selected,
                _enrich_one_company,
                "enrich-lead",
                input={
                    "enrich-dry-run": dry_run,
                    "enrich-icp-version": icp_version,
                    "enrich-campaign-id": campaign_id,
                    "enrich-catalog-ref": catalog_ref,
                    "enrich-icp-ref": icp_ref,
                    "enrich-campaign-config": campaign_config,
                    "enrich-run-id": run_id,
                },
            )
            waited = thread.wait_for_threads(spawned)
            thread.handle_any_failure(waited, _on_error_notify_and_continue(run_id, "enrich-lead"))

            summary_out = thread.execute(
                "build-campaign-summary",
                campaign_id,
                selected,
                dry_run,
                run_id,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
            )
            notification.assign(summary_out)
            thread.handle_any_failure(
                summary_out, _on_error_notify_and_continue(run_id, "build-campaign-summary")
            )

            notify_out = thread.execute(
                "notify",
                notification,
                timeout_seconds=TASK_TIMEOUT_SECONDS,
                retries=TASK_RETRIES,
            )
            thread.handle_any_failure(notify_out, _on_error_notify_and_continue(run_id, "notify"))

            record_out = thread.execute(
                "record-campaign-run",
                run_id,
                notification,
                "completed",
                timeout_seconds=TASK_TIMEOUT_SECONDS,
            )
            thread.handle_any_failure(
                record_out, _on_error_notify_and_continue(run_id, "record-campaign-run")
            )

        wf.do_if(
            search_count.is_equal_to(0),
            _notify_empty_and_exit,
            _continue_after_search,
        )

    return (
        Workflow(PARENT_WF_NAME, leads_search_workflow)
        .with_task_timeout_seconds(TASK_TIMEOUT_SECONDS)
        .with_retry_policy(TASK_RETRIES, _retry_policy())
    )
