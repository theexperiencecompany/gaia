#!/usr/bin/env python3
"""analytics.py — the PostHog side of the event catalog contract.

Subcommands:
  check [--live-catalog P] [--live-actions P]
                          Fail when the PostHog project drifts from the repo:
                          (a) a saved insight on a live dashboard references an
                              event or property the catalog does not have;
                          (b) the project settings differ from
                              config/posthog/project.json;
                          (c) the test-account filter drops every user:signed_up
                              of the last 7 days that the unfiltered count sees;
                          (d) the canonical actions differ from
                              config/posthog/actions.json, or a catalog event's
                              previous_names is not stitched to it by one;
                          (e) the loop insight or alert in
                              config/posthog/loop-alert.json differs from what
                              the catalog's budget_per_user_day generates.
                          (d) and (e) read what the project is SYNCED to: a
                          push to master syncs it from the merged files, so a
                          PR passes master's catalog and actions.json as the
                          live ones — its own copies cannot be live until it
                          merges, and checking them failed every such PR.
  sync-actions [--apply]  Create or update the canonical actions so the project
                          matches config/posthog/actions.json. A dry run that
                          prints the plan unless --apply is given.
  sync-loop-alert [--apply]
                          Update the loop insight's query and its alert's
                          threshold to what the catalog generates. A dry run
                          unless --apply is given.

Env contract:
  POSTHOG_PERSONAL_API_KEY  A personal API key. `check` needs the READ_SCOPES
                            below; `sync-actions --apply` also needs action:write,
                            `sync-loop-alert --apply` insight:write and alert:write.
                            Missing, both subcommands fail and say how to make one.
  GITHUB_ACTIONS            On a runner, each failure is also an ::error annotation.

The catalog is read from its generated JSON, so the script needs nothing beyond
the standard library and runs wherever python3 does.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import difflib
from enum import StrEnum
from http import HTTPStatus
import http.client
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_JSON = (
    REPO_ROOT
    / "libs"
    / "shared"
    / "ts"
    / "src"
    / "analytics"
    / "generated"
    / "analytics-catalog.json"
)
PROJECT_JSON = REPO_ROOT / "config" / "posthog" / "project.json"
ACTIONS_JSON = REPO_ROOT / "config" / "posthog" / "actions.json"
LOOP_ALERT_JSON = REPO_ROOT / "config" / "posthog" / "loop-alert.json"

KEY_ENV = "POSTHOG_PERSONAL_API_KEY"
# The /query/ refresh mode that always recomputes; the default serves a cached result.
QUERY_REFRESH = "force_blocking"
READ_SCOPES = (
    "insight:read",
    "project:read",
    "query:read",
    "dashboard:read",
    "action:read",
    "alert:read",
)
WRITE_SCOPE = "action:write"
LOOP_WRITE_SCOPES = ("insight:write", "alert:write")

# The loop detector: one row per (event, distinct_id, IST day); budget_used = events / budget.
LOOP_COLUMN = "budget_used"
LOOP_LABEL_COLUMN = "event_and_id"
LOOP_TIMEZONE = "Asia/Kolkata"
# Above 1 a user emitted more than the event's whole daily budget.
# Also the HAVING floor: a lower one lists every active user's one user:active (budget 1),
# and an alert errors once its rows reach the query's row limit.
LOOP_BUDGET_USED_LIMIT = 1
# PostHog rejects a longer insight description with a 400 (max_length).
POSTHOG_INSIGHT_DESCRIPTION_MAX = 400

# Events and properties the PostHog SDKs and LLM tracing own ($pageview, $ai_generation, $host).
SDK_PREFIX = "$"
# Added to every capture by posthog_properties() in libs/shared/py/analytics/client.py.
ENVELOPE_PROPERTIES = frozenset({"timestamp"})

PROBE_EVENT = "user:signed_up"
PROBE_DAYS = 7
SUGGESTION_CUTOFF = 0.6
PAGE_LIMIT = 100
HTTP_TIMEOUT_S = 30
# A PostHog read that drops mid-body (IncompleteRead), times out or 5xxs is
# retried: one flaky response used to red the analytics check.
HTTP_ATTEMPTS = 4
HTTP_BACKOFF_S = 2.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "PATCH", "PUT", "DELETE"})

JsonValue = dict[str, "JsonValue"] | list["JsonValue"] | str | int | float | bool | None
JsonObject = dict[str, JsonValue]

# A query node that only wraps another one in its "source".
WRAPPER_KINDS = frozenset({"InsightVizNode", "DataVisualizationNode", "DataTableNode"})
SERIES_QUERY_KINDS = frozenset({"TrendsQuery", "FunnelsQuery", "LifecycleQuery", "StickinessQuery"})
# Property filter types that name an event property; person, cohort, session and
# element filters are outside the catalog.
EVENT_PROPERTY_TYPE = "event"
HOGQL_TYPE = "hogql"
ALL_EVENTS_ENTITY = "All events"

# HogQL: string literals and comments are lifted out first, so neither a quoted
# 'properties.x' nor a commented-out comparison is read as a reference.
_LITERAL_OR_COMMENT = re.compile(r"'(?:[^'\\]|\\.)*'|--[^\n]*|/\*.*?\*/", re.DOTALL)
_PLACEHOLDER = "\x00{}\x00"
_LIT = r"\x00(\d+)\x00"
_EVENT_COLUMN = r"(?<![\w.$])(?:(?!properties\.)[A-Za-z_]\w*\.)?event\b"
_EVENT_COMPARED = re.compile(rf"{_EVENT_COLUMN}\s*(?:==|=|!=|<>)\s*{_LIT}")
_EVENT_COMPARED_REVERSED = re.compile(rf"{_LIT}\s*(?:==|=|!=|<>)\s*{_EVENT_COLUMN}")
_EVENT_IN_LIST = re.compile(rf"{_EVENT_COLUMN}\s+(?:NOT\s+)?IN\s*\(([^)]*)\)", re.IGNORECASE)
_PROPERTY = re.compile(
    rf"(?<![\w.$])((?:[A-Za-z_]\w*\.)*)properties(?:\.(\$?\w+)|\[\s*{_LIT}\s*\])"
)
_TABLE_ALIAS = re.compile(
    r"\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)(?:\s+AS)?\s+([A-Za-z_]\w*)", re.IGNORECASE
)
_SQL_KEYWORDS = frozenset(
    [
        "where",
        "left",
        "right",
        "inner",
        "outer",
        "full",
        "cross",
        "join",
        "on",
        "group",
        "order",
        "limit",
        "having",
        "union",
        "prewhere",
        "sample",
        "final",
        "settings",
        "array",
        "any",
        "all",
        "semi",
        "anti",
        "using",
        "as",
        "with",
        "select",
    ]
)
_EVENTS_TABLE = "events"
_PERSON_QUALIFIER = "person"


class PostHogError(RuntimeError):
    """A PostHog API call failed; the message carries the status and response body."""


class JsonShapeError(TypeError):
    """A JSON value is not the shape this script reads it as."""


# ---------------------------------------------------------------------------
# Narrowing JSON values: each raises on another shape rather than defaulting


def _obj(value: JsonValue, what: str) -> JsonObject:
    if isinstance(value, dict):
        return value
    raise JsonShapeError(f"{what}: expected an object, got {value!r:.200}")


def _list(value: JsonValue, what: str) -> list[JsonValue]:
    if isinstance(value, list):
        return value
    raise JsonShapeError(f"{what}: expected a list, got {value!r:.200}")


def _objs(value: JsonValue, what: str) -> list[JsonObject]:
    return [_obj(item, what) for item in _list(value, what)]


def _str(value: JsonValue, what: str) -> str:
    if isinstance(value, str):
        return value
    raise JsonShapeError(f"{what}: expected a string, got {value!r:.200}")


def _int(value: JsonValue, what: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise JsonShapeError(f"{what}: expected an integer, got {value!r:.200}")


def _id(value: JsonValue, what: str) -> int:
    """Read an id inside a stored insight query, which PostHog serves as an int, float or string."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return _int(value, what)


