"""Tests for the todo constants module's query fragments and facet resolver.

``app/constants/todos.py`` is mostly declarative data, but three functions in it
are the single source of truth for behaviour every other layer depends on: the
two Mongo assignee fragments (repositories, workers and endpoints all narrow
with them) and ``facet_from_doc``, the dual-read migration bridge shared by the
storage primitives and the VFS projection. These pin the exact fragment shape
and every branch of the bridge.
"""

from typing import Any

import pytest

from app.constants.todos import (
    ASSIGNEE_GAIA,
    FACET_DELIVERABLE,
    FACET_FIELDS,
    FACET_LOG,
    FACET_NOTES,
    facet_from_doc,
    gaia_assigned_filter,
    user_assigned_filter,
)

LEGACY_CANVAS = "canvas_content"


class TestAssigneeFilters:
    """The Mongo fragments that split GAIA todos from user todos."""

    def test_gaia_filter_matches_the_assignee_field_exactly(self) -> None:
        assert gaia_assigned_filter() == {"assignee": ASSIGNEE_GAIA}

    def test_user_filter_excludes_gaia_and_so_matches_unmigrated_docs(self) -> None:
        assert user_assigned_filter() == {"assignee": {"$ne": ASSIGNEE_GAIA}}


class TestFacetFromDoc:
    """The facet dual-read bridge, branch by branch."""

    @pytest.mark.parametrize("facet", [FACET_DELIVERABLE, FACET_NOTES, FACET_LOG])
    def test_stored_content_wins_for_every_facet(self, facet: str) -> None:
        """A written facet is read from its own field, never from the legacy blob."""
        doc: dict[str, Any] = {FACET_FIELDS[facet]: "own content", LEGACY_CANVAS: "legacy"}

        assert facet_from_doc(doc, facet, allow_canvas_fallback=True) == "own content"

    def test_non_string_stored_content_is_coerced(self) -> None:
        assert (
            facet_from_doc({FACET_FIELDS[FACET_LOG]: 42}, FACET_LOG, allow_canvas_fallback=False)
            == "42"
        )

    def test_notes_falls_back_to_the_legacy_canvas(self) -> None:
        """The old canvas WAS the working memory, so notes always reads it."""
        doc: dict[str, Any] = {LEGACY_CANVAS: "legacy body"}

        assert facet_from_doc(doc, FACET_NOTES, allow_canvas_fallback=False) == "legacy body"

    def test_notes_without_a_canvas_is_empty(self) -> None:
        assert facet_from_doc({}, FACET_NOTES, allow_canvas_fallback=True) == ""

    def test_deliverable_falls_back_to_the_canvas_only_when_allowed(self) -> None:
        doc: dict[str, Any] = {LEGACY_CANVAS: "legacy body"}

        assert facet_from_doc(doc, FACET_DELIVERABLE, allow_canvas_fallback=True) == "legacy body"

    def test_deliverable_ignores_the_canvas_when_not_allowed(self) -> None:
        doc: dict[str, Any] = {LEGACY_CANVAS: "legacy body"}

        assert facet_from_doc(doc, FACET_DELIVERABLE, allow_canvas_fallback=False) == ""

    def test_deliverable_without_a_canvas_is_empty(self) -> None:
        assert facet_from_doc({}, FACET_DELIVERABLE, allow_canvas_fallback=True) == ""

    def test_log_never_falls_back_to_the_canvas(self) -> None:
        """Only notes and deliverable bridge; the timeline has no legacy source."""
        doc: dict[str, Any] = {LEGACY_CANVAS: "legacy body"}

        assert facet_from_doc(doc, FACET_LOG, allow_canvas_fallback=True) == ""

    @pytest.mark.parametrize("facet", [FACET_DELIVERABLE, FACET_NOTES, FACET_LOG])
    def test_empty_stored_content_is_treated_as_unwritten(self, facet: str) -> None:
        """An empty string is not content, so the fallback rules still apply."""
        doc: dict[str, Any] = {FACET_FIELDS[facet]: "", LEGACY_CANVAS: "legacy body"}
        expected = "legacy body" if facet in (FACET_NOTES, FACET_DELIVERABLE) else ""

        assert facet_from_doc(doc, facet, allow_canvas_fallback=True) == expected
