"""Read a delivery mode from data written before delivery modes existed.

Workflows, run configurables and trigger contexts once carried a boolean
notify flag instead of a delivery mode. Records, checkpoints and queued jobs
from that time still exist, so every reader maps the flag the same way here:
False ran silently; True, or no flag at all (the old default), pushed the result.
Kept free of app imports beyond the enum so light models can use it.
"""

from collections.abc import Mapping

from pydantic import TypeAdapter

from app.constants.workflows import WorkflowDelivery

#: The flag a workflow record stored.
LEGACY_WORKFLOW_NOTIFY_KEY = "notify_on_completion"
#: The flag a run's configurable and its trigger context carried.
LEGACY_RUN_NOTIFY_KEY = "workflow_notify_on_completion"

_FLAG = TypeAdapter(bool)


def delivery_from_legacy_flag(data: object, *, flag_key: str, delivery_key: str) -> object:
    """Fill delivery_key from the legacy flag at flag_key when the data carries no delivery.

    A before-validator's input, so anything that is not a mapping, or already
    has a delivery, passes through unchanged.
    """
    if not isinstance(data, Mapping) or delivery_key in data:
        return data
    notified = _FLAG.validate_python(data.get(flag_key, True))
    return {**data, delivery_key: WorkflowDelivery.NOW if notified else WorkflowDelivery.SILENT}
