"""The event catalog's contract: names, owners, property kinds, emitters and the generated types."""

import ast
from datetime import timedelta
import json
from pathlib import Path
import re
from typing import Annotated, ClassVar

from pydantic import TypeAdapter, ValidationError
import pytest

from shared.py.analytics.catalog import CATALOG
from shared.py.analytics.catalog.auth import UserActive
from shared.py.analytics.catalog.base import (
    EVENT_NAME_PATTERN,
    CatalogError,
    ServerEvent,
    Surface,
    WebEvent,
)
from shared.py.analytics.catalog.billing import RateLimitHit
from shared.py.analytics.catalog.properties import (
    CurrencyCode,
    Emoji,
    Identifier,
    ObjectIdStr,
    UrlPath,
)
from shared.py.analytics.codegen import (
    CATALOG_JSON,
    EVENTS_TS,
    export_catalog,
    render_typescript,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

# Where each owner's emitters live, and how a call site names the event there.
_SERVER_SOURCES = ("apps/api/app",)
_VOICE_SOURCES = ("apps/voice-agent/src",)
_WEB_SOURCES = ("apps/web/src", "apps/web/instrumentation-client.ts")
_BOT_SOURCES = ("libs/shared/ts/src/bots", "apps/bots")
_ATTRIBUTED_OWNERS = (Surface.SERVER, Surface.VOICE)
_TEST_PATH = re.compile(r"(__tests__|/tests?/|\.test\.tsx?$|\.spec\.tsx?$)")
_EMITTER_SITE_SOURCES = (*_SERVER_SOURCES, *_VOICE_SOURCES, "libs/shared/py")
# The capture machinery names events to configure them (the active-use set) and emits none itself.
_ANALYTICS_PACKAGE = "libs/shared/py/analytics/"

# Events built in several functions, one per mutually exclusive path; a count may only fall.
_MULTI_SITE_EVENTS: dict[str, tuple[int, str]] = {
    "agent:run_started": (2, "the comms run and the executor run are different runs"),
    "approval:decided": (2, "the single and the batch decision routes; props say which"),
    "browser:handoff_resolved": (3, "card reply or button, card stop button, chat stop tool"),
    "calendar:event_created": (2, "the single and the batch route; batch props say which"),
    "calendar:event_deleted": (2, "the single and the batch route; batch props say which"),
    "calendar:event_updated": (2, "the single and the batch route; batch props say which"),
    "chat:conversation_created": (2, "a user's conversation and a system one, never both"),
    "chat:conversation_deleted": (2, "delete one and delete all; props say which"),
    "chat:message_submitted": (2, "the web chat route and the bot turn charge, one per surface"),
    "email:sent": (2, "send a new email and send a saved draft"),
    "hil:decision_submitted": (
        2,
        "auto mode's verdict has no card; a card's decision has no verdict",
    ),
    "hil:resumed": (2, "a parked todo run and a parked workflow run"),
    "hil:revoked": (2, "the proposer's revoke and a cancelled run's sweep"),
    "integration:connect_initiated": (3, "the connect route, a connect link, a platform connect"),
    "integration:connected": (
        7,
        "each connect transport finishes in its own place: Composio and MCP OAuth callbacks, "
        "direct, custom, marketplace and workspace adds, bot platform links",
    ),
    "integration:disconnected": (
        4,
        "agent tool, settings route, workspace removal, platform unlink",
    ),
    "payment:checkout_started": (2, "the redirect checkout and the embedded overlay"),
    "profile:updated": (4, "the full profile, name, timezone and card colour routes"),
    "settings:preferences_changed": (5, "one site per setting; setting says which"),
    "skill:installed": (2, "install from GitHub and write inline"),
    "todos:deleted": (2, "delete one and bulk delete; props say which"),
    "todos:toggled": (3, "a todo, a bulk selection, a subtask"),
    "todos:updated": (6, "a todo, a bulk edit, a bulk move, and three subtask routes"),
    "tool:used": (
        3,
        "bound tools, the execute proxy, the MCP app proxy; via and source split them",
    ),
    "workflow:created": (4, "one per origin: user, chat agent, todo conversion, todo request"),
    "workflow:executed": (2, "manual runs at the run-now route, every other trigger in the worker"),
}


def _source_texts(roots: tuple[str, ...], suffixes: tuple[str, ...]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for root in roots:
        base = REPO_ROOT / root
        files = [base] if base.is_file() else base.rglob("*")
        for path in files:
            relative = path.relative_to(REPO_ROOT).as_posix()
            if (
                path.suffix in suffixes
                and "node_modules" not in path.parts
                and not _TEST_PATH.search(relative)
            ):
                texts.append((relative, path.read_text(encoding="utf-8")))
    return texts


def _source_files(roots: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
    return [text for _, text in _source_texts(roots, suffixes)]


def _not_emitting(tree: ast.Module) -> set[int]:
    """Ids of nodes that name a class without building it: annotations, type aliases, type checks, X.event."""
    types = [
        node.annotation
        for node in ast.walk(tree)
        if isinstance(node, ast.arg | ast.AnnAssign) and node.annotation is not None
    ]
    types += [
        node.returns
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None
    ]
    types += [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and node.value is not None
        and ast.unparse(node.annotation).endswith("TypeAlias")
    ]
    types += [
        node.args[1]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in ("isinstance", "issubclass")
        and len(node.args) == 2
    ]
    types += [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in ("event", "__name__")
    ]
    return {id(child) for node in types for child in ast.walk(node)}


def _python_references(source: str) -> dict[str, set[str]]:
    """Each name the module's code loads, with the functions that load it; module level is ""."""
    tree = ast.parse(source)
    skipped = _not_emitting(tree)
    scopes: dict[str, set[str]] = {}

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = f"{scope}.{child.name}" if scope else child.name
            elif isinstance(child, ast.Name) and id(child) not in skipped:
                scopes.setdefault(child.id, set()).add(scope)
            visit(child, inner)

    visit(tree, "")
    return scopes


@pytest.fixture(scope="module")
def python_references() -> dict[Surface, set[str]]:
    return {
        surface: set().union(
            *(_python_references(text).keys() for text in _source_files(roots, (".py",)))
        )
        for surface, roots in ((Surface.SERVER, _SERVER_SOURCES), (Surface.VOICE, _VOICE_SOURCES))
    }


@pytest.fixture(scope="module")
def emitter_sites() -> dict[str, set[tuple[str, str]]]:
    """Every (file, function) that names each catalog class in product Python."""
    sites: dict[str, set[tuple[str, str]]] = {}
    for relative, text in _source_texts(_EMITTER_SITE_SOURCES, (".py",)):
        if relative.startswith(_ANALYTICS_PACKAGE):
            continue
        for name, scopes in _python_references(text).items():
            sites.setdefault(name, set()).update((relative, scope) for scope in scopes)
    return sites


@pytest.fixture(scope="module")
def typescript_sources() -> dict[Surface, str]:
    return {
        Surface.WEB: "\n".join(_source_files(_WEB_SOURCES, (".ts", ".tsx"))),
        Surface.BOT: "\n".join(_source_files(_BOT_SOURCES, (".ts",))),
    }


@pytest.mark.parametrize("name", list(CATALOG))
def test_every_event_name_is_domain_action(name: str) -> None:
    assert EVENT_NAME_PATTERN.fullmatch(name), name


@pytest.mark.parametrize("name", ["rate_limit_hit", "chat", "Chat:Sent", "chat:", ":sent", "a:b:c"])
def test_a_name_that_is_not_domain_action_cannot_be_defined(name: str) -> None:
    with pytest.raises(CatalogError, match="domain:action"):
        type(
            "BadName", (ServerEvent,), {"event": name, "__annotations__": {"event": ClassVar[str]}}
        )


def test_a_second_event_with_a_taken_name_cannot_be_defined() -> None:
    with pytest.raises(CatalogError, match="already"):
        type(
            "Duplicate",
            (WebEvent,),
            {"event": "chat:message_submitted", "__annotations__": {"event": ClassVar[str]}},
        )


def test_a_free_text_property_cannot_be_defined() -> None:
    """A bare str would let message text, names or emails ride along as a property."""
    with pytest.raises(CatalogError, match="not a count, enum, id kind"):
        type(
            "FreeText",
            (ServerEvent,),
            {"event": "test:free_text", "__annotations__": {"event": ClassVar[str], "text": str}},
        )


@pytest.mark.parametrize("name", list(CATALOG))
def test_no_catalog_property_accepts_free_text(name: str) -> None:
    """Every str-typed property is an id kind, so a sentence or an email fails validation."""
    for field in CATALOG[name].model_fields.values():
        annotation = (
            Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
        )
        adapter: TypeAdapter[object] = TypeAdapter(annotation)
        for text in ("hello there, it is me", "someone@example.com"):
            with pytest.raises(ValidationError):
                adapter.validate_python(text)


@pytest.mark.parametrize("kind", [Identifier, ObjectIdStr, CurrencyCode, Emoji, UrlPath])
def test_every_id_kind_rejects_whitespace_and_email(kind: object) -> None:
    adapter: TypeAdapter[str] = TypeAdapter(kind)
    for text in ("two words", "someone@example.com", ""):
        with pytest.raises(ValidationError):
            adapter.validate_python(text)


def test_the_renamed_rate_limit_event_keeps_its_old_name_on_record() -> None:
    assert RateLimitHit.event == "rate_limit:hit"
    assert RateLimitHit.previous_names == ("rate_limit_hit",)


@pytest.mark.parametrize(
    "name", ["chat:style_guard_regenerated", "onboarding:integrations_submitted"]
)
def test_never_emitted_events_are_gone(name: str) -> None:
    assert name not in CATALOG


@pytest.mark.parametrize("name", list(CATALOG))
def test_every_event_has_an_emitter(
    name: str,
    python_references: dict[Surface, set[str]],
    typescript_sources: dict[Surface, str],
) -> None:
    """A catalog entry nothing emits is a dashboard tile that reads zero forever."""
    model = CATALOG[name]
    if model.owner in python_references:
        # A name reference, not "Name(": some emitters pick the class first, then build it.
        assert model.__name__ in python_references[model.owner], f"nothing emits {model.__name__}"
    else:
        assert f'"{name}"' in typescript_sources[model.owner], (
            f"no {model.owner} source names {name}"
        )


@pytest.mark.parametrize(
    "name", [name for name, model in CATALOG.items() if model.owner in _ATTRIBUTED_OWNERS]
)
def test_every_server_and_voice_event_has_one_emitter(
    name: str, emitter_sites: dict[str, set[tuple[str, str]]]
) -> None:
    """One action, one emitter: a second function building the same event is how double counts start."""
    sites = sorted(emitter_sites.get(CATALOG[name].__name__, set()))
    allowed = _MULTI_SITE_EVENTS[name][0] if name in _MULTI_SITE_EVENTS else 1
    where = "\n".join(f"  {path}: {scope or '<module>'}" for path, scope in sites)
    assert len(sites) <= allowed, (
        f"{name} is built in {len(sites)} functions, allowed {allowed}; converge it:\n{where}"
    )
    assert len(sites) == allowed or name not in _MULTI_SITE_EVENTS, (
        f"{name} is down to {len(sites)} sites: shrink its _MULTI_SITE_EVENTS entry to match"
    )


def test_every_multi_site_entry_names_a_server_or_voice_event() -> None:
    for name, (count, _) in _MULTI_SITE_EVENTS.items():
        assert CATALOG[name].owner in _ATTRIBUTED_OWNERS, name
        assert count > 1, f"{name}: one site needs no entry"


def test_each_function_that_builds_an_event_is_one_site() -> None:
    source = (
        "def charge():\n"
        "    capture(uid, PaymentFailed())\n"
        "    capture(other, PaymentFailed(retry=True))\n"
        "class Webhook:\n"
        "    def on_failure(self):\n"
        "        event_cls = PaymentFailed\n"
        "        capture(uid, event_cls())\n"
    )
    assert _python_references(source)["PaymentFailed"] == {"charge", "Webhook.on_failure"}


def test_a_type_alias_type_check_or_event_name_read_is_not_an_emitter() -> None:
    source = (
        "Lifecycle: TypeAlias = PaymentFailed | PaymentSucceeded\n"
        "def f(event):\n"
        "    if isinstance(event, PaymentFailed):\n"
        "        return PaymentFailed.event\n"
    )
    assert "PaymentFailed" not in _python_references(source)


def test_an_import_comment_docstring_or_annotation_is_not_an_emitter() -> None:
    source = (
        "from shared.py.analytics.catalog.billing import PaymentFailed\n"
        "def f(event: PaymentFailed) -> PaymentFailed:\n"
        '    """PaymentFailed is captured elsewhere."""\n'
        "    # PaymentFailed\n"
        "    return event\n"
    )
    assert "PaymentFailed" not in _python_references(source)


def test_a_class_picked_before_it_is_built_is_an_emitter() -> None:
    source = (
        "event_cls = PaymentFailed if failed else PaymentSucceeded\ncapture(uid, event_cls())\n"
    )
    assert {"PaymentFailed", "PaymentSucceeded"} <= _python_references(source).keys()


def test_the_generated_typescript_matches_the_catalog() -> None:
    assert EVENTS_TS.read_text(encoding="utf-8") == render_typescript(), (
        "run `mise analytics:types`"
    )


def test_the_exported_catalog_json_matches_the_catalog() -> None:
    committed = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(export_catalog())), "run `mise analytics:types`"


@pytest.mark.parametrize("name", list(CATALOG))
def test_every_event_has_a_daily_budget(name: str) -> None:
    """The volume alert reads it; an event with none could loop unnoticed."""
    assert CATALOG[name].budget_per_user_day >= 1


def test_an_event_without_a_budget_cannot_be_defined() -> None:
    with pytest.raises(CatalogError, match="budget_per_user_day"):
        type(
            "NoBudget",
            (ServerEvent,),
            {"event": "test:no_budget", "__annotations__": {"event": ClassVar[str]}},
        )


@pytest.mark.parametrize(
    "name", [name for name, model in CATALOG.items() if model.owner in _ATTRIBUTED_OWNERS]
)
def test_every_server_and_voice_event_requires_attribution(name: str) -> None:
    """The base properties are required in the exported schema, so a tile may rely on them."""
    exported = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    [event] = [event for event in exported["events"] if event["event"] == name]
    base = exported["base_properties"][event["base_properties"]]
    assert set(base["required"]) == {"actor", "trigger", "surface"}


def test_an_event_property_cannot_shadow_the_attribution() -> None:
    with pytest.raises(CatalogError, match="shadow"):
        type(
            "Shadowing",
            (ServerEvent,),
            {
                "event": "test:shadowing",
                "budget_per_user_day": 10,
                "__annotations__": {
                    "event": ClassVar[str],
                    "budget_per_user_day": ClassVar[int],
                    "surface": bool,
                },
            },
        )


def test_the_active_user_mark_is_gated_to_once_a_day() -> None:
    assert UserActive.event in CATALOG
    assert UserActive.budget_per_user_day == 1
    assert UserActive.at_most_once_ttl is not None
    assert UserActive.at_most_once_ttl >= timedelta(days=1)
