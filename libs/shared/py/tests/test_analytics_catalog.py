"""The event catalog's contract: names, owners, property kinds, emitters and the generated types."""

import ast
import json
from pathlib import Path
import re
from typing import Annotated, ClassVar

from pydantic import TypeAdapter, ValidationError
import pytest

from shared.py.analytics.catalog import CATALOG
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
_TEST_PATH = re.compile(r"(__tests__|/tests?/|\.test\.tsx?$|\.spec\.tsx?$)")


def _source_files(roots: tuple[str, ...], suffixes: tuple[str, ...]) -> list[str]:
    texts: list[str] = []
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
                texts.append(path.read_text(encoding="utf-8"))
    return texts


def _python_references(source: str) -> set[str]:
    """Names the module's code loads; imports, comments, docstrings and annotations emit nothing."""
    tree = ast.parse(source)
    annotations = [
        node.annotation
        for node in ast.walk(tree)
        if isinstance(node, ast.arg | ast.AnnAssign) and node.annotation is not None
    ]
    annotations += [
        node.returns
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None
    ]
    in_annotation = {id(child) for annotation in annotations for child in ast.walk(annotation)}
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and id(node) not in in_annotation
    }


@pytest.fixture(scope="module")
def python_references() -> dict[Surface, set[str]]:
    return {
        surface: set().union(*(_python_references(text) for text in _source_files(roots, (".py",))))
        for surface, roots in ((Surface.SERVER, _SERVER_SOURCES), (Surface.VOICE, _VOICE_SOURCES))
    }


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
    assert {"PaymentFailed", "PaymentSucceeded"} <= _python_references(source)


def test_the_generated_typescript_matches_the_catalog() -> None:
    assert EVENTS_TS.read_text(encoding="utf-8") == render_typescript(), (
        "run `mise analytics:types`"
    )


def test_the_exported_catalog_json_matches_the_catalog() -> None:
    committed = json.loads(CATALOG_JSON.read_text(encoding="utf-8"))
    assert committed == json.loads(json.dumps(export_catalog())), "run `mise analytics:types`"
