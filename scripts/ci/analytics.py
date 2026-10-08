#!/usr/bin/env python3
"""analytics.py — the PostHog side of the event catalog contract.

Subcommands:
  check                   Fail when the PostHog project drifts from the repo:
                          (a) a saved insight on a live dashboard references an
                              event or property the catalog does not have;
                          (b) the project settings differ from
                              config/posthog/project.json;
                          (c) the test-account filter drops every user:signed_up
                              of the last 7 days that the unfiltered count sees;
                          (d) the canonical actions differ from
                              config/posthog/actions.json, or a catalog event's
                              previous_names is not stitched to it by one.
  sync-actions [--apply]  Create or update the canonical actions so the project
                          matches config/posthog/actions.json. A dry run that
                          prints the plan unless --apply is given.

Env contract:
  POSTHOG_PERSONAL_API_KEY  A personal API key. `check` needs the READ_SCOPES
                            below; `sync-actions --apply` also needs action:write.
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

KEY_ENV = "POSTHOG_PERSONAL_API_KEY"
READ_SCOPES = ("insight:read", "project:read", "query:read", "dashboard:read", "action:read")
WRITE_SCOPE = "action:write"

# Events and properties the PostHog SDKs and LLM tracing own ($pageview, $ai_generation, $host).
SDK_PREFIX = "$"
# Added to every capture by posthog_properties() in libs/shared/py/analytics/client.py.
ENVELOPE_PROPERTIES = frozenset({"timestamp"})

PROBE_EVENT = "user:signed_up"
PROBE_DAYS = 7
# {filters} is where PostHog splices the project's test-account filter in.
PROBE_HOGQL = (
    "SELECT count() FROM events "
    "WHERE event = {event} AND timestamp > now() - toIntervalDay({days}) AND {filters}"
)
SUGGESTION_CUTOFF = 0.6
PAGE_LIMIT = 100
HTTP_TIMEOUT_S = 30

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


# ---------------------------------------------------------------------------
# The catalog


@dataclass(frozen=True)
class Catalog:
    """Each catalog event's properties, and the name each previous name became."""

    properties: Mapping[str, frozenset[str]]
    renamed: Mapping[str, str]

    @classmethod
    def from_doc(cls, doc: Mapping[str, JsonValue]) -> Catalog:
        """Build from the analytics-catalog.json document `mise analytics:types` writes."""
        properties: dict[str, frozenset[str]] = {}
        renamed: dict[str, str] = {}
        base_sets = {
            name: frozenset(schema.get("properties", {}))
            for name, schema in doc["base_properties"].items()
        }
        for entry in doc["events"]:
            own = frozenset(entry["properties"].get("properties", {}))
            base = entry["base_properties"]
            properties[entry["event"]] = own | base_sets[base] if base else own
            for old in entry["previous_names"]:
                renamed[old] = entry["event"]
        return cls(properties=properties, renamed=renamed)

    @classmethod
    def load(cls, path: Path = CATALOG_JSON) -> Catalog:
        """Read the generated catalog JSON."""
        return cls.from_doc(json.loads(path.read_text(encoding="utf-8")))

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
        refs.properties.append((filters["key"], scope))
    elif kind == HOGQL_TYPE:
        _add_hogql(refs, filters["key"], scope)


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
        scope = _add_event(refs, node["event"]) if node.get("event") else frozenset()
    elif kind == "ActionsNode":
        scope = _add_action(refs, node["id"])
    else:
        refs.unreadable.append(BadRef(RefKind.QUERY_KIND, str(kind), None))
        return
    _add_filters(refs, node.get("properties"), scope)
    if node.get("math_property") and node.get("math_property_type", EVENT_PROPERTY_TYPE) in (
        EVENT_PROPERTY_TYPE,
        "event_properties",
    ):
        refs.properties.append((node["math_property"], scope))
    if node.get("math_hogql"):
        _add_hogql(refs, node["math_hogql"], scope)


def _add_entity(refs: _Refs, entity: Mapping[str, JsonValue] | None) -> None:
    """Add a retention target or returning entity: an event by id or name, or an action by id."""
    if not entity:
        return
    if entity.get("type") == "actions":
        _add_action(refs, int(entity["id"]))
        return
    name = entity.get("id") or entity.get("name")
    if isinstance(name, str) and name != ALL_EVENTS_ENTITY:
        _add_event(refs, name)


