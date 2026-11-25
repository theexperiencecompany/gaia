"""The changes that carry one JSON value to the next, as wire 2 sends a change to an item or a timeline.

A change names a path from the root and what happens there, so a tool call's output landing
inside a long timeline is sent as that output, not as the timeline again.
"""

from pydantic import JsonValue

from shared.py.conversation_wire import ChangeOp, ItemChange

_Path = tuple[str | int, ...]


def changes_between(before: JsonValue, after: JsonValue, path: _Path = ()) -> list[ItemChange]:
    """Return the changes that turn before into after, in the order they apply."""
    if isinstance(before, dict) and isinstance(after, dict):
        return _dict_changes(before, after, path)
    if isinstance(before, list) and isinstance(after, list):
        return _list_changes(before, after, path)
    if _same_scalar(before, after):
        return []
    if isinstance(before, str) and isinstance(after, str) and before and after.startswith(before):
        return [ItemChange(op=ChangeOp.APPEND, path=path, value=after[len(before) :])]
    return [ItemChange(op=ChangeOp.SET, path=path, value=after)]


def _same_scalar(before: JsonValue, after: JsonValue) -> bool:
    # True == 1 in Python, and they are different JSON.
    return type(before) is type(after) and before == after


def _dict_changes(
    before: dict[str, JsonValue], after: dict[str, JsonValue], path: _Path
) -> list[ItemChange]:
    changes = [
        ItemChange(op=ChangeOp.REMOVE, path=(*path, key)) for key in before if key not in after
    ]
    for key, value in after.items():
        if key in before:
            changes.extend(changes_between(before[key], value, (*path, key)))
        else:
            changes.append(ItemChange(op=ChangeOp.SET, path=(*path, key), value=value))
    return changes


def _list_changes(before: list[JsonValue], after: list[JsonValue], path: _Path) -> list[ItemChange]:
    shared = min(len(before), len(after))
    changes = [
        change
        for index in range(shared)
        for change in changes_between(before[index], after[index], (*path, index))
    ]
    changes.extend(
        ItemChange(op=ChangeOp.SET, path=(*path, index), value=after[index])
        for index in range(shared, len(after))
    )
    changes.extend(
        ItemChange(op=ChangeOp.REMOVE, path=(*path, index))
        for index in range(len(before) - 1, shared - 1, -1)
    )
    return changes
