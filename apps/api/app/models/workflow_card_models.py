"""The workflow cards' payloads: a draft the user confirms, and a workflow created without one."""

from app.constants.workflows import WorkflowDelivery
from app.models.trigger_gate_models import GateCondition
from app.models.workflow_models import TriggerType
from app.schemas.common import ResponseModel


class WorkflowDraftData(ResponseModel):
    """The workflow_draft card the user reviews before the workflow is created."""

    suggested_title: str
    suggested_description: str
    prompt: str
    trigger_type: TriggerType
    trigger_slug: str | None
    integration_ids: list[str]
    cron_expression: str | None
    runs_only_when: GateCondition | None
    direct_create: bool
    delivery: WorkflowDelivery
    #: Sent back on create, so whatever waited on the user setting it up is picked back up.
    draft_id: str


class WorkflowCreatedTriggerConfig(ResponseModel):
    """The trigger the created workflow runs on."""

    type: TriggerType
    cron_expression: str | None
    trigger_name: str | None
    enabled: bool
    timezone: str | None


class WorkflowCreatedData(ResponseModel):
    """The workflow_created card: a workflow created directly, with no draft to confirm."""

    id: str
    title: str
    description: str
    trigger_config: WorkflowCreatedTriggerConfig
    integration_ids: list[str]
    activated: bool