# ---------------------------------------------------------------------------
# The catalog


@dataclass(frozen=True)
class Catalog:
    """Each catalog event's properties and daily budget, and the name each previous name became."""

    properties: Mapping[str, frozenset[str]]
    renamed: Mapping[str, str]
    budgets: Mapping[str, int]

    @classmethod
    def from_doc(cls, doc: Mapping[str, JsonValue]) -> Catalog:
        """Build from the analytics-catalog.json document `mise analytics:types` writes."""
        properties: dict[str, frozenset[str]] = {}
        renamed: dict[str, str] = {}
        budgets: dict[str, int] = {}
        base_sets = {
            name: _schema_properties(schema, f"base_properties.{name}")
            for name, schema in _obj(doc["base_properties"], "base_properties").items()
        }
        for entry in _objs(doc["events"], "events"):
            event = _str(entry["event"], "events[].event")
            own = _schema_properties(entry["properties"], f"{event}.properties")
            base = entry["base_properties"]
            properties[event] = (
                own | base_sets[_str(base, f"{event}.base_properties")] if base else own
            )
            budgets[event] = _int(entry["budget_per_user_day"], f"{event}.budget_per_user_day")
            for old in _list(entry["previous_names"], f"{event}.previous_names"):
                renamed[_str(old, f"{event}.previous_names[]")] = event
        return cls(properties=properties, renamed=renamed, budgets=budgets)

    @classmethod
    def load(cls, path: Path = CATALOG_JSON) -> Catalog:
        """Read the generated catalog JSON."""
        return cls.from_doc(_read_json(path))

    def has_event(self, name: str) -> bool:
        """Whether the catalog defines this event name."""
        return name in self.properties

    def suggest_event(self, name: str) -> str | None:
        """Suggest a renamed event's successor, else the closest name in its domain, else overall."""
        if name in self.renamed:
            return self.renamed[name]
        domain = name.split(":", 1)[0] + ":"
        same_domain = (
            [event for event in self.properties if event.startswith(domain)] if ":" in name else []
        )
        if same_domain:
            return max(
                same_domain, key=lambda event: difflib.SequenceMatcher(None, name, event).ratio()
            )
        return _closest(name, self.properties)


def _schema_properties(schema: JsonValue, what: str) -> frozenset[str]:
    """Return the property names a JSON schema object declares."""
    return frozenset(_obj(_obj(schema, what).get("properties", {}), f"{what}.properties"))


def _closest(name: str, candidates: Iterable[str]) -> str | None:
    matches = difflib.get_close_matches(name, sorted(candidates), n=1, cutoff=SUGGESTION_CUTOFF)
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# (a) Reading an insight's references


class RefKind(StrEnum):
    """What a bad reference names."""

    EVENT = "event"
    PROPERTY = "property"
    ACTION = "action"
    QUERY_KIND = "kind"


