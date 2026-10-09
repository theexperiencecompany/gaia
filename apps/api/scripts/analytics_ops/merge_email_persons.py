"""Merge each email-keyed PostHog person into the person of the GAIA user who owns that email.

A merge is $merge_dangerously on the Mongo id with the email as alias, sent
through the live pipeline. The survivor's properties win a merge, so when the
email person is the older one its first-touch properties ($initial_* and
first_seen) are set on the survivor afterwards. Only an exact, case-folded,
unambiguous users.email match is merged; a person that already holds a Mongo
id is skipped, so a re-run merges nothing twice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from uuid import uuid4

from pymongo.database import Database

from shared.py.analytics import UserId, is_user_id

from .mongo import Document
from .posthog_api import REPO_ROOT, PostHogReader, Sender, hogql_complete

MERGE_EVENT = "$merge_dangerously"
FIRST_TOUCH_PREFIX = "$initial_"
FIRST_SEEN = "first_seen"
DEFAULT_SNAPSHOT_DIR = REPO_ROOT / ".agents" / "plans" / "posthog-backfill"
SNAPSHOT_MODE = 0o600

EMAIL_PERSONS_HOGQL = (
    "SELECT distinct_id, toString(person_id) FROM person_distinct_ids "
    "WHERE distinct_id LIKE '%@%' LIMIT {limit}"
)
PERSON_DISTINCT_IDS_HOGQL = (
    "SELECT distinct_id, toString(person_id) FROM person_distinct_ids "
    "WHERE has({persons}, toString(person_id)) LIMIT {limit}"
)
PERSONS_HOGQL = (
    "SELECT toString(id), toString(created_at), properties FROM persons "
    "WHERE has({persons}, toString(id)) LIMIT {limit}"
)
SURVIVOR_CREATED_HOGQL = (
    "SELECT distinct_id, toString(person.created_at) FROM person_distinct_ids "
    "WHERE has({ids}, distinct_id) LIMIT {limit}"
)


@dataclass(frozen=True)
class Merge:
    """One email person and the GAIA user it belongs to."""

    person_id: str
    distinct_ids: tuple[str, ...]
    created_at: str
    properties: dict[str, object]
    user_id: UserId

    @property
    def alias(self) -> str:
        """Return the email distinct_id the merge names; the others share its person."""
        return min(d for d in self.distinct_ids if "@" in d)

    def first_touch(self) -> dict[str, object]:
        """Return the person's first-touch properties."""
        return {
            key: value
            for key, value in self.properties.items()
            if key.startswith(FIRST_TOUCH_PREFIX) or key == FIRST_SEEN
        }


@dataclass(frozen=True)
class MergePlan:
    """Every email person, sorted into what the script may and may not do with it."""

    merges: list[Merge]
    already_merged: list[str]
    unmatched: list[str]
    ambiguous: list[str]
    # A merge moves every alias's activity, so one alias no user holds needs a human.
    unowned_aliases: list[str]
    # Users whose history sits on a person left unmerged, out of reach of a Mongo-id lookup.
    held_users: set[str]

    def summary(self) -> str:
        """Return the bucket counts."""
        return (
            f"{len(self.merges)} to merge, {len(self.already_merged)} already merged, "
            f"{len(self.unmatched)} with no GAIA user (not merged), "
            f"{len(self.ambiguous)} matching more than one user (not merged), "
            f"{len(self.unowned_aliases)} with an email no GAIA user holds (not merged)"
        )


def normalise_email(email: str) -> str:
    """Return the form two spellings of one address share: trimmed and case-folded."""
    return email.strip().casefold()


def users_by_email(users: Iterable[Document]) -> dict[str, set[str]]:
    """Map each normalised users.email to the ids holding it."""
    owners: defaultdict[str, set[str]] = defaultdict(set)
    for user in users:
        owners[normalise_email(str(user["email"]))].add(str(user["_id"]))
    return owners


def _persons(
    read: PostHogReader, person_ids: list[str]
) -> dict[str, tuple[str, dict[str, object]]]:
    rows = hogql_complete(read, PERSONS_HOGQL, {"persons": person_ids})
    persons: dict[str, tuple[str, dict[str, object]]] = {}
    for person_id, created_at, properties in rows:
        parsed = json.loads(properties) if isinstance(properties, str) else properties
        if not isinstance(parsed, dict):
            raise SystemExit(f"person {person_id} has non-object properties: {type(parsed)}")
        persons[str(person_id)] = (str(created_at), parsed)
    return persons


