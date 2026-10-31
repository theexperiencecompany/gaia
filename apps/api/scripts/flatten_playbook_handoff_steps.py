"""Flatten every stored playbook's ``handoff`` steps into top-level ``execute`` steps.

The playbook grammar no longer has a handoff step: integrations are reached by
the executor itself, and their tools run through ``execute``, which resolves
Composio, MCP and custom MCP tools per user at call time. Each handoff child
becomes one top-level step in its original position, keeping its id, its
``for_each``/``max_items`` and its args (which become execute's ``data``). A
child that already called ``execute`` is kept as it is.

Dry run by default: prints how many playbooks change, a sample diff, and any
reference the flattening cannot carry over. ``--apply`` first copies every
affected document to a timestamped backup collection, then writes. Every
flattened body is validated against the current model before anything is
written; one that does not validate aborts the run.

Run before deploying the code that removed the handoff step, which refuses a
stored handoff step on read.

    cd apps/api && uv run python scripts/flatten_playbook_handoff_steps.py [--apply]
"""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import difflib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from pydantic import ValidationError

from app.constants.execute import EXECUTE_TOOL_NAME
from app.db.mongodb.collections import get_async_collection
from app.db.mongodb.mongodb import RawDocument
from app.models.playbook_models import PlaybookBody
from app.services.workflow.playbook.placeholders import placeholder_tokens

PLAYBOOKS_COLLECTION = "playbooks"
BACKUP_COLLECTION_PREFIX = "playbooks_backup_handoff_"
HANDOFF_KEY = "handoff"
#: Keys a stored step may carry from the old single step model, null when unset.
_LEGACY_NULL_KEYS = ("handoff", "steps", "for_each", "max_items")
_LAST_RUN_ROOT = "last_run"
_STEPS_ROOT = "steps"


@dataclass
class Flattened:
    """One playbook's new steps, and the references the old shape carried that no longer resolve."""

    steps: list[dict[str, object]]
    #: ``$steps.<handoff id>...`` tokens: a handoff recorded no result, so these never resolved.
    handoff_references: list[str] = field(default_factory=list)
    #: ``$last_run.<tool>...`` tokens for a flattened child: a replay records an
    #: execute step under ``execute``, so these stop resolving after the next replay.
    last_run_references: list[str] = field(default_factory=list)


def _is_handoff(step: Mapping[str, object]) -> bool:
    return step.get(HANDOFF_KEY) is not None


def _without_legacy_nulls(step: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in step.items()
        if not (key in _LEGACY_NULL_KEYS and (value is None or value == []))
    }


def _as_execute_step(child: Mapping[str, object]) -> dict[str, object]:
    """One handoff child as the top-level execute call the executor makes for the same tool."""
    step = _without_legacy_nulls(child)
    tool_name = step.get("tool")
    if not isinstance(tool_name, str) or not tool_name:
        raise ValueError(f"a handoff child names no tool: {json.dumps(child, default=str)}")
    if tool_name == EXECUTE_TOOL_NAME:
        return step
    args = step.get("args")
    step["tool"] = EXECUTE_TOOL_NAME
    step["args"] = {
        "task_description": f"Run {tool_name}",
        "tool_name": tool_name,
        "data": args if isinstance(args, Mapping) else {},
    }
    return step