@dataclass(frozen=True)
class BadRef:
    """One reference an insight makes that the catalog cannot back."""

    kind: RefKind
    name: str
    suggestion: str | None


@dataclass
class _Refs:
    """What one insight references; a property's scope of None means the whole insight's events."""

    actions: Mapping[int, set[str]]
    events: set[str] = field(default_factory=set)
    scope_events: set[str] = field(default_factory=set)
    action_events: set[str] = field(default_factory=set)
    properties: list[tuple[str, frozenset[str] | None]] = field(default_factory=list)
    unreadable: list[BadRef] = field(default_factory=list)


def hogql_refs(text: str) -> tuple[set[str], set[str]]:
    """Return the event names a HogQL text compares `event` against, and the event properties it reads."""
    literals: list[str] = []

    def lift(match: re.Match[str]) -> str:
        token = match.group(0)
        if not token.startswith("'"):
            return " "
        literals.append(token[1:-1])
        return _PLACEHOLDER.format(len(literals) - 1)

    code = _LITERAL_OR_COMMENT.sub(lift, text)
    events = {literals[int(i)] for i in _EVENT_COMPARED.findall(code)}
    events |= {literals[int(i)] for i in _EVENT_COMPARED_REVERSED.findall(code)}
    for group in _EVENT_IN_LIST.findall(code):
        events |= {literals[int(i)] for i in re.findall(_LIT, group)}

    other_tables = {
        alias.lower()
        for table, alias in _TABLE_ALIAS.findall(code)
        if table.lower() != _EVENTS_TABLE and alias.lower() not in _SQL_KEYWORDS
    }
    properties: set[str] = set()
    for qualifier, dotted, literal in _PROPERTY.findall(code):
        segments = [s.lower() for s in qualifier.split(".") if s]
        if segments and (segments[-1] == _PERSON_QUALIFIER or segments[0] in other_tables):
            continue
        properties.add(dotted or literals[int(literal)])
    return events, properties


def _add_hogql(refs: _Refs, text: str, scope: frozenset[str] | None) -> None:
    events, properties = hogql_refs(text)
    refs.events |= events
    refs.scope_events |= events
    refs.properties.extend((name, scope) for name in properties)


def _add_filters(refs: _Refs, filters: JsonValue, scope: frozenset[str] | None) -> None:
    """Property filters arrive as a list of leaves or as nested AND/OR groups of them."""
    if isinstance(filters, list):
        for item in filters:
            _add_filters(refs, item, scope)
        return
    if not isinstance(filters, dict):
        return
    if "values" in filters and "key" not in filters:
        _add_filters(refs, filters["values"], scope)
        return
    kind = filters.get("type", EVENT_PROPERTY_TYPE)
    if kind == EVENT_PROPERTY_TYPE:
        refs.properties.append((_str(filters["key"], "property filter key"), scope))
    elif kind == HOGQL_TYPE:
        _add_hogql(refs, _str(filters["key"], "hogql filter key"), scope)


def _add_event(refs: _Refs, name: str) -> frozenset[str]:
    refs.events.add(name)
    refs.scope_events.add(name)
    return frozenset({name})


def _add_action(refs: _Refs, action_id: int) -> frozenset[str] | None:
    if action_id not in refs.actions:
        refs.unreadable.append(BadRef(RefKind.ACTION, str(action_id), None))
        return None
    steps = refs.actions[action_id]
    refs.scope_events |= steps
    refs.action_events |= steps
    return frozenset(steps)


def _add_series(refs: _Refs, node: Mapping[str, JsonValue]) -> None:
    kind = node.get("kind")
    if kind == "EventsNode":
        # A null event is "All events": its properties may belong to any of them.
        scope = (
            _add_event(refs, _str(node["event"], "EventsNode.event"))
            if node.get("event")
            else frozenset()
        )
    elif kind == "ActionsNode":
        scope = _add_action(refs, _id(node["id"], "ActionsNode.id"))
    else:
        refs.unreadable.append(BadRef(RefKind.QUERY_KIND, str(kind), None))
        return
    _add_filters(refs, node.get("properties"), scope)
    if node.get("math_property") and node.get("math_property_type", EVENT_PROPERTY_TYPE) in (
        EVENT_PROPERTY_TYPE,
        "event_properties",
    ):
        refs.properties.append((_str(node["math_property"], "math_property"), scope))
    if node.get("math_hogql"):
        _add_hogql(refs, _str(node["math_hogql"], "math_hogql"), scope)


def _add_entity(refs: _Refs, entity: JsonValue) -> None:
    """Add a retention target or returning entity: an event by id or name, or an action by id."""
    if not entity:
        return
    entity = _obj(entity, "retention entity")
    if entity.get("type") == "actions":
        _add_action(refs, _id(entity["id"], "retention action id"))
        return
    name = entity.get("id") or entity.get("name")
    if isinstance(name, str) and name != ALL_EVENTS_ENTITY:
        _add_event(refs, name)


def _add_breakdowns(refs: _Refs, breakdown_filter: JsonValue) -> None:
    if not breakdown_filter:
        return
    breakdown_filter = _obj(breakdown_filter, "breakdownFilter")
    pairs: list[tuple[JsonValue, JsonValue]] = [
        (b.get("type", EVENT_PROPERTY_TYPE), b["property"])
        for b in _objs(breakdown_filter.get("breakdowns") or [], "breakdownFilter.breakdowns")
    ]
    single = breakdown_filter.get("breakdown")
    single_type = breakdown_filter.get("breakdown_type") or EVENT_PROPERTY_TYPE
    for value in single if isinstance(single, list) else [single] if single is not None else []:
        pairs.append((single_type, value))
    for kind, value in pairs:
        if kind == EVENT_PROPERTY_TYPE and isinstance(value, str):
            refs.properties.append((value, None))
        elif kind == HOGQL_TYPE:
            _add_hogql(refs, _str(value, "hogql breakdown"), None)


