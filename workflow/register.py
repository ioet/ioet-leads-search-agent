"""Register TaskDefs and WfSpecs with the LittleHorse Kernel."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import grpc
from littlehorse import create_task_def, create_workflow_spec
from littlehorse.config import LHConfig
from littlehorse.model.object_id_pb2 import TaskDefId
from littlehorse.model.service_pb2 import DeleteTaskDefRequest

from workflow.workers import TASK_HANDLERS, TASK_NAMES
from workflow.workflows.enrich_publish import CHILD_WF_NAME, get_workflow as get_child_workflow
from workflow.workflows.fire_schedule import (
    FIRE_SCHEDULE_WF_NAME,
    get_workflow as get_fire_schedule_workflow,
)
from workflow.workflows.leads_search import PARENT_WF_NAME, get_workflow as get_parent_workflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _put_task_def(task, name: str, config: LHConfig) -> None:
    # TaskDef schemas are immutable; delete + recreate so worker signatures stay in sync.
    try:
        config.stub().DeleteTaskDef(DeleteTaskDefRequest(id=TaskDefId(name=name)))
        logger.info("Deleted existing TaskDef %s", name)
    except grpc.RpcError as e:
        if e.code() != grpc.StatusCode.NOT_FOUND:
            logger.warning("Could not delete TaskDef %s: %s", name, e.details())

    create_task_def(task, name, config)
    logger.info("Created TaskDef %s", name)


def main() -> None:
    config = LHConfig()
    child_wf = get_child_workflow()
    parent_wf = get_parent_workflow()
    fire_wf = get_fire_schedule_workflow()

    for name in TASK_NAMES:
        _put_task_def(TASK_HANDLERS[name], name, config)

    # Child first — parent references it via run_wf().
    create_workflow_spec(child_wf, config)
    create_workflow_spec(parent_wf, config)
    create_workflow_spec(fire_wf, config)
    logger.info(
        "Registered WfSpecs: %s + %s + %s (%d TaskDefs)",
        PARENT_WF_NAME,
        CHILD_WF_NAME,
        FIRE_SCHEDULE_WF_NAME,
        len(TASK_NAMES),
    )


if __name__ == "__main__":
    main()
