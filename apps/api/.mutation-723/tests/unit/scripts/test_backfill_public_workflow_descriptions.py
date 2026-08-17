"""Unit tests for the workflow-description backfill script.

The script's decision logic (truncation, prompt resolution, plan building)
is pure and drives what gets written to Mongo — pin it here so the script's
core behavior is covered without running it against a real cluster.
"""

import pytest

from app.scripts.backfill_public_workflow_descriptions import (
    COPY_DESCRIPTION,
    _build_plans,
    _plan_for,
    _resolve_prompt,
    _truncate,
)


def test_truncate_keeps_short_text() -> None:
    assert _truncate("short") == "short"


def test_truncate_collapses_newlines_and_ellipsizes() -> None:
    out = _truncate("a" * 100, limit=10)
    assert out == "aaaaaaaaa…"
    assert "\n" not in _truncate("line1\nline2", limit=80)


def test_resolve_prompt_copy_sentinel_uses_next_description() -> None:
    assert _resolve_prompt(COPY_DESCRIPTION, "next") == "next"


def test_resolve_prompt_passthrough_and_none() -> None:
    assert _resolve_prompt("explicit", "next") == "explicit"
    assert _resolve_prompt(None, "next") is None


def test_plan_for_noop_when_matches_target() -> None:
    plan = _plan_for(
        "wid-1",
        {"description": "same", "prompt": "same"},
        {"description": "same", "prompt": "same"},
    )
    assert plan is None


def test_plan_for_edit_and_copy_sentinel() -> None:
    before, after = _plan_for(
        "wid-1",
        {"description": "new", "prompt": COPY_DESCRIPTION},
        {"description": "old", "prompt": "old-prompt"},
    )
    assert before == {"description": "old", "prompt": "old-prompt"}
    assert after == {"description": "new", "prompt": "new"}


def test_build_plans_skips_orphans_and_noops() -> None:
    manifest = {
        "wid-1": {"description": "new", "prompt": None},
        "wid-missing": {"description": "x", "prompt": None},
    }
    docs = {"wid-1": {"description": "old", "prompt": "p", "title": "T"}}
    plans = _build_plans(manifest, docs)

    assert [wid for wid, _, _ in plans] == ["wid-1"]


def test_main_parses_flags(capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.scripts.backfill_public_workflow_descriptions import main

    monkeypatch.setattr("sys.argv", ["backfill_public_workflow_descriptions", "--help"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    assert "backfill" in capsys.readouterr().out