def _add_query(refs: _Refs, node: JsonValue) -> None:
    if not node:
        refs.unreadable.append(BadRef(RefKind.QUERY_KIND, "no query", None))
        return
    node = _obj(node, "insight query")
    kind = node.get("kind")
    if kind in WRAPPER_KINDS:
        _add_query(refs, node.get("source"))
        return
    if kind == "HogQLQuery":
        _add_hogql(refs, _str(node["query"], "HogQLQuery.query"), None)
        return
    if kind in SERIES_QUERY_KINDS:
        for series in _objs(node.get("series", []), "series"):
            _add_series(refs, series)
        funnels = _obj(node.get("funnelsFilter") or {}, "funnelsFilter")
        for exclusion in _objs(funnels.get("exclusions") or [], "funnelsFilter.exclusions"):
            _add_series(refs, exclusion)
        if node.get("funnelAggregateByHogQL"):
            _add_hogql(refs, _str(node["funnelAggregateByHogQL"], "funnelAggregateByHogQL"), None)
    elif kind == "RetentionQuery":
        retention = _obj(node.get("retentionFilter") or {}, "retentionFilter")
        _add_entity(refs, retention.get("targetEntity"))
        _add_entity(refs, retention.get("returningEntity"))
    # A paths query's own filters name URLs and event types, so only its properties
    # are read; any other kind is a query this reader does not understand.
    elif kind != "PathsQuery":
        refs.unreadable.append(BadRef(RefKind.QUERY_KIND, str(kind), None))
        return
    _add_filters(refs, node.get("properties"), None)
    _add_breakdowns(refs, node.get("breakdownFilter"))


def _property_finding(name: str, scope: frozenset[str], catalog: Catalog) -> BadRef | None:
    if name.startswith(SDK_PREFIX) or name in ENVELOPE_PROPERTIES:
        return None
    if not scope:
        candidates: set[str] = set().union(*catalog.properties.values())
    elif any(event.startswith(SDK_PREFIX) for event in scope):
        # An SDK event carries properties the catalog does not describe.
        return None
    else:
        live = [event for event in scope if catalog.has_event(event)]
        if not live:
            # Every event it could belong to is already flagged as dead.
            return None
        candidates = set().union(*(catalog.properties[event] for event in live))
    if name in candidates:
        return None
    return BadRef(RefKind.PROPERTY, name, _closest(name, candidates))


def bad_refs(query: JsonValue, catalog: Catalog, actions: Mapping[int, set[str]]) -> list[BadRef]:
    """Every event, property, action or query kind in one insight that the catalog cannot back."""
    refs = _Refs(actions=actions)
    _add_query(refs, query)
    found = set(refs.unreadable)
    for event in refs.events:
        if not event.startswith(SDK_PREFIX) and not catalog.has_event(event):
            found.add(BadRef(RefKind.EVENT, event, catalog.suggest_event(event)))
    # A continuity action deliberately steps on a previous name, so only a step that is neither is dead.
    for event in refs.action_events - refs.events:
        if (
            not event.startswith(SDK_PREFIX)
            and not catalog.has_event(event)
            and event not in catalog.renamed
        ):
            found.add(BadRef(RefKind.EVENT, event, catalog.suggest_event(event)))
    insight_scope = frozenset(refs.scope_events)
    for name, scope in refs.properties:
        finding = _property_finding(name, insight_scope if scope is None else scope, catalog)
        if finding:
            found.add(finding)
    return sorted(found, key=lambda bad: (bad.kind, bad.name))


def describe(bad: BadRef, catalog: Catalog) -> str:
    """One finding as the reader acts on it."""
    if bad.kind is RefKind.QUERY_KIND:
        return f"query kind {bad.name} — analytics.py cannot read it; teach _add_query this kind"
    if bad.kind is RefKind.ACTION:
        return f"action {bad.name} — no such action in the project"
    text = f"{bad.kind} {bad.name} — not in the catalog"
    if bad.suggestion and catalog.renamed.get(bad.name) == bad.suggestion:
        return f"{text} (renamed to {bad.suggestion})"
    if bad.suggestion:
        return f"{text} (did you mean {bad.suggestion}?)"
    return text


# ---------------------------------------------------------------------------
# (b) settings, (c) probe, (d) actions


def settings_diff(expected: Mapping[str, JsonValue], live: Mapping[str, JsonValue]) -> list[str]:
    """One line per checked-in setting the live project does not match."""
    diffs = []
    for key, value in expected.items():
        if key not in live:
            diffs.append(
                f"{key}: missing from the project (config/posthog/project.json has {json.dumps(value)})"
            )
        elif live[key] != value:
            diffs.append(
                f"{key}: config/posthog/project.json has {json.dumps(value)} but the project has {json.dumps(live[key])}"
            )
    return diffs


def probe_failure(filtered: int, unfiltered: int) -> str | None:
    """Why the test-account filter is broken, or None when the probe is consistent."""
    if filtered == 0 and unfiltered > 0:
        return (
            f"{PROBE_EVENT} over the last {PROBE_DAYS} days: {unfiltered} without the test-account filter, "
            "0 with it — the filter drops every event, so every filtered tile reads 0"
        )
    return None


