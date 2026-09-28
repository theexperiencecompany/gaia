"""Audit the stored data that reads a hooked Composio tool's output; --apply resets its learned shapes.

A tool with a GAIA after-hook now returns {data, successful, error} instead of
the bare reshaped data, so a stored path into its output needs a leading
``data.``. This lists every playbook placeholder ($steps.<id> / $last_run.<TOOL>)
that reads such an output — stale ones, and ``data.`` ones a person must check —
and with --apply deletes the tools' observed output shapes so they are relearned
in the new form. Playbooks are only reported.

    cd apps/api && uv run python scripts/migrate_hooked_tool_envelope.py [--apply]
"""

import asyncio
from collections.abc import Iterator, Mapping
from pathlib import Path
import sys
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.execute import EXECUTE_TOOL_NAME
from app.db.mongodb.collections import get_async_collection
from app.models.integrations.composio_hooks import ComposioToolResponse
from app.services.workflow.playbook.placeholders import placeholder_tokens
from app.utils.composio_hooks import hook_registry

STEPS_ROOT = "steps"
LAST_RUN_ROOT = "last_run"
# A path whose next segment is one of these already reads through the envelope.
ENVELOPE_KEYS = frozenset(ComposioToolResponse.model_fields)
DATA_KEY = "data"


class References(NamedTuple):
    """A playbook's placeholders into hooked tools' outputs, by what they need."""

    #: Read the old shape; each needs a leading data.
    stale: list[str]
    #: Start with data.: already migrated, or an old read of a raw data field — a person decides.
    ambiguous: list[str]


def _calls(steps: object) -> Iterator[Mapping[str, object]]:
    """Every call step of a playbook, including the children a handoff step ran."""
    if not isinstance(steps, list):
        return
    for step in steps:
        if isinstance(step, Mapping):
            yield step
            yield from _calls(step.get("steps"))


def _called_tool(step: Mapping[str, object]) -> object:
    args = step.get("args")
    if step.get("tool") == EXECUTE_TOOL_NAME and isinstance(args, Mapping):
        return args.get("tool_name")
    return step.get("tool")


def playbook_references(playbook: Mapping[str, object], hooked_tools: frozenset[str]) -> References:
    """Every placeholder in a playbook that reads a hooked tool's output, split by what it needs."""
    calls = list(_calls(playbook.get("steps")))
    hooked_ids = {step.get("id") for step in calls if _called_tool(step) in hooked_tools}
    hooked_ids.discard("")
    hooked_ids.discard(None)
    found = References(stale=[], ambiguous=[])
    for step in calls:
        for match in placeholder_tokens([step.get("args"), step.get("for_each")]):
            head, *rest = match.group("path").lstrip(".").split(".")
            root = match.group("root")
            reads_hooked = (root == STEPS_ROOT and head in hooked_ids) or (
                root == LAST_RUN_ROOT and head in hooked_tools
            )
            if not reads_hooked:
                continue
            if not rest or rest[0] not in ENVELOPE_KEYS:
                found.stale.append(match.group(0))
            elif rest[0] == DATA_KEY:
                found.ambiguous.append(match.group(0))
    return found


def hooked_tool_inventory() -> frozenset[str]:
    """Every tool whose output the envelope change reshaped; refuses when that cannot be listed by name."""
    if hook_registry.has_broad_after_hook:
        raise SystemExit(
            "an after-hook is scoped by toolkit or to every tool, so the tools whose output "
            "changed cannot be listed by name; scope that hook by tool, then rerun this audit"
        )
    return frozenset(hook_registry.after_hook_tools)


async def main(apply: bool) -> None:
    hooked = hooked_tool_inventory()
    print(f"{len(hooked)} hooked tools: {', '.join(sorted(hooked))}")

    stale = ambiguous = 0
    async for playbook in get_async_collection("playbooks").find({}):
        references = playbook_references(playbook, hooked)
        if references.stale:
            stale += 1
            print(f"  STALE   playbook {playbook.get('_id')}: {', '.join(references.stale)}")
        if references.ambiguous:
            ambiguous += 1
            print(f"  CHECK   playbook {playbook.get('_id')}: {', '.join(references.ambiguous)}")
    print(f"playbooks with stale paths (each needs a leading data.): {stale}")
    print(
        f"playbooks with data. paths to check by hand: {ambiguous} "
        "(fine if already migrated; needs a second data. only if it read a raw data field)"
    )

    shapes = get_async_collection("tool_output_shapes")
    shape_filter = {"tool_name": {"$in": sorted(hooked)}}
    print(f"observed shapes to reset: {await shapes.count_documents(shape_filter)}")
    if apply:
        deleted = await shapes.delete_many(shape_filter)
        print(f"deleted {deleted.deleted_count} observed shapes")
    else:
        print("dry run: pass --apply to delete them")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