@dataclass(frozen=True)
class EmailPerson:
    """A PostHog person holding at least one email distinct_id."""

    person_id: str
    distinct_ids: tuple[str, ...]
    created_at: str
    properties: dict[str, object]


def match(persons: Iterable[EmailPerson], owners: Mapping[str, set[str]]) -> MergePlan:
    """Sort each email person into merge, already merged, unmatched or ambiguous; merges oldest first."""
    result = MergePlan([], [], [], [], [], set())
    for person in persons:
        owners_per_email = [
            owners.get(normalise_email(d), set()) for d in person.distinct_ids if "@" in d
        ]
        matches = set().union(*owners_per_email)
        merged_into = {d for d in person.distinct_ids if is_user_id(d)}
        if merged_into:
            if matches <= merged_into:
                result.already_merged.append(person.person_id)
            else:
                # Another user's email on a merged person: that user's history sits here too.
                result.ambiguous.append(person.person_id)
                result.held_users.update(matches | merged_into)
            continue
        if not matches:
            result.unmatched.append(person.person_id)
        elif len(matches) > 1:
            result.ambiguous.append(person.person_id)
            result.held_users.update(matches)
        elif not all(owners_per_email):
            result.unowned_aliases.append(person.person_id)
            result.held_users.update(matches)
        else:
            result.merges.append(
                Merge(
                    person.person_id,
                    person.distinct_ids,
                    person.created_at,
                    person.properties,
                    UserId(matches.pop()),
                )
            )
    result.merges.sort(key=lambda merge: merge.created_at)
    return result


def email_persons(read: PostHogReader) -> list[EmailPerson]:
    """Read every person holding an email distinct_id, with all its distinct_ids and properties."""
    email_rows = hogql_complete(read, EMAIL_PERSONS_HOGQL, {})
    person_ids = sorted({str(person_id) for _, person_id in email_rows})
    distinct_ids: defaultdict[str, list[str]] = defaultdict(list)
    for distinct_id, person_id in hogql_complete(
        read, PERSON_DISTINCT_IDS_HOGQL, {"persons": person_ids}
    ):
        distinct_ids[str(person_id)].append(str(distinct_id))
    persons = _persons(read, person_ids)
    return [
        EmailPerson(person_id, tuple(sorted(distinct_ids[person_id])), *persons[person_id])
        for person_id in person_ids
    ]


def plan(read: PostHogReader, db: Database[Document]) -> MergePlan:
    """Read every email person and match it to a GAIA user."""
    users = db.users.find({"email": {"$type": "string"}}, {"email": 1})
    return match(email_persons(read), users_by_email(users))


def write_snapshot(merges: list[Merge], snapshot_dir: Path) -> Path:
    """Write the persons about to be merged to JSONL: the only record a merge can be read back from."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    # Unique per run and created exclusively: no later run can replace an earlier record.
    path = (
        snapshot_dir / f"merge-email-persons-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex}.jsonl"
    )
    # Owner-only: the snapshot holds every merged person's properties, emails included.
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SNAPSHOT_MODE), "w", encoding="utf-8"
    ) as snapshot:
        for merge in merges:
            record = {
                "person_id": merge.person_id,
                "distinct_ids": merge.distinct_ids,
                "created_at": merge.created_at,
                "properties": merge.properties,
                "merged_into": merge.user_id.distinct_id,
            }
            snapshot.write(json.dumps(record) + "\n")
    return path


def apply(read: PostHogReader, sender: Sender, merges: list[Merge]) -> int:
    """Merge each person, then restore its first touch where it predates the survivor; return how many restored."""
    survivors = {
        str(distinct_id): str(created_at)
        for distinct_id, created_at in hogql_complete(
            read, SURVIVOR_CREATED_HOGQL, {"ids": [m.user_id.distinct_id for m in merges]}
        )
    }
    restored = 0
    for merge in merges:
        survivor = merge.user_id.distinct_id
        sender.client.capture(
            event=MERGE_EVENT, distinct_id=survivor, properties={"alias": merge.alias}
        )
        survivor_created = survivors.get(survivor)
        first_touch = merge.first_touch()
        if first_touch and (survivor_created is None or merge.created_at < survivor_created):
            sender.client.set(distinct_id=survivor, properties=first_touch)
            # The survivor now carries this person's first touch; a newer one must not replace it.
            survivors[survivor] = merge.created_at
            restored += 1
    return restored