def _clean(value: JsonValue) -> JsonValue:
    """Drop null keys recursively, which is how the API pads every unused action field."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def normalize_step(step: Mapping[str, JsonValue]) -> JsonObject:
    """Strip an action step of its nulls, empty filters, and *_matching modes for unset fields."""
    clean = _obj(_clean(dict(step)), "action step")
    for matched in ("url", "text", "href"):
        if matched not in clean:
            clean.pop(f"{matched}_matching", None)
    if not clean.get("properties"):
        clean.pop("properties", None)
    return clean


def _comparable(action: Mapping[str, JsonValue]) -> JsonObject:
    return {
        "description": action.get("description", ""),
        "tags": sorted(_list(action.get("tags") or [], "tags"), key=lambda t: _str(t, "tag")),
        "steps": [normalize_step(step) for step in _objs(action.get("steps") or [], "steps")],
    }


def action_diff(
    expected: Sequence[Mapping[str, JsonValue]], live: Sequence[Mapping[str, JsonValue]], tag: str
) -> list[str]:
    """One line per canonical action that is missing, differs, or is tagged canonical but unlisted."""
    live_by_name = {action["name"]: action for action in live}
    diffs = []
    for action in expected:
        name = action["name"]
        if name not in live_by_name:
            diffs.append(f"{name}: missing from the project")
            continue
        want, have = _comparable(action), _comparable(live_by_name[name])
        diffs.extend(
            f"{name}: {key} differ (file: {json.dumps(want[key])}; project: {json.dumps(have[key])})"
            for key in want
            if want[key] != have[key]
        )
    listed = {action["name"] for action in expected}
    diffs.extend(
        f"{action['name']}: tagged {tag} in the project but not in config/posthog/actions.json"
        for action in sorted(live, key=lambda a: _str(a["name"], "action name"))
        if tag in _list(action.get("tags") or [], "tags") and action["name"] not in listed
    )
    return diffs


def _step_events(action: Mapping[str, JsonValue]) -> set[str]:
    return {
        _str(step["event"], "action step event")
        for step in _objs(action.get("steps") or [], "steps")
        if step.get("event")
    }


def coverage_gaps(catalog: Catalog, expected: Sequence[Mapping[str, JsonValue]]) -> list[str]:
    """List renames no action stitches together, and steps naming neither a catalog event nor a previous name."""
    gaps = [
        f"{old} -> {new}: no canonical action has both as steps"
        for old, new in sorted(catalog.renamed.items())
        if not any({old, new} <= _step_events(action) for action in expected)
    ]
    for action in expected:
        gaps.extend(
            f"{action['name']}: step {event} is not a catalog event or a previous name"
            for event in sorted(_step_events(action))
            if not event.startswith(SDK_PREFIX)
            and not catalog.has_event(event)
            and event not in catalog.renamed
        )
    return gaps


# ---------------------------------------------------------------------------
# (e) the loop alert, generated from the catalog's budgets


def loop_insight(catalog: Catalog, spec: Mapping[str, JsonValue]) -> JsonObject:
    """Generate the loop insight's name, description and query: each (event, user, IST day) count over its budget."""
    events = sorted(catalog.budgets)
    names = ", ".join(f"'{event}'" for event in events)
    budgets = ", ".join(str(catalog.budgets[event]) for event in events)
    hogql = f"""SELECT
    concat(event, ' / ', if(position(distinct_id, '@') > 0, concat('email#', toString(cityHash64(distinct_id) % 100000)), distinct_id)) AS {LOOP_LABEL_COLUMN},
    toDate(toTimeZone(timestamp, '{LOOP_TIMEZONE}')) AS day,
    count() AS events,
    transform(event, [{names}], [{budgets}], {spec["uncatalogued_budget_per_user_day"]}) AS budget,
    events / budget AS {LOOP_COLUMN}
FROM events
WHERE timestamp >= toStartOfDay(toTimeZone(now(), '{LOOP_TIMEZONE}')) - INTERVAL 1 DAY
    AND NOT startsWith(event, '{spec["excluded_event_prefix"]}')
    AND {{filters}}
GROUP BY event, distinct_id, day
HAVING {LOOP_COLUMN} > {LOOP_BUDGET_USED_LIMIT}
ORDER BY {LOOP_COLUMN} DESC"""  # noqa: S608 -- catalog-validated domain:action names, int budgets and checked-in config, no runtime input
    insight = _obj(spec["insight"], "loop-alert.json insight")
    return {
        "name": insight["name"],
        "description": insight["description"],
        "query": {
            "kind": "DataVisualizationNode",
            "source": {
                "kind": "HogQLQuery",
                "query": hogql,
                "filters": {"filterTestAccounts": True},
            },
            "display": "ActionsTable",
        },
    }


def loop_alert(spec: Mapping[str, JsonValue]) -> JsonObject:
    """Generate the loop alert as PATCH takes it: fire when any row used more than its whole budget."""
    return {
        "name": _obj(spec["alert"], "loop-alert.json alert")["name"],
        "insight": _obj(spec["insight"], "loop-alert.json insight")["id"],
        "threshold": {
            "configuration": {"type": "absolute", "bounds": {"upper": LOOP_BUDGET_USED_LIMIT}}
        },
        "config": {
            "type": "HogQLAlertConfig",
            "column": LOOP_COLUMN,
            "evaluation": "any_row",
            "label_column": LOOP_LABEL_COLUMN,
        },
    }


