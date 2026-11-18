"""What GAIA itself logged as going wrong during the run, flattened out of its wide events."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path

from briefsim.oracle.truth import parse_instant

#: Logged because the sim gives GAIA no Dodo API key; nothing in the brief path calls Dodo.
_SIM_CONFIG_NOISE = frozenset({"[PAYMENT] Failed to instantiate dodo payments"})
_LOGS = ("api", "worker")


@dataclass(frozen=True)
class LoggedError:
    at: datetime
    source: str
    message: str
    error: str


def _entries(event: dict[str, object]) -> Iterator[tuple[str, str]]:
    """Yield (message, error) for an ERROR event and for every error a wide event collected."""
    nested = event.get("errors")
    if isinstance(nested, list):
        for entry in nested:
            if isinstance(entry, dict):
                yield (
                    str(entry.get("msg") or ""),
                    str(entry.get("error") or entry.get("label") or ""),
                )
    elif event.get("level") == "ERROR":
        yield str(event.get("message") or ""), str(event.get("error") or "")


def logged_errors(out: Path, since: datetime) -> list[LoggedError]:
    """Return every error GAIA logged from since on (boot noise before the persona signs up is not the brief's)."""
    found: list[LoggedError] = []
    for source in _LOGS:
        path = out / "logs" / f"{source}.log"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if not line.startswith("{"):
                continue
            event = json.loads(line)
            at = parse_instant(str(event["time"]))
            if at < since or event.get("level") not in {"ERROR", "WARNING"}:
                continue
            for message, error in _entries(event):
                if message and message not in _SIM_CONFIG_NOISE:
                    found.append(LoggedError(at, source, message, error))
    return sorted(set(found), key=lambda e: e.at)
