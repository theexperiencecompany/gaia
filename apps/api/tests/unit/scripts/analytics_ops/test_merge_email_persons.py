"""Merging email-keyed PostHog persons into their GAIA user: irreversible, so every rule is pinned."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from scripts.analytics_ops import __main__ as cli
from scripts.analytics_ops.merge_email_persons import (
    EMAIL_PERSONS_HOGQL,
    MERGE_EVENT,
    PERSON_DISTINCT_IDS_HOGQL,
    PERSONS_HOGQL,
    SURVIVOR_CREATED_HOGQL,
    EmailPerson,
    Merge,
    apply,
    match,
    users_by_email,
    write_snapshot,
)
from scripts.analytics_ops.posthog_api import Sender, TargetName

from tests.unit.scripts.analytics_ops.conftest import FakeReader

ALICE = "6ac74a19fa5dfaf1f5770471"
BOB = "6ac74a19fa5dfaf1f5770472"
CAROL = "6ac74a19fa5dfaf1f5770473"


def _person(
    person_id: str, *distinct_ids: str, created_at: str = "2026-01-01 00:00:00", **props: object
) -> EmailPerson:
    return EmailPerson(person_id, tuple(sorted(distinct_ids)), created_at, dict(props))


def _owners(*users: tuple[str, str]) -> dict[str, set[str]]:
    return users_by_email({"_id": user_id, "email": email} for user_id, email in users)


class TestMatching:
    def test_an_email_person_merges_into_the_user_holding_that_email(self) -> None:
        plan = match([_person("p1", "alice@x.com")], _owners((ALICE, "alice@x.com")))

        assert [(m.person_id, m.user_id.distinct_id) for m in plan.merges] == [("p1", ALICE)]

    def test_case_differences_between_posthog_and_mongo_still_match(self) -> None:
        plan = match([_person("p1", "Alice@X.com")], _owners((ALICE, "alice@x.COM")))

        assert [m.user_id.distinct_id for m in plan.merges] == [ALICE]

    def test_surrounding_whitespace_on_either_side_still_matches(self) -> None:
        plan = match([_person("p1", " alice@x.com")], _owners((ALICE, "alice@x.com \n")))

        assert [m.user_id.distinct_id for m in plan.merges] == [ALICE]

    def test_an_email_no_user_holds_is_left_unmerged(self) -> None:
        plan = match([_person("p1", "gone@x.com")], _owners((ALICE, "alice@x.com")))

        assert (plan.merges, plan.unmatched) == ([], ["p1"])

    def test_an_email_two_users_hold_is_never_merged(self) -> None:
        plan = match(
            [_person("p1", "dup@x.com")], _owners((ALICE, "dup@x.com"), (BOB, "DUP@x.com"))
        )

        assert (plan.merges, plan.ambiguous) == ([], ["p1"])

    def test_a_person_with_two_emails_of_two_users_is_never_merged(self) -> None:
        person = _person("p1", "alice@x.com", "bob@x.com")

        plan = match([person], _owners((ALICE, "alice@x.com"), (BOB, "bob@x.com")))

        assert (plan.merges, plan.ambiguous) == ([], ["p1"])

    def test_a_person_already_holding_a_mongo_id_is_skipped(self) -> None:
        plan = match([_person("p1", "alice@x.com", ALICE)], _owners((ALICE, "alice@x.com")))

        assert (plan.merges, plan.already_merged) == ([], ["p1"])

    def test_merges_run_oldest_person_first(self) -> None:
        persons = [
            _person("new", "bob@x.com", created_at="2026-03-01 00:00:00"),
            _person("old", "alice@x.com", created_at="2025-11-01 00:00:00"),
        ]

        plan = match(persons, _owners((ALICE, "alice@x.com"), (BOB, "bob@x.com")))

        assert [m.person_id for m in plan.merges] == ["old", "new"]


def _merge(person_id: str, email: str, user_id: str, created_at: str, **props: object) -> Merge:
    return match(
        [_person(person_id, email, created_at=created_at, **props)], _owners((user_id, email))
    ).merges[0]


def _survivors(created: dict[str, str]) -> FakeReader:
    return FakeReader(
        {
            SURVIVOR_CREATED_HOGQL: lambda values: [
                [d, created[d]] for d in values["ids"] if d in created
            ]
        }
    )


class TestApply:
    def test_each_merge_names_the_survivor_and_aliases_the_email(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        merge = _merge("p1", "alice@x.com", ALICE, "2026-05-01 00:00:00")

        apply(_survivors({ALICE: "2026-01-01 00:00:00"}), recording_sender, [merge])

        [message] = sent
        assert (message["event"], message["distinct_id"]) == (MERGE_EVENT, ALICE)
        assert message["properties"]["alias"] == "alice@x.com"

    def test_an_older_email_persons_first_touch_is_read_then_set_on_the_survivor(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        merge = _merge(
            "p1",
            "alice@x.com",
            ALICE,
            "2025-11-01 00:00:00",
            **{
                "$initial_referring_domain": "google.com",
                "first_seen": "2025-11-01",
                "plan": "free",
            },
        )

        restored = apply(_survivors({ALICE: "2026-02-01 00:00:00"}), recording_sender, [merge])

        merge_message, set_message = sent
        assert merge_message["event"] == MERGE_EVENT
        assert (set_message["event"], set_message["distinct_id"]) == ("$set", ALICE)
        assert set_message["$set"] == {
            "$initial_referring_domain": "google.com",
            "first_seen": "2025-11-01",
        }
        assert restored == 1

    def test_a_newer_email_persons_first_touch_does_not_overwrite_the_survivors(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        merge = _merge("p1", "alice@x.com", ALICE, "2026-06-01 00:00:00", first_seen="2026-06-01")

        restored = apply(_survivors({ALICE: "2026-02-01 00:00:00"}), recording_sender, [merge])

        assert [m["event"] for m in sent] == [MERGE_EVENT]
        assert restored == 0

    def test_two_older_persons_of_one_user_restore_only_the_oldests_first_touch(
        self, recording_sender: Sender, sent: list[dict[str, object]]
    ) -> None:
        """Merges run oldest first; the second must not overwrite the first's earlier first touch."""
        oldest = _merge("p1", "Alice@x.com", ALICE, "2025-09-01 00:00:00", first_seen="2025-09-01")
        later = _merge("p2", "alice@x.com", ALICE, "2025-11-01 00:00:00", first_seen="2025-11-01")

        restored = apply(
            _survivors({ALICE: "2026-02-01 00:00:00"}), recording_sender, [oldest, later]
        )

        sets = [m["$set"] for m in sent if m["event"] == "$set"]
        assert sets == [{"first_seen": "2025-09-01"}]
        assert restored == 1