def _live_alert_fields(live: Mapping[str, JsonValue]) -> JsonObject:
    """Reshape a GET alert into loop_alert's shape: the insight by id, the threshold without its own id."""
    return {
        "name": live["name"],
        "insight": _obj(live["insight"], "alert insight")["id"],
        "threshold": {"configuration": _obj(live["threshold"], "alert threshold")["configuration"]},
        "config": live["config"],
    }


def _drifted(want: Mapping[str, JsonValue], have: Mapping[str, JsonValue]) -> list[str]:
    return [key for key in want if have.get(key) != want[key]]


def loop_alert_diff(
    catalog: Catalog,
    spec: Mapping[str, JsonValue],
    live_insight: Mapping[str, JsonValue],
    live_alert: Mapping[str, JsonValue],
) -> list[str]:
    """One line per field of the live loop insight or alert that differs from what the catalog generates."""
    fix = "run `python3 scripts/ci/analytics.py sync-loop-alert --apply`"
    insight = loop_insight(catalog, spec)
    diffs = [
        f"insight {live_insight['id']}: {key} differs from what the catalog generates — {fix}"
        for key in _drifted(insight, live_insight)
    ]
    alert, have = loop_alert(spec), _live_alert_fields(live_alert)
    diffs.extend(
        f"alert {live_alert['id']}: {key} differs (generated: {json.dumps(alert[key])}; "
        f"project: {json.dumps(have[key])}) — {fix}"
        for key in _drifted(alert, have)
    )
    return diffs


# ---------------------------------------------------------------------------
# The PostHog REST API


class PostHog:
    """The handful of PostHog REST calls the checks make, authenticated with a personal API key."""

    def __init__(self, host: str, project_id: int, key: str) -> None:
        """Bind to one project on an https host."""
        parts = urlsplit(host)
        if parts.scheme != "https" or not parts.netloc:
            raise ValueError(f"PostHog host must be an https URL, got {host!r}")
        self.netloc = parts.netloc
        self.base = f"/api/projects/{project_id}"
        self.key = key

    def _send(
        self, method: str, path: str, body: Mapping[str, JsonValue] | None
    ) -> tuple[int, str]:
        connection = http.client.HTTPSConnection(self.netloc, timeout=HTTP_TIMEOUT_S)
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        try:
            connection.request(
                method, path, json.dumps(body) if body is not None else None, headers
            )
            response = connection.getresponse()
            return response.status, response.read().decode(errors="replace")
        finally:
            connection.close()

    def _request(
        self,
        method: str,
        path: str,
        body: Mapping[str, JsonValue] | None = None,
        *,
        idempotent: bool | None = None,
    ) -> JsonObject:
        """Send one call, retrying a read or idempotent write on a dropped response, timeout, 429 or 5xx.

        A POST that creates is never retried: it may have landed.
        """
        retryable = method in IDEMPOTENT_METHODS if idempotent is None else idempotent
        attempts = HTTP_ATTEMPTS if retryable else 1
        for attempt in range(1, attempts + 1):
            try:
                status, payload = self._send(method, path, body)
            except (http.client.HTTPException, OSError) as exc:
                failure = f"{type(exc).__name__}: {exc}"
            else:
                if status < HTTPStatus.BAD_REQUEST:
                    return _obj(json.loads(payload), f"{method} {path}")
                failure = f"HTTP {status} {payload[:500]}"
                if status not in RETRYABLE_STATUS:
                    raise PostHogError(f"{method} {path}: {failure}")
            if attempt == attempts:
                raise PostHogError(f"{method} {path}: {failure} (after {attempt} attempt(s))")
            delay = HTTP_BACKOFF_S * 2 ** (attempt - 1)
            print(
                f"[posthog] {method} {path}: {failure}; retry {attempt}/{attempts - 1} in {delay:g}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def _all(self, path: str) -> list[JsonObject]:
        """Follow the API's `next` links; each must stay on this host."""
        url: str | None = f"{self.base}/{path}?limit={PAGE_LIMIT}"
        items: list[JsonObject] = []
        while url:
            page = self._request("GET", url)
            items.extend(_objs(page["results"], f"{path} results"))
            next_page = page.get("next")
            url = None if next_page is None else _str(next_page, f"{path} next")
            if url:
                parts = urlsplit(url)
                if parts.netloc != self.netloc:
                    raise PostHogError(f"pagination left {self.netloc} for {parts.netloc}")
                url = f"{parts.path}?{parts.query}"
        return items

    def project(self) -> JsonObject:
        """Fetch the project, settings included."""
        return self._request("GET", f"{self.base}/")

    def insights(self) -> list[JsonObject]:
        """Fetch every saved, non-deleted insight with its query and dashboards."""
        return [i for i in self._all("insights/") if i.get("saved")]

    def dashboards(self) -> list[JsonObject]:
        """Fetch every non-deleted dashboard."""
        return self._all("dashboards/")

    def actions(self) -> list[JsonObject]:
        """Fetch every non-deleted action."""
        return self._all("actions/")

    def hogql(
        self, query: str, values: Mapping[str, JsonValue] | None = None
    ) -> list[list[JsonValue]]:
        """Run a HogQL query with {placeholder} values and return its rows."""
        node: JsonObject = {"kind": "HogQLQuery", "query": query, "values": dict(values or {})}
        return [_list(row, "HogQL row") for row in self._query(node)]

    def probe(self, filter_test_accounts: bool) -> int:
        """Count the probe event over the probe window, with the test-account filter on or off."""
        # The same query node a dashboard trends tile runs, so the filter is applied exactly as it is there.
        query: JsonObject = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": PROBE_EVENT, "math": "total"}],
            "dateRange": {"date_from": f"-{PROBE_DAYS}d"},
            "filterTestAccounts": filter_test_accounts,
        }
        [series] = self._query(query)
        count = _obj(series, "trends series")["count"]
        if not isinstance(count, int | float):
            raise JsonShapeError(f"trends series count: expected a number, got {count!r:.200}")
        return int(count)

    def _query(self, node: JsonObject) -> list[JsonValue]:
        """Run a query node and return its rows, never from PostHog's result cache."""
        # A cached read after a write (a merge, a filter change) reports the state before it.
        response = self._request(
            "POST",
            f"{self.base}/query/",
            {"query": node, "refresh": QUERY_REFRESH},
            idempotent=True,
        )
        return _list(response["results"], "query results")

    def create_action(self, action: Mapping[str, JsonValue]) -> None:
        """Create an action."""
        self._request("POST", f"{self.base}/actions/", action)

    def update_action(self, action_id: int, action: Mapping[str, JsonValue]) -> None:
        """Overwrite an action's name, description, tags and steps."""
        self._request("PATCH", f"{self.base}/actions/{action_id}/", action)

    def insight(self, insight_id: int) -> JsonObject:
        """Fetch one insight by id."""
        return self._request("GET", f"{self.base}/insights/{insight_id}/")

    def update_insight(self, insight_id: int, fields: Mapping[str, JsonValue]) -> None:
        """Overwrite the given fields of an insight."""
        self._request("PATCH", f"{self.base}/insights/{insight_id}/", fields)

    def alert(self, alert_id: str) -> JsonObject:
        """Fetch one alert by id, its insight and threshold included."""
        return self._request("GET", f"{self.base}/alerts/{alert_id}/")

    def update_alert(self, alert_id: str, fields: Mapping[str, JsonValue]) -> None:
        """Overwrite the given fields of an alert."""
        self._request("PATCH", f"{self.base}/alerts/{alert_id}/", fields)


