"""Put this process on the brief simulator's clock when BRIEF_SIM_CLOCK names one.

Python imports sitecustomize at startup from PYTHONPATH, so the API, the ARQ worker,
the fake world and the driver all read one simulated "now". The clock file holds the
instant of the last jump; time ticks in real seconds from it until the next jump. Each
process registers its pid in the clock's directory and acks every jump it has applied.
"""

from datetime import datetime
import os
from pathlib import Path
import threading
import time

import time_machine

_CLOCK = os.environ.get("BRIEF_SIM_CLOCK")
_POLL_S = 0.02


def _read(path: Path) -> str:
    return path.read_text().strip()


def _follow(path: Path, acks: Path, traveller: time_machine.Traveller, applied: str) -> None:
    while True:
        time.sleep(_POLL_S)
        try:
            instant = _read(path)
        except FileNotFoundError:
            continue
        if instant and instant != applied:
            traveller.move_to(datetime.fromisoformat(instant))
            applied = instant
            acks.write_text(applied)


def _start(clock: Path) -> None:
    instant = _read(clock)
    traveller = time_machine.travel(datetime.fromisoformat(instant), tick=True).start()
    acks = clock.parent / "pids" / str(os.getpid())
    acks.parent.mkdir(exist_ok=True)
    acks.write_text(instant)
    threading.Thread(
        target=_follow, args=(clock, acks, traveller, instant), daemon=True, name="brief-sim-clock"
    ).start()


if _CLOCK:
    _start(Path(_CLOCK))