def _add_breakdowns(refs: _Refs, breakdown_filter: Mapping[str, JsonValue] | None) -> None:
    if not breakdown_filter:
        return
    pairs: list[tuple[str, JsonValue]] = [
        (b.get("type", EVENT_PROPERTY_TYPE), b["property"])
        for b in breakdown_filter.get("breakdowns") or []
    ]
    single = breakdown_filter.get("breakdown")
    single_type = breakdown_filter.get("breakdown_type") or EVENT_PROPERTY_TYPE
    for value in single if isinstance(single, list) else [single] if single is not None else []:
        pairs.append((single_type, value))
    for kind, value in pairs:
        if kind == EVENT_PROPERTY_TYPE and isinstance(value, str):
            refs.properties.append((value, None))
        elif kind == HOGQL_TYPE:
            _add_hogql(refs, value, None)


def _add_query(refs: _Refs, node: Mapping[str, JsonValue] | None) -> None:
    if not node:
        refs.unreadable.append(BadRef(RefKind.QUERY_KIND, "no query", None))
        return
    kind = node.get("kind")
    if kind in WRAPPER_KINDS:
        _add_query(refs, node.get("source"))
        return
    if kind == "HogQLQuery":
        _add_hogql(refs, node["query"], None)
        return
    if kind in SERIES_QUERY_KINDS:
        for series in node.get("series", []):
            _add_series(refs, series)
        for exclusion in (node.get("funnelsFilter") or {}).get("exclusions") or []:
            _add_series(refs, exclusion)
        if node.get("funnelAggregateByHogQL"):
            _add_hogql(refs, node["funnelAggregateByHogQL"], None)
    elif kind == "RetentionQuery":
        retention = node.get("retentionFilter") or {}
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


def bad_refs(
    query: Mapping[str, JsonValue] | None, catalog: Catalog, actions: Mapping[int, set[str]]
) -> list[BadRef]:
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
    clean = _clean(dict(step))
    for matched in ("url", "text", "href"):
        if matched not in clean:
            clean.pop(f"{matched}_matching", None)
    if not clean.get("properties"):
        clean.pop("properties", None)
    return clean


def _comparable(action: Mapping[str, JsonValue]) -> JsonObject:
    return {
        "description": action.get("description", ""),
        "tags": sorted(action.get("tags") or []),
        "steps": [normalize_step(step) for step in action.get("steps") or []],
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
        for action in sorted(live, key=lambda a: a["name"])
        if tag in (action.get("tags") or []) and action["name"] not in listed
    )
    return diffs


def _step_events(action: Mapping[str, JsonValue]) -> set[str]:
    return {step["event"] for step in action.get("steps") or [] if step.get("event")}


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

    def _request(
        self, method: str, path: str, body: Mapping[str, JsonValue] | None = None
    ) -> JsonObject:
        connection = http.client.HTTPSConnection(self.netloc, timeout=HTTP_TIMEOUT_S)
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        try:
            connection.request(
                method, path, json.dumps(body) if body is not None else None, headers
            )
            response = connection.getresponse()
            payload = response.read().decode(errors="replace")
        finally:
            connection.close()
        if response.status >= HTTPStatus.BAD_REQUEST:
            raise PostHogError(f"{method} {path}: HTTP {response.status} {payload[:500]}")
        return json.loads(payload)

    def _all(self, path: str) -> list[JsonObject]:
        """Follow the API's `next` links; each must stay on this host."""
        url: str | None = f"{self.base}/{path}?limit={PAGE_LIMIT}"
        items: list[JsonObject] = []
        while url:
            page = self._request("GET", url)
            items.extend(page["results"])
            url = page.get("next")
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

    def probe(self, filter_test_accounts: bool) -> int:
        """Count the probe event over the probe window, with the test-account filter on or off."""
        query = {
            "kind": "HogQLQuery",
            "query": PROBE_HOGQL,
            "values": {"event": PROBE_EVENT, "days": PROBE_DAYS},
            "filters": {"filterTestAccounts": filter_test_accounts},
        }
        return int(self._request("POST", f"{self.base}/query/", {"query": query})["results"][0][0])

    def create_action(self, action: Mapping[str, JsonValue]) -> None:
        """Create an action."""
        self._request("POST", f"{self.base}/actions/", action)

    def update_action(self, action_id: int, action: Mapping[str, JsonValue]) -> None:
        """Overwrite an action's name, description, tags and steps."""
        self._request("PATCH", f"{self.base}/actions/{action_id}/", action)