# ---------------------------------------------------------------------------
# Subcommands


def client_from_env(
    scopes: Sequence[str], *, key_env: str = KEY_ENV, project_json: Path = PROJECT_JSON
) -> PostHog | None:
    """Return a client for the project in project_json, or print how to make the missing key."""
    key = os.environ.get(key_env, "")
    project = _read_json(project_json)
    if key:
        return PostHog(
            _str(project["host"], f"{project_json} host"),
            _int(project["project_id"], f"{project_json} project_id"),
            key,
        )
    print(
        f"{key_env} is not set. Create a personal API key at {project['host']}/settings/user-api-keys "
        f"scoped to project {project['project_id']} with {', '.join(scopes)}, then export it "
        f"(CI reads it from the repository secret {key_env}).",
        file=sys.stderr,
    )
    if os.environ.get("GITHUB_ACTIONS"):
        print(
            f"::error title=analytics check::{key_env} secret is missing; nothing was checked",
            file=sys.stderr,
        )
    return None


def _read_json(path: Path) -> JsonObject:
    return _obj(json.loads(path.read_text(encoding="utf-8")), str(path))


def _report(section: str, failures: list[str]) -> None:
    if not failures:
        print(f"✓ {section}")
        return
    for failure in failures:
        print(f"✗ {failure}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title={section}::{failure}")


def _read_actions(path: Path) -> tuple[str, list[JsonObject]]:
    """Return an actions.json file's canonical tag and its actions."""
    doc = _read_json(path)
    return _str(doc["tag"], f"{path} tag"), _objs(doc["actions"], f"{path} actions")


def _loop_ids(spec: Mapping[str, JsonValue]) -> tuple[int, str]:
    """Return the ids of the loop insight and of its alert from loop-alert.json."""
    insight = _obj(spec["insight"], "loop-alert.json insight")
    alert = _obj(spec["alert"], "loop-alert.json alert")
    return _int(insight["id"], "loop-alert.json insight.id"), _str(
        alert["id"], "loop-alert.json alert.id"
    )


def _dashboard_ids(insight: Mapping[str, JsonValue]) -> set[int]:
    """Return the ids of the dashboards an insight sits on."""
    return {
        _int(d, "insight dashboard id")
        for d in _list(insight.get("dashboards") or [], "insight dashboards")
    }


def _insight_failures(client: PostHog, catalog: Catalog) -> list[str]:
    dashboards = {
        _int(d["id"], "dashboard id"): _str(d["name"], "dashboard name")
        for d in client.dashboards()
    }
    actions = {_int(a["id"], "action id"): _step_events(a) for a in client.actions()}
    insights = client.insights()
    on_dashboards = [i for i in insights if _dashboard_ids(i) & dashboards.keys()]
    failures: list[str] = []
    for insight in on_dashboards:
        where = ", ".join(sorted(dashboards[d] for d in _dashboard_ids(insight) if d in dashboards))
        failures.extend(
            f'{where} › "{insight.get("name") or insight.get("derived_name")}" (insight {insight["id"]}) › '
            f"{describe(bad, catalog)}"
            for bad in bad_refs(insight.get("query"), catalog, actions)
        )
    print(
        f"(a) {len(on_dashboards)} saved insights on {len(dashboards)} live dashboards read; "
        f"{len(insights) - len(on_dashboards)} saved insights on no live dashboard not read"
    )
    return failures


