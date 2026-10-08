"""analytics.py: the drift guard between PostHog and the event catalog.

Every rule here names a way a dashboard reads zero without anyone noticing:

* a tile still queries a renamed event (`chat:message_sent` read 0 for seven
  weeks after the rename to `chat:message_submitted`);
* the event survived but the tile filters or breaks down on a property the
  event no longer carries;
* the reference hides inside HogQL, where no UI shows the event name;
* the project's test-account filter drops every event, so every filtered tile
  reads 0 while the unfiltered one does not;
* a canonical action drifts from its checked-in definition, or a rename ships
  without the action that stitches the old name to the new one.

The insights are real ones from the 2026-10-08 snapshot; the catalog is a
small hand-made one in the shape `mise analytics:types` exports.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any

import pytest
import yaml

CI = Path(__file__).resolve().parent.parent
SCRIPT = CI / "analytics.py"
INSIGHTS = json.loads((CI / "tests" / "fixtures" / "posthog_insights.json").read_text())["insights"]

CATALOG_DOC: dict[str, Any] = {
    # The generated shape: shared fields live once, in base_properties.
    "base_properties": {"Attribution": {"properties": {"actor": {}, "trigger": {}, "surface": {}}}},
    "events": [
        {
            "event": "chat:message_submitted",
            "previous_names": ["chat:message_sent"],
            "base_properties": "Attribution",
            "properties": {"properties": {"source": {}, "has_files": {}, "platform": {}}},
        },
        {
            "event": "hil:decision_submitted",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {"approval_id": {}, "card_age_seconds": {}}},
        },
        {
            "event": "rate_limit:hit",
            "previous_names": ["rate_limit_hit"],
            "base_properties": "Attribution",
            "properties": {"properties": {"feature": {}, "plan": {}, "origin": {}}},
        },
        {
            "event": "onboarding:started",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {}},
        },
        {
            "event": "onboarding:completed",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {"platform": {}}},
        },
        {
            "event": "payment:checkout_started",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {"source": {}}},
        },
        {
            "event": "subscription:activated",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {"plan": {}}},
        },
        {
            "event": "user:signed_up",
            "previous_names": [],
            "base_properties": "Attribution",
            "properties": {"properties": {"signup_method": {}}},
        },
    ],
}


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("analytics_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


analytics = _load()


@pytest.fixture
def catalog() -> Any:
    return analytics.Catalog.from_doc(CATALOG_DOC)


def _insight(insight_id: int) -> dict[str, Any]:
    return next(i for i in INSIGHTS if i["id"] == insight_id)


def _bad(insight_id: int, catalog: Any) -> list[tuple[str, str, str | None]]:
    findings = analytics.bad_refs(_insight(insight_id)["query"], catalog, actions={})
    return sorted((f.kind, f.name, f.suggestion) for f in findings)


# ---------------------------------------------------------------------------
# (a) insights reference only catalog events and properties


def test_a_renamed_event_on_a_tile_points_at_its_successor(catalog: Any) -> None:
    assert _bad(6589947, catalog) == [("event", "chat:message_sent", "chat:message_submitted")]


def test_a_series_property_filter_is_checked_against_that_series_event(catalog: Any) -> None:
    assert _bad(11843360, catalog) == []
    query = json.loads(json.dumps(_insight(11843360)["query"]))
    query["source"]["series"][0]["properties"][0]["key"] = "approval_id"
    assert _bad_query(query, catalog) == [("property", "approval_id", None)]


def test_the_generated_catalog_gives_a_server_event_its_attribution() -> None:
    catalog = analytics.Catalog.load()
    assert {"actor", "trigger", "surface"} <= catalog.properties["chat:message_submitted"]


@pytest.mark.parametrize("shared", ["actor", "trigger", "surface"])
def test_a_filter_on_a_shared_attribution_property_is_a_real_ref(catalog: Any, shared: str) -> None:
    """The generated catalog keeps attribution in base_properties, not on each event."""
    query = json.loads(json.dumps(_insight(11843360)["query"]))
    query["source"]["series"][0]["properties"][0]["key"] = shared
    assert _bad_query(query, catalog) == []


def _bad_query(query: dict[str, Any], catalog: Any) -> list[tuple[str, str, str | None]]:
    return sorted(
        (f.kind, f.name, f.suggestion) for f in analytics.bad_refs(query, catalog, actions={})
    )


def test_a_dead_event_does_not_also_flag_every_property_it_carried(catalog: Any) -> None:
    assert _bad(11845518, catalog) == [("event", "hil:approval_decided", "hil:decision_submitted")]


def test_retention_entities_are_events_too(catalog: Any) -> None:
    assert _bad(6589959, catalog) == [("event", "chat:message_sent", "chat:message_submitted")]


def test_a_hogql_breakdown_contributes_its_properties(catalog: Any) -> None:
    assert _bad(11845123, catalog) == []
    query = json.loads(json.dumps(_insight(11845123)["query"]))
    query["source"]["breakdownFilter"]["breakdowns"][0]["property"] = "properties.sources"
    assert _bad_query(query, catalog) == [("property", "sources", "source")]


def test_a_funnel_flags_each_dead_step_once(catalog: Any) -> None:
    assert _bad(6589753, catalog) == [
        ("event", "chat:first_message_sent", "chat:message_submitted"),
        ("event", "onboarding:step_completed", "onboarding:completed"),
    ]


def test_a_hogql_query_is_read_for_its_events_and_properties(catalog: Any) -> None:
    assert _bad(11403383, catalog) == [("event", "rate_limit_hit", "rate_limit:hit")]


def test_hogql_person_properties_and_sdk_names_are_not_catalog_refs(catalog: Any) -> None:
    # p is the persons alias, so p.properties.email is a person property; $ai_* is the SDK's.
    assert _bad(11403259, catalog) == []


def test_hogql_extraction_reads_comparisons_lists_and_aliases() -> None:
    events, props = analytics.hogql_refs(
        "SELECT e.properties.source, properties['has_files'], person.properties.plan, "
        "'properties.inside_a_string' AS s FROM events AS e "
        "WHERE e.event IN ('a:one', 'b:two') OR 'c:three' = event OR event != 'd:four' "
        "-- event = 'e:commented_out'\n"
        "AND properties.event = 'not:an_event'"
    )
    assert events == {"a:one", "b:two", "c:three", "d:four"}
    assert props == {"source", "has_files", "event"}


def test_an_unknown_query_kind_fails_instead_of_passing_unread(catalog: Any) -> None:
    query = {"kind": "InsightVizNode", "source": {"kind": "SomeNewQuery", "series": []}}
    assert _bad_query(query, catalog) == [("kind", "SomeNewQuery", None)]


def test_an_action_series_scopes_properties_to_the_action_events(catalog: Any) -> None:
    query = {
        "kind": "InsightVizNode",
        "source": {
            "kind": "TrendsQuery",
            "series": [{"kind": "ActionsNode", "id": 7}],
            "breakdownFilter": {"breakdown": "has_files", "breakdown_type": "event"},
        },
    }
    actions = {7: {"chat:message_submitted"}}
    assert analytics.bad_refs(query, catalog, actions=actions) == []
    actions = {7: {"user:signed_up"}}
    assert [f.name for f in analytics.bad_refs(query, catalog, actions=actions)] == ["has_files"]


def test_a_property_an_sdk_event_in_the_same_query_may_carry_is_not_judged(catalog: Any) -> None:
    query = {
        "kind": "HogQLQuery",
        "query": "SELECT properties.agent_name FROM events "
        "WHERE event IN ('$ai_generation', 'rate_limit:hit')",
    }
    assert _bad_query(query, catalog) == []
    query["query"] = query["query"].replace("'$ai_generation', ", "")
    assert _bad_query(query, catalog) == [("property", "agent_name", None)]


def test_an_action_whose_step_is_no_catalog_event_is_a_bad_ref(catalog: Any) -> None:
    query = {"kind": "TrendsQuery", "series": [{"kind": "ActionsNode", "id": 7}]}
    stale = {7: {"hil:approval_decided"}}
    assert [
        (f.kind, f.name, f.suggestion) for f in analytics.bad_refs(query, catalog, actions=stale)
    ] == [("event", "hil:approval_decided", "hil:decision_submitted")]


def test_a_continuity_action_may_step_on_a_previous_name(catalog: Any) -> None:
    query = {"kind": "TrendsQuery", "series": [{"kind": "ActionsNode", "id": 7}]}
    continuity = {7: {"chat:message_sent", "chat:message_submitted"}}
    assert analytics.bad_refs(query, catalog, actions=continuity) == []


def test_an_action_that_no_longer_exists_is_a_bad_ref(catalog: Any) -> None:
    query = {"kind": "TrendsQuery", "series": [{"kind": "ActionsNode", "id": 99}]}
    assert _bad_query(query, catalog) == [("action", "99", None)]


class _Project:
    """The three reads the insight check makes, answering from memory instead of the API."""

    def __init__(self, insights: list[dict[str, Any]]) -> None:
        self._insights = insights

    def dashboards(self) -> list[dict[str, Any]]:
        return [{"id": 1, "name": "Chat & Engagement"}]

    def actions(self) -> list[dict[str, Any]]:
        return []

    def insights(self) -> list[dict[str, Any]]:
        return self._insights


def test_only_insights_on_a_live_dashboard_are_read_and_the_rest_are_counted(
    catalog: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    dead = _insight(6589947)
    project = _Project(
        [
            {**dead, "dashboards": [1]},
            {**dead, "id": 2, "dashboards": [1188161]},  # a soft-deleted dashboard
            {**dead, "id": 3, "dashboards": []},
        ]
    )
    failures = analytics._insight_failures(project, catalog)
    assert failures == [
        'Chat & Engagement › "Daily messages sent" (insight 6589947) › '
        "event chat:message_sent — not in the catalog (renamed to chat:message_submitted)"
    ]
    assert "2 saved insights on no live dashboard not read" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# (b) the live project settings equal config/posthog/project.json


SETTINGS = {
    "test_account_filters": [{"key": "NOT ifNull(x, false)", "type": "hogql"}],
    "test_account_filters_default_checked": True,
    "primary_dashboard": 1,
}


def test_identical_settings_have_no_diff() -> None:
    live = {**SETTINGS, "name": "GAIA", "timezone": "Asia/Kolkata"}
    assert analytics.settings_diff(SETTINGS, live) == []


def test_a_changed_filter_names_the_setting_and_both_values() -> None:
    live = {**SETTINGS, "test_account_filters": [{"key": "x", "type": "hogql"}]}
    (diff,) = analytics.settings_diff(SETTINGS, live)
    assert "test_account_filters" in diff
    assert "NOT ifNull(x, false)" in diff and '"x"' in diff


def test_a_setting_missing_from_the_live_project_is_a_diff() -> None:
    live = {k: v for k, v in SETTINGS.items() if k != "primary_dashboard"}
    assert [d.split(":")[0] for d in analytics.settings_diff(SETTINGS, live)] == [
        "primary_dashboard"
    ]


# ---------------------------------------------------------------------------
# (c) the test-account filter does not drop every event


def test_the_probe_fails_when_the_filter_drops_every_signup() -> None:
    assert analytics.probe_failure(filtered=0, unfiltered=49) is not None


@pytest.mark.parametrize(("filtered", "unfiltered"), [(48, 49), (0, 0)])
def test_the_probe_passes_otherwise(filtered: int, unfiltered: int) -> None:
    assert analytics.probe_failure(filtered=filtered, unfiltered=unfiltered) is None


# ---------------------------------------------------------------------------
# (d) canonical actions: live equals the file, and renames are covered


def _live_action(
    name: str, steps: list[dict[str, Any]], tags: list[str] | None = None
) -> dict[str, Any]:
    # The shape GET /actions returns: every selector key present, nulls included.
    full_steps = [
        {
            "event": None,
            "properties": None,
            "selector": None,
            "selector_regex": None,
            "tag_name": None,
            "text": None,
            "text_matching": None,
            "href": None,
            "href_matching": None,
            "url": None,
            "url_matching": "contains",
            **step,
        }
        for step in steps
    ]
    return {
        "id": 1,
        "name": name,
        "description": "d",
        "tags": ["canonical"] if tags is None else tags,
        "steps": full_steps,
    }


BOUNDED = [{"key": "timestamp < toDateTime('2026-08-17 11:25:02.541', 'UTC')", "type": "hogql"}]
EXPECTED = [
    {
        "name": "Chat message submitted (continuous)",
        "description": "d",
        "tags": ["canonical"],
        "steps": [
            {"event": "chat:message_sent", "properties": BOUNDED},
            {"event": "chat:message_submitted"},
        ],
    }
]


def test_a_live_action_equal_to_the_file_has_no_diff() -> None:
    live_bounded = [{**BOUNDED[0], "value": None}]
    live = [
        _live_action(
            "Chat message submitted (continuous)",
            [
                {"event": "chat:message_sent", "properties": live_bounded},
                {"event": "chat:message_submitted"},
            ],
        ),
        _live_action("hi", [{"event": "$autocapture"}], tags=[]),
    ]
    assert analytics.action_diff(EXPECTED, live, tag="canonical") == []


def test_missing_changed_and_unlisted_canonical_actions_are_each_reported() -> None:
    changed = _live_action(
        "Chat message submitted (continuous)", [{"event": "chat:message_submitted"}]
    )
    unlisted = _live_action("Someone's action", [{"event": "user:signed_up"}])
    assert analytics.action_diff(EXPECTED, [], tag="canonical") == [
        "Chat message submitted (continuous): missing from the project"
    ]
    diffs = analytics.action_diff(EXPECTED, [changed, unlisted], tag="canonical")
    assert diffs[0].startswith("Chat message submitted (continuous): steps differ")
    assert (
        diffs[1]
        == "Someone's action: tagged canonical in the project but not in config/posthog/actions.json"
    )


def test_every_previous_name_must_be_stitched_to_its_successor(catalog: Any) -> None:
    assert analytics.coverage_gaps(catalog, EXPECTED) == [
        "rate_limit_hit -> rate_limit:hit: no canonical action has both as steps"
    ]


def test_an_action_with_only_the_old_name_does_not_stitch_the_rename(catalog: Any) -> None:
    old_only = [{**EXPECTED[0], "steps": EXPECTED[0]["steps"][:1]}]
    gaps = analytics.coverage_gaps(catalog, old_only)
    assert (
        "chat:message_sent -> chat:message_submitted: no canonical action has both as steps" in gaps
    )


def test_an_action_step_must_name_a_catalog_event_or_a_previous_name(catalog: Any) -> None:
    stale = [
        {**EXPECTED[0], "steps": [*EXPECTED[0]["steps"], {"event": "chat:first_message_sent"}]}
    ]
    gaps = analytics.coverage_gaps(catalog, stale)
    assert (
        "Chat message submitted (continuous): step chat:first_message_sent is not a catalog event or a previous name"
        in gaps
    )


class _ActionsProject:
    """The action reads and writes sync-actions makes, recorded instead of sent."""

    def __init__(self, live: list[dict[str, Any]], fail_updates: bool = False) -> None:
        self.live = live
        self.fail_updates = fail_updates
        self.writes: list[tuple[str, int | None, dict[str, Any]]] = []

    def actions(self) -> list[dict[str, Any]]:
        return self.live

    def create_action(self, action: dict[str, Any]) -> None:
        self.writes.append(("create", None, action))

    def update_action(self, action_id: int, action: dict[str, Any]) -> None:
        if self.fail_updates:
            raise analytics.PostHogError(f"PATCH actions/{action_id}/: HTTP 500")
        self.writes.append(("update", action_id, action))


NEW_ACTION = {
    "name": "Signed up",
    "description": "d",
    "tags": ["canonical"],
    "steps": [{"event": "user:signed_up"}],
}


def _sync(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    project: _ActionsProject,
    expected: list[dict[str, Any]],
    args: list[str],
) -> tuple[int, list[tuple[str, ...]]]:
    actions_json = tmp_path / "actions.json"
    actions_json.write_text(json.dumps({"tag": "canonical", "actions": expected}))
    monkeypatch.setattr(analytics, "ACTIONS_JSON", actions_json)
    scopes_asked: list[tuple[str, ...]] = []

    def client(scopes: tuple[str, ...]) -> _ActionsProject:
        scopes_asked.append(tuple(scopes))
        return project

    monkeypatch.setattr(analytics, "client_from_env", client)
    return analytics.main(["sync-actions", *args]), scopes_asked


def _stale_live() -> list[dict[str, Any]]:
    stale = _live_action(
        "Chat message submitted (continuous)", [{"event": "chat:message_submitted"}]
    )
    stale["id"] = 42
    return [stale]


def test_a_sync_dry_run_writes_nothing_and_asks_only_to_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _ActionsProject(_stale_live())
    code, scopes = _sync(monkeypatch, tmp_path, project, [*EXPECTED, NEW_ACTION], [])
    assert code == 0
    assert project.writes == []
    assert scopes == [tuple(analytics.READ_SCOPES)]
    assert capsys.readouterr().out.splitlines() == [
        "update  Chat message submitted (continuous) (action 42)",
        "create  Signed up",
        "2 change(s) planned (dry run; re-run with --apply to perform)",
    ]


def test_sync_apply_creates_the_missing_and_overwrites_the_changed_action(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project = _ActionsProject(_stale_live())
    code, scopes = _sync(monkeypatch, tmp_path, project, [*EXPECTED, NEW_ACTION], ["--apply"])
    assert code == 0
    assert scopes == [(*analytics.READ_SCOPES, analytics.WRITE_SCOPE)]
    assert project.writes == [
        ("update", 42, EXPECTED[0]),
        ("create", None, NEW_ACTION),
    ]


def test_sync_apply_leaves_an_action_equal_to_the_file_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    live_bounded = [{**BOUNDED[0], "value": None}]
    same = _live_action(
        "Chat message submitted (continuous)",
        [
            {"event": "chat:message_sent", "properties": live_bounded},
            {"event": "chat:message_submitted"},
        ],
    )
    project = _ActionsProject([same])
    code, _ = _sync(monkeypatch, tmp_path, project, EXPECTED, ["--apply"])
    assert code == 0
    assert project.writes == []
    assert capsys.readouterr().out.splitlines() == ["0 change(s) applied"]


def test_a_failed_write_stops_the_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    project = _ActionsProject(_stale_live(), fail_updates=True)
    with pytest.raises(analytics.PostHogError, match="PATCH actions/42/: HTTP 500"):
        _sync(monkeypatch, tmp_path, project, [*EXPECTED, NEW_ACTION], ["--apply"])
    assert project.writes == []


# ---------------------------------------------------------------------------
# the key


def test_check_without_a_key_fails_loudly_and_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    assert analytics.main(["check"]) != 0
    err = capsys.readouterr().err
    assert "POSTHOG_PERSONAL_API_KEY" in err
    for scope in ("insight:read", "project:read", "query:read", "dashboard:read", "action:read"):
        assert scope in err


def test_with_a_key_the_client_targets_the_checked_in_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTHOG_PERSONAL_API_KEY", "phx_test")
    client = analytics.client_from_env(analytics.READ_SCOPES)
    project = json.loads(analytics.PROJECT_JSON.read_text())
    assert client is not None
    assert (client.netloc, client.base, client.key) == (
        project["host"].removeprefix("https://"),
        f"/api/projects/{project['project_id']}",
        "phx_test",
    )


def test_an_unknown_subcommand_is_a_usage_error() -> None:
    assert analytics.main(["nope"]) == 2


# ---------------------------------------------------------------------------
# the lane


LANES = CI.parent / "dev" / "verify-lanes.json"
WORKFLOW = CI.parent.parent / ".github" / "workflows" / "code-quality.yml"


def test_the_lane_scope_is_the_files_that_define_the_contract() -> None:
    lanes = json.loads(LANES.read_text())["lanes"]
    scope = next(lane["scope"] for lane in lanes if lane["name"] == "analytics-check")
    for path in (
        "libs/shared/py/analytics/catalog/chat.py",
        "libs/shared/ts/src/analytics/generated/analytics-catalog.json",
        "config/posthog/project.json",
        "config/posthog/actions.json",
        "scripts/ci/analytics.py",
    ):
        assert re.search(scope, path), path
    for path in ("apps/web/src/app/page.tsx", "libs/shared/py/analytics/client.py"):
        assert not re.search(scope, path), path


def test_the_ci_job_runs_the_check_with_the_secret_and_reads_the_lane_scope() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    job = workflow["jobs"]["analytics-check"]
    (step,) = [s for s in job["steps"] if "analytics.py" in str(s.get("run", ""))]
    assert step["run"] == "python3 scripts/ci/analytics.py check"
    assert step["env"]["POSTHOG_PERSONAL_API_KEY"] == "${{ secrets.POSTHOG_PERSONAL_API_KEY }}"
    assert "has_analytics" in job["if"]
    (detect,) = [s for s in workflow["jobs"]["changes"]["steps"] if s.get("id") == "detect"]
    assert "l.name === 'analytics-check'" in detect["run"]
    assert "has_analytics=$ANALYTICS" in detect["run"]
