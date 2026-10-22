"""Judge every replayed signal, across all apps, in one cheap call: keep it or drop it, and how much it matters.

A replay reads every row its frozen calls return. Which rows need the user is decided
here by each scout's learned criteria and what the brief remembers of each item, so a
routine row is dropped while a person waiting on the user stays important. Signals a
learn run reported today were already judged by it and pass through untouched.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from app.agents.llm.client import ainvoke_structured, metered_config
from app.agents.prompts.scout_prompts import SIGNAL_JUDGE_PROMPT
from app.constants.scouts import SIGNAL_JUDGE_LABEL
from app.models.scout_models import (
    RememberedSignal,
    ScoutOutcome,
    ScoutResult,
    SignalImportance,
)
from app.services.briefing.scouts.facts import memory_note
from app.utils.errors import AppError


class SignalVerdict(BaseModel):
    """The judge's call on one numbered item."""

    number: int
    keep: bool
    importance: SignalImportance
    why: str = Field(description="One short line, from the item itself")


class SignalVerdicts(BaseModel):
    """One verdict per numbered item."""

    verdicts: list[SignalVerdict]


def _item_line(number: int, item: RememberedSignal, now: datetime) -> str:
    signal = item.signal
    parts = [f"{number}. [{signal.app}] {signal.kind}: {signal.title}"]
    if signal.state:
        parts.append(f"state: {signal.state}")
    if signal.due_at is not None:
        parts.append(f"due {signal.due_at.date().isoformat()}")
    if signal.people:
        parts.append(f"with {', '.join(signal.people)}")
    parts.append(memory_note(item, now))
    return " | ".join(parts)


def _verdicts_by_number(verdicts: SignalVerdicts, count: int) -> dict[int, SignalVerdict]:
    """Index the verdicts; raise unless every item got exactly one."""
    by_number = {verdict.number: verdict for verdict in verdicts.verdicts}
    if len(verdicts.verdicts) != count or set(by_number) != set(range(1, count + 1)):
        raise AppError(
            message="the signal judge did not answer every item once",
            why=f"{count} item(s) asked, verdicts for {sorted(by_number)}",
            fix="the brief goes without today's replayed app items; the next brief judges again",
        )
    return by_number


async def judge_replayed(
    user_id: str,
    results: Sequence[ScoutResult],
    remembered: Sequence[RememberedSignal],
    now: datetime,
    timezone: str,
) -> list[RememberedSignal]:
    """Return remembered with each replayed signal kept or dropped, and its importance judged.

    Raises AppError when the judge's answer does not cover every replayed item exactly once.
    """
    criteria: Mapping[str, str] = {
        r.integration_id: r.criteria
        for r in results
        if r.outcome is ScoutOutcome.REPLAYED and r.criteria
    }
    positions = [at for at, item in enumerate(remembered) if item.signal.integration_id in criteria]
    if not positions:
        return list(remembered)
    apps = {remembered[at].signal.integration_id: remembered[at].signal.app for at in positions}
    prompt = SIGNAL_JUDGE_PROMPT.format(
        today=now.date().isoformat(),
        timezone=timezone,
        criteria="\n".join(f"- {apps[iid]}: {criteria[iid]}" for iid in apps),
        items="\n".join(
            _item_line(number, remembered[at], now) for number, at in enumerate(positions, start=1)
        ),
    )
    verdicts = _verdicts_by_number(
        await ainvoke_structured(
            SignalVerdicts, prompt, label=SIGNAL_JUDGE_LABEL, config=metered_config(user_id)
        ),
        len(positions),
    )
    verdict_at = {at: verdicts[number] for number, at in enumerate(positions, start=1)}
    kept: list[RememberedSignal] = []
    for at, item in enumerate(remembered):
        verdict = verdict_at.get(at)
        if verdict is None:
            kept.append(item)
        elif verdict.keep:
            signal = item.signal.model_copy(
                update={"importance": verdict.importance, "why": verdict.why}
            )
            kept.append(item.model_copy(update={"signal": signal}))
    return kept
