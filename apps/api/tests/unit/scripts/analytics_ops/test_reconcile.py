"""Reconciliation's PostHog side, its pairing with the truth, and the table it prints."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from scripts.analytics_ops.reconcile import (
    EVENT_COUNTS_HOGQL,
    LLM_COST_HOGQL,
    MESSAGES_HOGQL,
    SUBSCRIBED_PERSONS_HOGQL,
    Row,
    Signals,
    Window,
    compare,
    posthog_signals,
    render,
)

from tests.unit.scripts.analytics_ops.conftest import FakeReader

WINDOW = Window.last_days(30, datetime(2026, 10, 8, 15, 0, tzinfo=UTC))


def _reader() -> FakeReader:
    return FakeReader(
        {
            EVENT_COUNTS_HOGQL: [
                ["user:signed_up", 190],
                ["support:form_submitted", 3],
                ["subscription:activated", 6],
                ["payment:succeeded", 9],
            ],
            MESSAGES_HOGQL: [["web", 306], ["telegram", 88]],
            LLM_COST_HOGQL: [[16.1, 2.4]],
            SUBSCRIBED_PERSONS_HOGQL: [[14]],
        }
    )


def _truth(**overrides: object) -> Signals:
    base = Signals(
        signups=190,
        support_requests=3,
        subscriptions_started=6,
        billing={
            "payment:succeeded": 9,
            "payment:failed": 0,
            "subscription:activated": 6,
            "subscription:renewed": 0,
            "subscription:cancelled": 0,
        },
        messages_by_source={"web": 306, "telegram": 88},
        llm_cost_usd=18.5,
        subscribers_now=14,
    )
    return replace(base, **overrides)


class TestPostHogSide:
    def test_every_query_is_bounded_by_the_window(self) -> None:
        reader = _reader()

        posthog_signals(reader, WINDOW)

        windowed = [values for query, values in reader.queries if query != SUBSCRIBED_PERSONS_HOGQL]
        assert windowed
        for values in windowed:
            assert (values["start"], values["end"]) == (
                "2026-09-08 00:00:00",
                "2026-10-08 00:00:00",
            )

    def test_messages_are_read_from_the_server_submit_event(self) -> None:
        reader = _reader()

        signals = posthog_signals(reader, WINDOW)

        [values] = [v for q, v in reader.queries if q == MESSAGES_HOGQL]
        assert values["event"] == "chat:message_submitted"
        assert signals.messages_by_source == {"web": 306, "telegram": 88}

    def test_llm_spend_adds_one_shot_calls_and_graph_generations(self) -> None:
        reader = _reader()

        signals = posthog_signals(reader, WINDOW)

        [values] = [v for q, v in reader.queries if q == LLM_COST_HOGQL]
        assert (values["llm_event"], values["generation_event"]) == (
            "ai:llm_call_completed",
            "$ai_generation",
        )
        assert signals.llm_cost_usd == pytest.approx(18.5)

    def test_an_event_posthog_never_saw_counts_zero(self) -> None:
        signals = posthog_signals(_reader(), WINDOW)

        assert signals.billing["payment:failed"] == 0
        assert signals.billing["payment:succeeded"] == 9


class TestCompare:
    def test_agreeing_sides_match_on_every_row(self) -> None:
        rows = compare(posthog_signals(_reader(), WINDOW), _truth())

        assert all(row.matches for row in rows), [r for r in rows if not r.matches]

    def test_a_count_off_by_one_is_a_mismatch(self) -> None:
        rows = compare(posthog_signals(_reader(), WINDOW), _truth(signups=191))

        assert [row.signal for row in rows if not row.matches] == ["signups"]

    def test_a_source_only_one_side_saw_is_a_row_of_its_own(self) -> None:
        truth = _truth(messages_by_source={"web": 306, "telegram": 88, "discord": 2})

        rows = compare(posthog_signals(_reader(), WINDOW), truth)

        [discord] = [row for row in rows if row.signal == "messages, discord"]
        assert (discord.posthog, discord.truth, discord.matches) == (0, 2, False)

    def test_llm_cost_tolerates_provider_rounding_but_not_more(self) -> None:
        within = Row("LLM cost (USD)", 100.4, 100.0, "ledger", relative_tolerance=0.005)
        beyond = Row("LLM cost (USD)", 100.6, 100.0, "ledger", relative_tolerance=0.005)

        assert (within.matches, beyond.matches) == (True, False)


class TestRender:
    def test_each_row_prints_its_verdict_both_sides_and_the_truths_source(self) -> None:
        table = render(
            [
                Row("signups", 190, 191, "users.created_at"),
                Row("support requests", 3, 3, "support_requests.created_at"),
            ]
        )

        header, signups, support = table.splitlines()
        assert header.split() == ["signal", "posthog", "truth", "truth", "source"]
        assert signups.split() == ["XX", "signups", "190", "191", "users.created_at"]
        assert support.split() == [
            "ok",
            "support",
            "requests",
            "3",
            "3",
            "support_requests.created_at",
        ]
