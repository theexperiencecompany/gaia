"""Audit the stored data that reads a hooked Composio tool's output; --apply resets its learned shapes.

A tool with a GAIA after-hook now returns {data, successful, error} instead of
the bare reshaped data, so a stored path into its output needs a leading
``data.``. This lists every playbook placeholder ($steps.<id> / $last_run.<TOOL>)
that reads such an output, and with --apply deletes the tools' observed output
shapes so they are relearned in the new form. Playbooks are only reported.

    cd apps/api && uv run python scripts/migrate_hooked_tool_envelope.py [--apply]
"""

import asyncio
from collections.abc import Iterator, Mapping
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.constants.execute import EXECUTE_TOOL_NAME
from app.db.mongodb.collections import get_async_collection
from app.services.workflow.playbook.placeholders import placeholder_tokens
from app.utils.composio_hooks import hook_registry

STEPS_ROOT = "steps"
LAST_RUN_ROOT = "last_run"


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


def stale_references(playbook: Mapping[str, object], hooked_tools: frozenset[str]) -> list[str]:
    """Every placeholder in a playbook that reads the output of a hooked tool."""
    calls = list(_calls(playbook.get("steps")))
    hooked_ids = {step.get("id") for step in calls if _called_tool(step) in hooked_tools}
    hooked_ids.discard("")
    hooked_ids.discard(None)
    found: list[str] = []
    for step in calls:
        for match in placeholder_tokens([step.get("args"), step.get("for_each")]):
            head = match.group("path").lstrip(".").split(".", 1)[0]
            root = match.group("root")
            if (root == STEPS_ROOT and head in hooked_ids) or (
                root == LAST_RUN_ROOT and head in hooked_tools
            ):
                found.append(match.group(0))
    return found


async def main(apply: bool) -> None:
    hooked_tools = frozenset(hook_registry.after_hook_tools)
    print(f"{len(hooked_tools)} hooked tools: {', '.join(sorted(hooked_tools))}")

    affected = 0
    async for playbook in get_async_collection("playbooks").find({}):
        references = stale_references(playbook, hooked_tools)
        if references:
            affected += 1
            print(f"  playbook {playbook.get('_id')}: {', '.join(references)}")
    print(f"playbooks reading a hooked tool's output: {affected}")

    shapes = get_async_collection("tool_output_shapes")
    shape_filter = {"tool_name": {"$in": sorted(hooked_tools)}}
    print(f"observed shapes to reset: {await shapes.count_documents(shape_filter)}")
    if apply:
        deleted = await shapes.delete_many(shape_filter)
        print(f"deleted {deleted.deleted_count} observed shapes")
    else:
        print("dry run: pass --apply to delete them")


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
