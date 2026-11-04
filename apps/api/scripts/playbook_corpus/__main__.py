"""Capture prod write_playbook attempts as an anonymised CI corpus, replayed through the pick flow.

Two steps, so prod is only ever read::

    # in the prod backend container: a read-only find, written to a gzip file
    python -m scripts.playbook_corpus export --since 2026-09-01 --out /tmp/writes.json.gz

    # locally, after copying the file out: anonymise, translate, replay, write fixtures
    cd apps/api
    uv run --group backend python -m scripts.playbook_corpus build --source /tmp/writes.json.gz

build replaces tests/fixtures/playbook_writes/ wholesale and prints the verdict
counts. Review the diff before committing it: every fixture's expected verdict
is what the pick flow does today, and the corpus test holds it there.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import UTC, datetime
import gzip
import json
from pathlib import Path
import shutil
import sys

from bson import json_util
from pydantic import BaseModel, ConfigDict, Field
import pymongo

from app.config.oauth_config import OAUTH_INTEGRATIONS
from app.config.settings import settings
from app.db.mongodb.mongodb import MONGO_DATABASE_NAME
from app.models.workflow_execution_models import RecordedCall
from app.utils.json_args import decode_json_container

from .anonymise import Anonymiser
from .fixture import (
    AUTHOR_CHOICE_REFUSALS,
    CORPUS_DIR,
    CorpusAttempt,
    CorpusRun,
    OldOutcome,
    Verdict,
)
from .replay import numbered, replay
from .translate import translate

WRITE_TOOL = "write_playbook"


class _ExportedRun(BaseModel):
    """One execution as export writes it."""

    model_config = ConfigDict(extra="ignore")

    execution_id: str
    started_at: datetime
    trigger_type: str = "manual"
    trace: list[RecordedCall] = Field(default_factory=list)


class _WriteAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool = False


def export(since: datetime, out: Path) -> int:
    """Read every execution since `since` whose trace holds a write; find only, never a write."""
    client: pymongo.MongoClient[dict[str, object]] = pymongo.MongoClient(settings.MONGO_DB)
    runs = list(
        client[MONGO_DATABASE_NAME].workflow_executions.find(
            {"started_at": {"$gte": since}, "trace.tool_name": WRITE_TOOL},
            {"execution_id": 1, "started_at": 1, "trigger_type": 1, "trace": 1},
        )
    )
    with gzip.open(out, "wt") as handle:
        handle.write(json_util.dumps(runs))
    return len(runs)


def build(source: Path) -> Counter[str]:
    """Anonymise and translate every exported run, replay each attempt, write the fixtures."""
    with gzip.open(source, "rt") as handle:
        raw = json_util.loads(handle.read())
    runs = [_ExportedRun.model_validate(item) for item in raw]
    names = {call.tool_name for run in runs for call in run.trace}
    integration_ids = {integration.id for integration in OAUTH_INTEGRATIONS}
    anonymiser = Anonymiser.fresh(kept=names | integration_ids | _step_ids(runs))
    tally: Counter[str] = Counter()
    # Always the corpus directory, never a path from the command line: build deletes what is there.
    out = CORPUS_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for run in sorted(runs, key=lambda item: item.started_at):
        fixture = asyncio.run(_fixture(run, anonymiser))
        for attempt in fixture.attempts:
            tally[_tally_key(attempt)] += 1
        (out / f"{fixture.run}.json").write_text(
            fixture.model_dump_json(indent=1, exclude_defaults=True) + "\n"
        )
    return tally


class _StepId(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: object = None
    steps: object = None


def _step_ids(runs: list[_ExportedRun]) -> set[str]:
    """The ids authors gave their steps: labels a $steps token names, kept so both still agree."""
    found: set[str] = set()
    pending = [
        decode_json_container(call.args.get("steps"))
        for run in runs
        for call in run.trace
        if call.tool_name == WRITE_TOOL
    ]
    while pending:
        node = pending.pop()
        if isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, dict):
            step = _StepId.model_validate(node)
            if isinstance(step.id, str):
                found.add(step.id)
            pending.append(step.steps)
    return found


async def _fixture(run: _ExportedRun, anonymiser: Anonymiser) -> CorpusRun:
    trace = [anonymiser.call(call) for call in run.trace]
    pickable = [entry.call for entry in numbered(trace, len(trace))]
    attempts: list[CorpusAttempt] = []
    for position, call in enumerate(trace):
        if call.tool_name != WRITE_TOOL:
            continue
        before = trace[:position]
        record_len = len(numbered(before, len(before)))
        record = numbered(pickable, record_len)
        translation = translate(call.args, record, frozenset())
        old = OldOutcome.ACCEPTED if _accepted(call) else OldOutcome.REFUSED
        written = {key: decode_json_container(value) for key, value in call.args.items()}
        if translation.unmappable is not None:
            attempts.append(
                CorpusAttempt(
                    position=position,
                    record_len=record_len,
                    written=written,
                    old_outcome=old,
                    unmappable=translation.unmappable,
                    unmappable_detail=translation.detail,
                    expected=Verdict.UNMAPPABLE,
                )
            )
            continue
        outcome = await replay(
            str(call.args.get("description") or ""),
            translation.picks,
            str(call.args.get("result_brief") or ""),
            record,
        )
        attempts.append(
            CorpusAttempt(
                position=position,
                record_len=record_len,
                written=written,
                old_outcome=old,
                picks=translation.picks,
                dropped=translation.dropped,
                expected=Verdict.REFUSED if outcome.issues else Verdict.ACCEPTED,
                refusals=outcome.refusals,
            )
        )
    return CorpusRun(
        run=anonymiser.name_of_run(run.execution_id),
        captured_from=run.started_at.date(),
        trigger_type=run.trigger_type,
        record=_needed(pickable, attempts),
        attempts=attempts,
    )


def _needed(pickable: list[RecordedCall], attempts: list[CorpusAttempt]) -> list[RecordedCall]:
    """The record, with args and results kept only on calls some attempt picked."""
    picked = {pick.call for attempt in attempts for pick in attempt.picks or []}
    longest = max((attempt.record_len for attempt in attempts), default=0)
    return [
        call if number in picked else RecordedCall(tool_name=call.tool_name)
        for number, call in enumerate(pickable[:longest], start=1)
    ]


def _accepted(call: RecordedCall) -> bool:
    try:
        return _WriteAnswer.model_validate_json(call.result_digest).success
    except ValueError:
        return False


def _tally_key(attempt: CorpusAttempt) -> str:
    if attempt.expected is Verdict.UNMAPPABLE and attempt.unmappable is not None:
        return f"unmappable:{attempt.unmappable.value}"
    if attempt.expected is Verdict.REFUSED:
        kinds = ",".join(kind.value for kind in attempt.refusals)
        choice = all(kind in AUTHOR_CHOICE_REFUSALS for kind in attempt.refusals)
        return f"refused:{kinds}{'' if choice else ' (NOT AN AUTHOR CHOICE)'}"
    return attempt.expected.value


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.playbook_corpus")
    commands = parser.add_subparsers(dest="command", required=True)
    exporting = commands.add_parser("export", help="read prod (find only) into a gzip file")
    exporting.add_argument("--since", required=True, type=datetime.fromisoformat)
    exporting.add_argument("--out", required=True, type=Path)
    building = commands.add_parser("build", help="anonymise, replay and write the fixtures")
    building.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "export":
        since = args.since if args.since.tzinfo else args.since.replace(tzinfo=UTC)
        print(f"exported {export(since, args.out)} runs to {args.out}")
        return 0
    tally = build(args.source)
    print(json.dumps(dict(sorted(tally.items(), key=lambda item: -item[1])), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