def cmd_check(args: list[str]) -> int:
    """Run the five checks and exit non-zero on any failure."""
    parser = argparse.ArgumentParser(prog="analytics.py check")
    parser.add_argument(
        "--live-catalog",
        type=Path,
        default=None,
        help="catalog the live actions and loop alert are held to; a PR passes master's, the one a merge syncs",
    )
    parser.add_argument(
        "--live-actions",
        type=Path,
        default=None,
        help="actions.json the live canonical actions are held to; a PR passes master's",
    )
    opts = parser.parse_args(args)
    client = client_from_env(READ_SCOPES)
    if client is None:
        return 1
    catalog = Catalog.load()
    live_catalog = Catalog.load(opts.live_catalog or CATALOG_JSON)
    tag, expected = _read_actions(opts.live_actions or ACTIONS_JSON)

    insight_failures = _insight_failures(client, catalog)
    _report("insights reference only catalog events and properties", insight_failures)

    settings = _obj(_read_json(PROJECT_JSON)["settings"], f"{PROJECT_JSON} settings")
    settings_failures = settings_diff(settings, client.project())
    _report("project settings match config/posthog/project.json", settings_failures)

    filtered, unfiltered = (
        client.probe(filter_test_accounts=True),
        client.probe(filter_test_accounts=False),
    )
    print(
        f"(c) {PROBE_EVENT}, last {PROBE_DAYS} days: {filtered} filtered, {unfiltered} unfiltered"
    )
    probe_failures = [f] if (f := probe_failure(filtered, unfiltered)) else []
    _report("the test-account filter keeps real events", probe_failures)

    action_failures = action_diff(expected, client.actions(), tag)
    action_failures += coverage_gaps(live_catalog, expected)
    _report(
        "canonical actions match config/posthog/actions.json and cover every rename",
        action_failures,
    )

    spec = _read_json(LOOP_ALERT_JSON)
    insight_id, alert_id = _loop_ids(spec)
    loop_failures = loop_alert_diff(
        live_catalog, spec, client.insight(insight_id), client.alert(alert_id)
    )
    _report("the loop alert divides by the catalog's budgets", loop_failures)

    failed = (
        insight_failures or settings_failures or probe_failures or action_failures or loop_failures
    )
    return 1 if failed else 0


def cmd_sync_actions(args: list[str]) -> int:
    """Print, or with --apply perform, the creates and updates that make the project match the file."""
    parser = argparse.ArgumentParser(prog="analytics.py sync-actions")
    parser.add_argument(
        "--apply", action="store_true", help="perform the plan instead of printing it"
    )
    opts = parser.parse_args(args)
    client = client_from_env((*READ_SCOPES, WRITE_SCOPE) if opts.apply else READ_SCOPES)
    if client is None:
        return 1
    tag, expected = _read_actions(ACTIONS_JSON)
    live = {_str(action["name"], "action name"): action for action in client.actions()}
    planned = 0
    for action in expected:
        payload = {k: action[k] for k in ("name", "description", "tags", "steps")}
        current = live.get(_str(action["name"], "action name"))
        if current is None:
            print(f"create  {action['name']}")
            if opts.apply:
                client.create_action(payload)
        elif _comparable(current) != _comparable(action):
            print(f"update  {action['name']} (action {current['id']})")
            if opts.apply:
                client.update_action(_int(current["id"], "action id"), payload)
        else:
            continue
        planned += 1
    listed = {action["name"] for action in expected}
    for name, action in sorted(live.items()):
        if tag in _list(action.get("tags") or [], "tags") and name not in listed:
            print(f"left    {name} (action {action['id']}): tagged {tag} but not in the file")
    verb = "applied" if opts.apply else "planned (dry run; re-run with --apply to perform)"
    print(f"{planned} change(s) {verb}")
    return 0


def cmd_sync_loop_alert(args: list[str]) -> int:
    """Print, or with --apply perform, the updates that make the loop insight and alert match the catalog."""
    parser = argparse.ArgumentParser(prog="analytics.py sync-loop-alert")
    parser.add_argument(
        "--apply", action="store_true", help="perform the plan instead of printing it"
    )
    opts = parser.parse_args(args)
    client = client_from_env((*READ_SCOPES, *LOOP_WRITE_SCOPES) if opts.apply else READ_SCOPES)
    if client is None:
        return 1
    catalog, spec = Catalog.load(), _read_json(LOOP_ALERT_JSON)
    insight_id, alert_id = _loop_ids(spec)
    insight, alert = loop_insight(catalog, spec), loop_alert(spec)
    planned = 0
    if drifted := _drifted(insight, client.insight(insight_id)):
        print(f"update  insight {insight_id}: {', '.join(drifted)}")
        if opts.apply:
            client.update_insight(insight_id, insight)
        planned += 1
    if drifted := _drifted(alert, _live_alert_fields(client.alert(alert_id))):
        print(f"update  alert {alert_id}: {', '.join(drifted)}")
        if opts.apply:
            client.update_alert(alert_id, alert)
        planned += 1
    verb = "applied" if opts.apply else "planned (dry run; re-run with --apply to perform)"
    print(f"{planned} change(s) {verb}")
    return 0


COMMANDS = {
    "check": cmd_check,
    "sync-actions": cmd_sync_actions,
    "sync-loop-alert": cmd_sync_loop_alert,
}


def main(argv: list[str]) -> int:
    """Dispatch to a subcommand; exit 2 with the usage on an unknown one."""
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: analytics.py {{{'|'.join(COMMANDS)}}} [args]", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