class TestSnapshot:
    def test_two_snapshots_in_one_second_are_two_files(self, tmp_path: Path) -> None:
        """A snapshot is the only record of an irreversible merge; a later run must never replace it."""
        merge = _merge("p1", "alice@x.com", ALICE, "2026-05-01 00:00:00")

        first = write_snapshot([merge], tmp_path)
        second = write_snapshot([merge], tmp_path)

        assert first != second
        assert len(list(tmp_path.iterdir())) == 2


class TestCommand:
    """The CLI's modes: a dry run touches nothing, --pilot N touches exactly N."""

    @pytest.fixture
    def opened(self, monkeypatch: pytest.MonkeyPatch, recording_sender: Sender) -> list[Sender]:
        users = [
            {"_id": ALICE, "email": "alice@x.com"},
            {"_id": BOB, "email": "bob@x.com"},
            {"_id": CAROL, "email": "carol@x.com"},
        ]
        persons = {
            "p1": ("alice@x.com", "2025-10-01 00:00:00"),
            "p2": ("bob@x.com", "2025-11-01 00:00:00"),
            "p3": ("carol@x.com", "2025-12-01 00:00:00"),
        }
        reader = FakeReader(
            {
                EMAIL_PERSONS_HOGQL: [[email, pid] for pid, (email, _) in persons.items()],
                PERSON_DISTINCT_IDS_HOGQL: [[email, pid] for pid, (email, _) in persons.items()],
                PERSONS_HOGQL: [[pid, created, "{}"] for pid, (_, created) in persons.items()],
                SURVIVOR_CREATED_HOGQL: [],
            }
        )

        class _Users:
            def find(self, *_args: object) -> list[dict[str, str]]:
                return users

        class _Db:
            users = _Users()

        opens: list[Sender] = []

        def open_sender(*_args: object) -> Sender:
            opens.append(recording_sender)
            return recording_sender

        monkeypatch.setattr(cli, "ground_truth_db", _Db)
        monkeypatch.setattr(cli, "reader", lambda *_args: reader)
        monkeypatch.setattr(Sender, "open", open_sender)
        return opens

    def _run(self, tmp_path: Path, *, pilot: int | None = None, apply: bool = False) -> int:
        return cli.cmd_merge(
            argparse.Namespace(
                project=TargetName.E2E, pilot=pilot, apply=apply, snapshot_dir=tmp_path
            )
        )

    def test_a_dry_run_opens_no_sender_and_writes_no_snapshot(
        self, opened: list[Sender], sent: list[dict[str, object]], tmp_path: Path
    ) -> None:
        assert self._run(tmp_path) == 0

        assert (opened, sent, list(tmp_path.iterdir())) == ([], [], [])

    def test_a_pilot_merges_exactly_n_persons_oldest_first(
        self, opened: list[Sender], sent: list[dict[str, object]], tmp_path: Path
    ) -> None:
        assert self._run(tmp_path, pilot=2) == 0

        merged = [m["properties"]["alias"] for m in sent if m["event"] == MERGE_EVENT]
        assert merged == ["alice@x.com", "bob@x.com"]
        [snapshot] = tmp_path.iterdir()
        assert len(snapshot.read_text().splitlines()) == 2

    def test_apply_merges_every_matched_person(
        self, opened: list[Sender], sent: list[dict[str, object]], tmp_path: Path
    ) -> None:
        assert self._run(tmp_path, apply=True) == 0

        assert len([m for m in sent if m["event"] == MERGE_EVENT]) == 3
