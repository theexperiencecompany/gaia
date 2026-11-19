"""Move every workflow still on a retired trigger type to its successor, off until its owner turns it on.

The "email" and "calendar" triggers were retired on 2026-01-19 (#412) for integration
triggers that Composio delivers (gmail_new_message, calendar_event_created). A record
still on one has not fired since, having no Composio subscription, and fails
WorkflowDocument validation wherever it is read. Each moves to its successor, left
unregistered; one that was on is deactivated as TRIGGER_RETIRED, so switching it back
on registers the trigger the normal way. A type that is neither current nor retired
stops the run: what it should become is a decision, not a default.

    cd apps/api && uv run python -m scripts.retire_legacy_triggers [--apply]
"""

import asyncio
from collections.abc import Mapping
from types import MappingProxyType

from app.db.repositories.workflows import workflow_repository
from app.models.scheduler_models import DeactivationReason
from app.models.trigger_configs import (
    CalendarEventCreatedConfig,
    GmailNewMessageConfig,
    TriggerConfigData,
)
from scripts._cli import apply_requested

#: Each retired trigger type and the integration trigger that replaced it.
RETIRED_TRIGGER_SUCCESSORS: Mapping[str, TriggerConfigData] = MappingProxyType(
    {"email": GmailNewMessageConfig(), "calendar": CalendarEventCreatedConfig()}
)


class UnknownTriggerTypeError(Exception):
    """A stored trigger type is neither a current TriggerType nor a retired one with a successor."""


async def migrate(apply: bool) -> int:
    """Move every workflow on a retired trigger type to its successor; return how many."""
    mode = "APPLY" if apply else "DRY RUN"
    rows = await workflow_repository.find_on_unknown_trigger_types()
    unknown = sorted({row.trigger_type for row in rows} - RETIRED_TRIGGER_SUCCESSORS.keys())
    if unknown:
        raise UnknownTriggerTypeError(
            f"workflows carry trigger types with no successor: {unknown}; decide what each becomes"
        )
    print(f"[{mode}] Moving {len(rows)} workflows off retired trigger types\n")
    for row in rows:
        successor = RETIRED_TRIGGER_SUCCESSORS[row.trigger_type]
        reason = DeactivationReason.TRIGGER_RETIRED if row.activated else None
        switched = ", switched off" if reason else ""
        print(
            f"  {row.id} (user {row.user_id}): {row.trigger_type} -> {successor.trigger_name}{switched}"
        )
        if apply:
            await workflow_repository.move_to_successor_trigger(
                row.id, row.trigger_type, successor, reason=reason
            )
    print(f"\n[{mode}] Done. workflows={len(rows)}")
    if not apply:
        print("Re-run with --apply to write these changes.")
    return len(rows)


if __name__ == "__main__":
    asyncio.run(migrate(apply=apply_requested(__doc__)))
