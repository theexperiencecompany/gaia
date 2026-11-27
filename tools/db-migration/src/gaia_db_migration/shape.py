"""Propose a relational shape for every migrated collection from its stored models and prod's inventory.

The proposal is input to the schema review, not the schema: each field gets a SQL type, its
nullability, and where it lives (a column, a child table, an array or a JSONB value), with the
evidence that decided it (array sizes in prod, whether an index reads the path).
"""

import argparse
from collections.abc import Iterator
from dataclasses import dataclass
import datetime as dt
from enum import Enum, StrEnum
import json
from pathlib import Path
import types
from typing import Annotated, Any, Literal, Union, get_args, get_origin
import uuid

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from gaia_db_migration.model_policy import collection_models
from gaia_db_migration.paths import ARRAY_MARKER
from gaia_db_migration.snapshot import DEFAULT_INVENTORY, snapshot_collections

SCALAR_SQL: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),
    (int, "bigint"),
    (float, "double precision"),
    (dt.datetime, "timestamptz"),
    (dt.date, "date"),
    (uuid.UUID, "uuid"),
    (str, "text"),
)


class Placement(StrEnum):
    COLUMN = "column"
    ENUM = "enum column"
    ARRAY = "array column"
    CHILD_TABLE = "child table"
    JSONB = "jsonb"
    NESTED = "nested object"


@dataclass(frozen=True)
class FieldShape:
    path: str
    python: str
    sql: str
    placement: Placement
    required: bool
    indexed: bool
    present: int
    null: int
    max_array: int


def _unwrap(annotation: object) -> tuple[object, bool]:
    """Strip Annotated and Optional; return the inner type and whether None was allowed."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap(get_args(annotation)[0])
    if origin in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        inner, _ = _unwrap(args[0]) if len(args) == 1 else (annotation, False)
        return inner, len(args) < len(get_args(annotation))
    return annotation, False


def _sql_scalar(annotation: object) -> str | None:
    if isinstance(annotation, type):
        for python_type, sql in SCALAR_SQL:
            if issubclass(annotation, python_type):
                return sql
    return None


def _classify(annotation: object) -> tuple[Placement, str, type[BaseModel] | None]:
    origin = get_origin(annotation)
    if origin is Literal or (isinstance(annotation, type) and issubclass(annotation, Enum)):
        return Placement.ENUM, "enum", None
    if origin in (list, set, frozenset, tuple):
        element, _ = _unwrap(get_args(annotation)[0])
        if isinstance(element, type) and issubclass(element, BaseModel):
            return Placement.CHILD_TABLE, element.__name__, element
        scalar = _sql_scalar(element)
        return (
            (Placement.ARRAY, f"{scalar}[]", None) if scalar else (Placement.JSONB, "jsonb", None)
        )
    if origin is dict or annotation in (Any, object):
        return Placement.JSONB, "jsonb", None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return Placement.NESTED, annotation.__name__, annotation
    if origin in (Union, types.UnionType):
        return Placement.JSONB, "jsonb (union)", None
    scalar = _sql_scalar(annotation)
    return (Placement.COLUMN, scalar, None) if scalar else (Placement.JSONB, "jsonb", None)


def _fields(
    model: type[BaseModel], prefix: str, seen: frozenset[type]
) -> Iterator[tuple[str, FieldInfo, object, bool]]:
    for name, info in model.model_fields.items():
        path = f"{prefix}{info.alias or name}"
        annotation, optional = _unwrap(info.annotation)
        yield path, info, annotation, optional
        placement, _, nested = _classify(annotation)
        if nested is not None and nested not in seen:
            child_prefix = (
                f"{path}{ARRAY_MARKER}." if placement is Placement.CHILD_TABLE else f"{path}."
            )
            yield from _fields(nested, child_prefix, seen | {nested})


def shapes(
    models: tuple[type[BaseModel], ...], profile: dict[str, Any], indexed_paths: set[str]
) -> list[FieldShape]:
    found: dict[str, FieldShape] = {}
    for model in models:
        for path, info, annotation, optional in _fields(model, "", frozenset({model})):
            placement, sql, _ = _classify(annotation)
            stats = profile["paths"].get(path, {})
            types_seen: dict[str, int] = stats.get("types", {})
            found.setdefault(
                path,
                FieldShape(
                    path=path,
                    python=str(info.annotation).replace("typing.", ""),
                    sql=sql,
                    placement=placement,
                    required=info.is_required() and not optional,
                    indexed=path.replace(ARRAY_MARKER, "") in indexed_paths,
                    present=stats.get("present", 0),
                    null=types_seen.get("null", 0),
                    max_array=stats.get("max_array_length", 0),
                ),
            )
    return list(found.values())


def _indexed_paths(profile: dict[str, Any]) -> set[str]:
    return {key for index in profile["indexes"] for key in index["key"]}


def main() -> None:
    parser = argparse.ArgumentParser(prog="db-shape", description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    inventory = json.loads(args.inventory.read_text())["collections"]
    models = collection_models()
    report: dict[str, Any] = {}
    for name in snapshot_collections():
        profile = inventory.get(name, {"paths": {}, "indexes": [], "documents": 0})
        report[name] = {
            "documents": profile["documents"],
            "models": [model.__name__ for model in models.get(name, ())],
            "unmodelled_top_level_paths": sorted(
                path
                for path in profile["paths"]
                if "." not in path
                and ARRAY_MARKER not in path
                and path not in {s.path for s in shapes(models.get(name, ()), profile, set())}
                and path != "_id"
            ),
            "fields": [
                vars(shape)
                for shape in shapes(models.get(name, ()), profile, _indexed_paths(profile))
            ],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {args.out}: {len(report)} collections")