# ---------------------------------------------------------------------------
# Subcommands


def _client(scopes: Sequence[str]) -> PostHog | None:
    key = os.environ.get(KEY_ENV, "")
    project = _read_json(PROJECT_JSON)
    if key:
        return PostHog(project["host"], project["project_id"], key)
    print(
        f"{KEY_ENV} is not set. Create a personal API key at {project['host']}/settings/user-api-keys "
        f"scoped to project {project['project_id']} with {', '.join(scopes)}, then export it "
        f"(CI reads it from the repository secret {KEY_ENV}).",
        file=sys.stderr,
    )
    if os.environ.get("GITHUB_ACTIONS"):
        print(
            f"::error title=analytics check::{KEY_ENV} secret is missing; nothing was checked",
            file=sys.stderr,
        )
    return None


def _read_json(path: Path) -> JsonObject:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(section: str, failures: list[str]) -> None:
    if not failures:
        print(f"✓ {section}")
        return
    for failure in failures:
        print(f"✗ {failure}")
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title={section}::{failure}")


def _insight_failures(client: PostHog, catalog: Catalog) -> list[str]:
    dashboards = {d["id"]: d["name"] for d in client.dashboards()}
    actions = {a["id"]: _step_events(a) for a in client.actions()}
    insights = client.insights()
    on_dashboards = [i for i in insights if set(i.get("dashboards") or []) & dashboards.keys()]
    failures = []
    for insight in on_dashboards:
        where = ", ".join(sorted(dashboards[d] for d in insight["dashboards"] if d in dashboards))
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


def cmd_check(_args: list[str]) -> int:
    """Run the four checks and exit non-zero on any failure."""
    client = _client(READ_SCOPES)
    if client is None:
        return 1
    catalog = Catalog.load()
    expected = _read_json(ACTIONS_JSON)

    insight_failures = _insight_failures(client, catalog)
    _report("insights reference only catalog events and properties", insight_failures)

    settings_failures = settings_diff(_read_json(PROJECT_JSON)["settings"], client.project())
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

    action_failures = action_diff(expected["actions"], client.actions(), expected["tag"])
    action_failures += coverage_gaps(catalog, expected["actions"])
    _report(
        "canonical actions match config/posthog/actions.json and cover every rename",
        action_failures,
    )

    failed = insight_failures or settings_failures or probe_failures or action_failures
    return 1 if failed else 0


def cmd_sync_actions(args: list[str]) -> int:
    """Print, or with --apply perform, the creates and updates that make the project match the file."""
    parser = argparse.ArgumentParser(prog="analytics.py sync-actions")
    parser.add_argument(
        "--apply", action="store_true", help="perform the plan instead of printing it"
    )
    opts = parser.parse_args(args)
    client = _client((*READ_SCOPES, WRITE_SCOPE) if opts.apply else READ_SCOPES)
    if client is None:
        return 1
    expected = _read_json(ACTIONS_JSON)
    live = {action["name"]: action for action in client.actions()}
    planned = 0
    for action in expected["actions"]:
        payload = {k: action[k] for k in ("name", "description", "tags", "steps")}
        current = live.get(action["name"])
        if current is None:
            print(f"create  {action['name']}")
            if opts.apply:
                client.create_action(payload)
        elif _comparable(current) != _comparable(action):
            print(f"update  {action['name']} (action {current['id']})")
            if opts.apply:
                client.update_action(current["id"], payload)
        else:
            continue
        planned += 1
    listed = {action["name"] for action in expected["actions"]}
    for name, action in sorted(live.items()):
        if expected["tag"] in (action.get("tags") or []) and name not in listed:
            print(
                f"left    {name} (action {action['id']}): tagged {expected['tag']} but not in the file"
            )
    verb = "applied" if opts.apply else "planned (dry run; re-run with --apply to perform)"
    print(f"{planned} change(s) {verb}")
    return 0


COMMANDS = {"check": cmd_check, "sync-actions": cmd_sync_actions}


def main(argv: list[str]) -> int:
    """Dispatch to a subcommand; exit 2 with the usage on an unknown one."""
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: analytics.py {{{'|'.join(COMMANDS)}}} [args]", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
