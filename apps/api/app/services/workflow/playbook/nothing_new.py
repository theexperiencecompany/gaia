"""Whether a playbook's opening read found nothing new, so the run can stop before any model call.

Only a read can say so: a playbook that opens with a write has already done its
work by the time it could look. Nothing new is either an empty result, or a
list whose elements carry exactly the ids the last delivered fire's replay of
the same read returned, as the same account. Only a delivered (successful) run
is a baseline: a failed one never told the user, so the next fire runs. The ids
are fingerprinted from the whole result (RecordedCall.item_fingerprint), never
read back from a bounded digest that may have shed elements. Elements without
an id never count as the same.
"""

from collections.abc import Mapping, Sequence
import hashlib

from pydantic import BaseModel, ConfigDict

from app.agents.tools.execute.unwrap import execute_call_account, unwrap_execute_call
from app.models.playbook_models import is_read_call
from app.models.workflow_execution_models import RecordedCall, carries_no_data, largest_list


class _Identified(BaseModel):
    """The one field of a listed element that says which element it is."""

    model_config = ConfigDict(extra="ignore")

    id: str | int | None = None


def is_opening_read(tool_name: str, args: Mapping[str, object]) -> bool:
    """Whether a call, seen through execute, reads rather than changes something."""
    real_name, _ = unwrap_execute_call(tool_name, dict(args))
    return is_read_call(real_name)


def nothing_new(
    tool_name: str,
    args: Mapping[str, object],
    value: object,
    previous: Sequence[RecordedCall],
) -> str | None:
    """Return why an opening read found nothing new since the previous fire, or None."""
    real_name, _ = unwrap_execute_call(tool_name, dict(args))
    if carries_no_data(value):
        return f"{real_name} returned nothing"
    ids = item_ids(value)
    if ids is None:
        return None
    account = execute_call_account(tool_name, dict(args))
    for call in previous:
        name, _ = unwrap_execute_call(call.tool_name, call.args)
        if (
            name == real_name
            and call.replayed
            and execute_call_account(call.tool_name, call.args) == account
        ):
            if call.item_fingerprint == item_fingerprint(ids):
                return f"{real_name} returned the same {len(ids)} items as the last run"
            return None
    return None


def item_ids(value: object) -> frozenset[str] | None:
    """Return the ids of the largest list's elements, or None when any element has none."""
    items = largest_list(value)
    if not items:
        return None
    ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            return None
        identified = _Identified.model_validate(item).id
        if identified in (None, ""):
            return None
        ids.add(str(identified))
    return frozenset(ids)


def item_fingerprint(ids: frozenset[str]) -> str:
    """Return a fixed-size, order-free identity for a set of ids: its count and a hash of the sorted ids."""
    digest = hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()
    return f"{len(ids)}:{digest}"
