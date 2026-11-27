"""Derive, from each collection's document model, which stored strings may keep their value.

A string keeps its value only where the model says it is structural: a member of an enum or
Literal, a pattern-constrained string, or a non-string type (a timestamp or number stored as a string).
Identifier fields keep only values in an opaque-token format. Every other string, and every
string in a collection with no model, is overwritten.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
import importlib
import pkgutil
import types
from typing import Annotated, Literal, Protocol, TypeAlias, Union, get_args, get_origin

from pydantic import BaseModel, EmailStr

from app.db import repositories
from app.db.repositories.base import _BaseRepository
from app.models.conversation_models import ConversationHead, StoredEntry
from gaia_db_migration.paths import ARRAY_MARKER

#: Field names whose string values are opaque identifiers, never personal data.
IDENTIFIER_FIELDS = frozenset({"_id", "id"})
IDENTIFIER_SUFFIXES = ("_id", "_ids")
#: Stored identifier keys every repository writes without declaring them on the model.
ALWAYS_KEPT_PATHS = frozenset({"_id"})


class StringRule(Enum):
    #: Structural by type: kept, after the PII guard checks it.
    KEEP = "keep"
    #: Kept only when the value is an opaque token; otherwise a same-length fake token.
    IDENTIFIER = "identifier"
    FAKE_EMAIL = "fake_email"


#: A closed, code-defined value set (an enum's or Literal's members): kept only if a member.
Members: TypeAlias = frozenset[str]
Rule: TypeAlias = StringRule | Members


class CollectionPolicy(Protocol):
    def rule(self, path: str) -> Rule | None: ...


@dataclass(frozen=True)
class ModelPolicy:
    """Rules read off a document model, by stored path."""

    rules: dict[str, Rule]

    def rule(self, path: str) -> Rule | None:
        return self.rules.get(path)


@dataclass(frozen=True)
class IdentifierPolicy:
    """For a collection with no model: only identifier-named fields keep their strings."""

    def rule(self, path: str) -> Rule | None:
        last = path.rsplit(".", 1)[-1].removesuffix(ARRAY_MARKER)
        return StringRule.IDENTIFIER if is_identifier(last) else None


def is_identifier(field_name: str) -> bool:
    return field_name in IDENTIFIER_FIELDS or field_name.endswith(IDENTIFIER_SUFFIXES)


#: Models the conversation log stores beside the repository's client-facing document model.
STORED_MODELS: dict[str, tuple[type[BaseModel], ...]] = {
    "conversations": (ConversationHead,),
    "conversation_entries": (StoredEntry,),
}


def collection_models() -> dict[str, tuple[type[BaseModel], ...]]:
    """Map each collection to every model its documents are stored and read with."""
    for module in pkgutil.iter_modules(repositories.__path__):
        importlib.import_module(f"{repositories.__name__}.{module.name}")
    models: dict[str, type[BaseModel]] = {}
    for repository in _subclasses(_BaseRepository):
        name = getattr(repository, "collection_name", None)
        model = getattr(repository, "document_model", None)
        if isinstance(name, str) and isinstance(model, type) and issubclass(model, BaseModel):
            if models.setdefault(name, model) is not model:
                raise ValueError(f"{name} has two document models: {models[name]} and {model}")
    stored: dict[str, tuple[type[BaseModel], ...]] = {
        name: (model,) for name, model in models.items()
    }
    for name, extra in STORED_MODELS.items():
        stored[name] = (*stored.get(name, ()), *extra)
    return stored


def _subclasses(cls: type) -> Iterator[type]:
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _subclasses(subclass)


def policy_for(models: tuple[type[BaseModel], ...]) -> CollectionPolicy:
    """Return the collection's string rules: from all its models, or identifiers only without one."""
    if not models:
        return IdentifierPolicy()
    rules: dict[str, Rule] = dict.fromkeys(ALWAYS_KEPT_PATHS, StringRule.IDENTIFIER)
    for model in models:
        _collect_model(model, "", rules, set())
    return ModelPolicy(rules)


def _collect_model(
    model: type[BaseModel], prefix: str, policy: dict[str, Rule], visiting: set[type]
) -> None:
    if model in visiting:
        return
    visiting.add(model)
    for name, field in model.model_fields.items():
        stored = field.alias or name
        path = f"{prefix}{stored}"
        if any(getattr(constraint, "pattern", None) for constraint in field.metadata):
            policy[path] = StringRule.KEEP
        else:
            _collect(field.annotation, path, stored, policy, visiting)
    visiting.discard(model)


def _collect(
    annotation: object, path: str, name: str, policy: dict[str, Rule], visiting: set[type]
) -> None:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        _collect(args[0], path, name, policy, visiting)
    elif origin in (Union, types.UnionType):
        for arg in args:
            _collect(arg, path, name, policy, visiting)
    elif origin in (list, set, frozenset, tuple):
        for arg in args:
            if arg is not Ellipsis:
                _collect(arg, f"{path}{ARRAY_MARKER}", name, policy, visiting)
    elif origin is Literal:
        _add_members(policy, path, frozenset(str(arg) for arg in args))
    elif origin is None:
        _collect_leaf(annotation, path, name, policy, visiting)


def _collect_leaf(
    annotation: object, path: str, name: str, policy: dict[str, Rule], visiting: set[type]
) -> None:
    if annotation is EmailStr:
        policy[path] = StringRule.FAKE_EMAIL
    elif annotation is str:
        if is_identifier(name):
            policy[path] = StringRule.IDENTIFIER
    elif not isinstance(annotation, type) or annotation in (object, type(None)):
        return
    elif issubclass(annotation, Enum):
        _add_members(policy, path, frozenset(str(member.value) for member in annotation))
    elif issubclass(annotation, BaseModel):
        _collect_model(annotation, f"{path}.", policy, visiting)
    else:
        policy[path] = StringRule.KEEP


def _add_members(policy: dict[str, Rule], path: str, members: Members) -> None:
    """Union members a path collects from several models; a broader rule already there wins."""
    existing = policy.get(path)
    if existing is None:
        policy[path] = members
    elif isinstance(existing, frozenset):
        policy[path] = existing | members
