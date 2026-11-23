"""Signal memory: pair today's signals with what earlier briefs saw and said about them."""

from collections.abc import Sequence
from datetime import datetime

from app.db.repositories.signal_memory import signal_memory_repository
from app.models.scout_models import RememberedSignal, Signal


async def remember(
    user_id: str, signals: Sequence[Signal], now: datetime
) -> list[RememberedSignal]:
    """Return each signal with its memory as it stood before today, then record today's sighting."""
    known = {
        (memory.integration_id, memory.external_id): memory
        for memory in await signal_memory_repository.find_for(user_id, signals)
    }
    remembered: list[RememberedSignal] = []
    for signal in signals:
        memory = known.get((signal.integration_id, signal.external_id))
        moved = memory is not None and memory.last_state not in (None, signal.state)
        remembered.append(
            RememberedSignal(
                signal=signal,
                memory=memory,
                previous_state=memory.last_state if memory is not None and moved else None,
            )
        )
    await signal_memory_repository.record_seen(user_id, signals, now)
    return remembered
