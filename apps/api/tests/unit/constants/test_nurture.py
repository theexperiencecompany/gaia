"""Tests for the nurture email sequence definition.

The steps in app/constants/nurture.py are declarative data, but each field
is a key into a live registry: skip predicates resolve into
app/services/nurture/predicates.py, context builders into
app/services/nurture/context_builders.py, templates must exist on disk, and
the frequency guardrails must actually fit the schedule they guard. These tests
pin every one of those couplings so a rename or a cap change fails loudly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import app
from app.constants.nurture import (
    NURTURE_BACKFILL_GRACE_DAYS,
    NURTURE_STEPS,
)
from app.models.nurture_models import NurtureHistoryEntry, NurtureStepStatus
from app.services.nurture.context_builders import CONTEXT_BUILDERS
from app.services.nurture.predicates import SKIP_PREDICATES
from app.services.nurture.service import _within_frequency_caps

_TEMPLATES_DIR = Path(app.__file__).resolve().parent / "templates"


class TestStepRegistry:
    def test_step_keys_are_unique(self) -> None:
        keys = [step.key for step in NURTURE_STEPS]
        assert len(keys) == len(set(keys))

    def test_every_skip_predicate_resolves(self) -> None:
        for step in NURTURE_STEPS:
            if step.skip_predicate is not None:
                assert step.skip_predicate in SKIP_PREDICATES, (
                    f"step {step.key}: unknown skip predicate {step.skip_predicate!r}"
                )

    def test_every_context_builder_resolves(self) -> None:
        for step in NURTURE_STEPS:
            if step.context_builder is not None:
                assert step.context_builder in CONTEXT_BUILDERS, (
                    f"step {step.key}: unknown context builder {step.context_builder!r}"
                )

    def test_every_template_exists_on_disk(self) -> None:
        for step in NURTURE_STEPS:
            assert (_TEMPLATES_DIR / step.template).is_file(), (
                f"step {step.key}: missing template {step.template!r}"
            )

    def test_cta_fields_come_in_pairs(self) -> None:
        for step in NURTURE_STEPS:
            assert (step.cta_path is None) == (step.cta_label is None), (
                f"step {step.key}: cta_path and cta_label must be set together"
            )


class TestScheduleFitsTheCaps:
    """Simulate the sequence sending each step at its earliest possible day and prove the 3/week + 2-day spacing cap starves no enabled step."""

    @staticmethod
    def _day(offset: int) -> datetime:
        return datetime(2026, 1, offset, 9, tzinfo=UTC)

    def test_every_enabled_step_can_send_within_its_window(self) -> None:
        sent: list[NurtureHistoryEntry] = []
        for step in NURTURE_STEPS:
            if not step.enabled:
                continue
            window = range(step.day_offset, step.day_offset + NURTURE_BACKFILL_GRACE_DAYS + 1)
            send_day = next(
                (day for day in window if _within_frequency_caps(sent, self._day(day))),
                None,
            )
            assert send_day is not None, (
                f"step {step.key} (day {step.day_offset}) is starved by the caps: "
                f"no sendable day in its window. Tightening a cap starves a step."
            )
            sent.append(
                NurtureHistoryEntry(
                    step=step.key, at=self._day(send_day), status=NurtureStepStatus.SENT
                )
            )