def flatten_steps(steps: Sequence[Mapping[str, object]]) -> Flattened:
    """The playbook's steps with every handoff replaced by its children, in order."""
    handoff_ids = {
        str(step["id"]) for step in steps if _is_handoff(step) and isinstance(step.get("id"), str)
    }
    handoff_ids.discard("")
    child_tools: set[str] = set()
    flattened: list[dict[str, object]] = []
    for step in steps:
        if not _is_handoff(step):
            flattened.append(dict(step))
            continue
        children = step.get("steps")
        if not isinstance(children, list) or not children:
            raise ValueError(f"handoff step carries no children: {json.dumps(step, default=str)}")
        for child in children:
            if not isinstance(child, Mapping):
                raise ValueError(f"handoff child is not a mapping: {child!r}")
            if isinstance(child.get("tool"), str):
                child_tools.add(str(child["tool"]))
            flattened.append(_as_execute_step(child))

    result = Flattened(steps=flattened)
    for step in flattened:
        for match in placeholder_tokens([step.get("args"), step.get("for_each")]):
            head = match.group("path").lstrip(".").partition(".")[0]
            if match.group("root") == _STEPS_ROOT and head in handoff_ids:
                result.handoff_references.append(match.group(0))
            elif match.group("root") == _LAST_RUN_ROOT and head in child_tools:
                result.last_run_references.append(match.group(0))
    return result


def _validated(doc: RawDocument, steps: list[dict[str, object]]) -> None:
    """Refuse a flattened body the current model cannot read: writing it would break the playbook."""
    try:
        PlaybookBody.model_validate(
            {
                "description": doc.get("description"),
                "steps": steps,
                "result_brief": doc.get("result_brief"),
            }
        )
    except ValidationError as error:
        raise SystemExit(
            f"playbook {doc.get('playbook_id')} does not validate after flattening, nothing "
            f"was written:\n{error}"
        ) from error


def _diff(before: object, after: object) -> str:
    old = json.dumps(before, indent=2, default=str).splitlines()
    new = json.dumps(after, indent=2, default=str).splitlines()
    return "\n".join(difflib.unified_diff(old, new, "before", "after", lineterm=""))


async def main(apply: bool) -> None:
    playbooks = get_async_collection(PLAYBOOKS_COLLECTION)
    affected: list[tuple[RawDocument, Flattened]] = []
    total = await playbooks.count_documents({})
    async for doc in playbooks.find({"steps": {"$elemMatch": {HANDOFF_KEY: {"$type": "string"}}}}):
        flattened = flatten_steps(doc["steps"])
        _validated(doc, flattened.steps)
        affected.append((doc, flattened))

    print(f"playbooks: {total}, with handoff steps to flatten: {len(affected)}")
    for doc, flattened in affected:
        if flattened.handoff_references:
            print(
                f"  UNRESOLVED playbook {doc.get('playbook_id')}: "
                f"{', '.join(flattened.handoff_references)} addressed a handoff, which never "
                "recorded a result"
            )
        if flattened.last_run_references:
            print(
                f"  CHECK      playbook {doc.get('playbook_id')}: "
                f"{', '.join(flattened.last_run_references)} reads a flattened child's last "
                "run; replays record it under execute"
            )
    if affected:
        sample_doc, sample = affected[0]
        print(f"sample, playbook {sample_doc.get('playbook_id')}:")
        print(_diff(sample_doc.get("steps"), sample.steps))

    if not apply:
        print("dry run: pass --apply to back up and write")
        return
    if not affected:
        return

    backup_name = f"{BACKUP_COLLECTION_PREFIX}{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    backup = get_async_collection(backup_name)
    inserted = await backup.insert_many([doc for doc, _ in affected])
    if len(inserted.inserted_ids) != len(affected):
        raise SystemExit(
            f"backup wrote {len(inserted.inserted_ids)} of {len(affected)} documents to "
            f"{backup_name}; nothing was flattened"
        )
    print(f"backed up {len(affected)} playbooks to {backup_name}")

    written = 0
    for doc, flattened in affected:
        # Matched on the steps read above, so a playbook rewritten since is left alone.
        result = await playbooks.update_one(
            {"_id": doc["_id"], "steps": doc["steps"]},
            {
                "$set": {"steps": flattened.steps, "updated_at": datetime.now(UTC)},
                "$inc": {"revision": 1},
            },
        )
        if result.modified_count == 1:
            written += 1
        else:
            print(f"  SKIPPED playbook {doc.get('playbook_id')}: rewritten since it was read")
    print(f"flattened {written} of {len(affected)} playbooks")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
