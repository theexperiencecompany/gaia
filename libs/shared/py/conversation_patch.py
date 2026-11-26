"""Apply the changes a wire 2 conversation stream sends to the JSON a reader holds.

The Python twin of libs/shared/ts/src/conversation/patch.ts: voice applies a screen_patch
with it, and the API's tests check the patches it writes against it.
"""

from collections.abc import Iterable, Sequence

from pydantic import JsonValue

from shared.py.conversation_wire import ChangeOp, ItemChange


class ChangeNotApplicable(Exception):
    """A change names a path the held JSON does not have: the holder's copy is not the one it was made against."""


def with_changes(document: JsonValue, changes: Iterable[ItemChange]) -> JsonValue:
    """Return document with changes applied in order; containers off a changed path are shared, not copied.

    Raises ChangeNotApplicable when a path does not exist in document.
    """
    for change in changes:
        document = _changed(document, change, change.path)
    return document


def _changed(node: JsonValue, change: ItemChange, rest: Sequence[str | int]) -> JsonValue:
    if not rest:
        return _at_target(node, change)
    key, deeper = rest[0], rest[1:]
    if isinstance(node, dict) and isinstance(key, str):
        return _in_dict(node, key, change, deeper)
    if isinstance(node, list) and isinstance(key, int):
        return _in_list(node, key, change, deeper)
    raise ChangeNotApplicable(f"{change.path}: {key!r} does not index a {type(node).__name__}")


def _at_target(node: JsonValue, change: ItemChange) -> JsonValue:
    if change.op is ChangeOp.SET:
        return change.value
    if change.op is ChangeOp.APPEND and isinstance(node, str) and isinstance(change.value, str):
        return node + change.value
    raise ChangeNotApplicable(f"{change.path}: cannot {change.op.value} a {type(node).__name__}")


def _in_dict(
    node: dict[str, JsonValue], key: str, change: ItemChange, deeper: Sequence[str | int]
) -> JsonValue:
    if not deeper and change.op is ChangeOp.REMOVE:
        return {held: value for held, value in node.items() if held != key}
    if not deeper and change.op is ChangeOp.SET:
        return {**node, key: change.value}
    if key not in node:
        raise ChangeNotApplicable(f"{change.path}: no key {key!r}")
    return {**node, key: _changed(node[key], change, deeper)}


def _in_list(
    node: list[JsonValue], index: int, change: ItemChange, deeper: Sequence[str | int]
) -> JsonValue:
    if not deeper and change.op is ChangeOp.REMOVE and index == len(node) - 1:
        return node[:-1]
    if not deeper and change.op is ChangeOp.SET and index == len(node):
        return [*node, change.value]
    if not 0 <= index < len(node) or (not deeper and change.op is ChangeOp.REMOVE):
        raise ChangeNotApplicable(f"{change.path}: no index {index} in a list of {len(node)}")
    return [*node[:index], _changed(node[index], change, deeper), *node[index + 1 :]]
