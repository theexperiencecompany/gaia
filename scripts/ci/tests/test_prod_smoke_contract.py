"""Every API target the post-deploy smoke reads matches the API contract in apps/api/openapi.json.

Without this, a PR that renames a route or reshapes a response passes CI and only fails its
own deploy's smoke. The api-schema lane regenerates openapi.json, so the contract change and
this check land in the same PR.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lib import prod_smoke
import pytest

OPENAPI = prod_smoke.REPO_ROOT / "apps/api/openapi.json"
PLACEHOLDER = re.compile(r"^\{[^}]+\}$")
API_TARGETS = [
    t for t in prod_smoke.load_targets(prod_smoke.TARGETS_FILE) if t.base is prod_smoke.Base.API
]


def _spec(path: Path = OPENAPI) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text())
    return document


def _operation(spec: dict[str, Any], target_path: str) -> dict[str, Any]:
    """Return the GET operation whose template matches the target's path segment by segment."""
    wanted = urlsplit(target_path).path.split("/")
    for template, item in spec["paths"].items():
        segments = template.split("/")
        if len(segments) == len(wanted) and all(
            a == b or (PLACEHOLDER.match(a) and PLACEHOLDER.match(b))
            for a, b in zip(segments, wanted)
        ):
            assert "get" in item, f"{template} has no GET"
            operation: dict[str, Any] = item["get"]
            return operation
    raise AssertionError(f"{target_path}: no such route in openapi.json")


def _resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]
    return schema


def _ok_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    """Return the 200 body schema; for a union, the first member (the healthy shape, by convention)."""
    schema = _resolve(spec, operation["responses"]["200"]["content"]["application/json"]["schema"])
    if "anyOf" in schema:
        schema = _resolve(spec, schema["anyOf"][0])
    return schema


def _always_present(schema: dict[str, Any], key: str) -> bool:
    """Return whether the API always sends key: it is required, or a field with a default."""
    return key in schema.get("required", []) or "default" in schema.get("properties", {}).get(
        key, {}
    )


def contract_problems(target: prod_smoke.Target, spec: dict[str, Any]) -> list[str]:
    """Return how a target's path, query and JSON assertions disagree with the contract."""
    operation = _operation(spec, target.path)
    problems: list[str] = []
    params = {p["name"] for p in operation.get("parameters", []) if p.get("in") == "query"}
    problems += [
        f"query parameter {q!r} is not in the route"
        for q in parse_qs(urlsplit(target.path).query)
        if q not in params
    ]
    schema = _ok_schema(spec, operation)
    properties = schema.get("properties", {})
    if target.json_nonempty == ".":
        return problems + ([] if schema.get("type") == "array" else ["the 200 body is not a list"])
    asserted = [
        *target.json_keys,
        *target.json_equals,
        *filter(None, [target.json_nonempty, target.slugs_from]),
    ]
    problems += [
        f"key {key!r} is not always in the 200 body"
        for key in asserted
        if not _always_present(schema, key)
    ]
    for key in filter(None, [target.json_nonempty, target.slugs_from]):
        if properties.get(key, {}).get("type") != "array":
            problems.append(f"key {key!r} is not a list")
    if target.slugs_from:
        items = _resolve(spec, properties.get(target.slugs_from, {}).get("items", {}))
        if not _always_present(items, "slug"):
            problems.append(f"items of {target.slugs_from!r} carry no slug")
    return problems


@pytest.mark.parametrize("target", API_TARGETS, ids=lambda t: t.name)
def test_every_api_target_matches_the_contract(target: prod_smoke.Target) -> None:
    assert contract_problems(target, _spec()) == []


def test_a_reshaped_response_is_caught_before_it_deploys() -> None:
    spec = _spec()
    plans = next(t for t in API_TARGETS if t.name == "plans")
    community = next(t for t in API_TARGETS if t.name == "integrations-community")
    reshaped = json.loads(json.dumps(spec))
    reshaped["paths"]["/api/v1/payments/plans"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] = {"type": "object", "properties": {"plans": {"type": "array"}}}
    community_schema = reshaped["components"]["schemas"]["CommunityListResponse"]
    community_schema["required"].remove("total")
    del community_schema["properties"]["total"]

    assert contract_problems(plans, reshaped) == ["the 200 body is not a list"]
    assert contract_problems(community, reshaped) == ["key 'total' is not always in the 200 body"]


def test_a_renamed_route_or_query_parameter_is_caught() -> None:
    spec = _spec()
    plans = next(t for t in API_TARGETS if t.name == "plans")
    renamed = json.loads(json.dumps(spec))
    renamed["paths"]["/api/v1/payments/plans"]["get"]["parameters"][0]["name"] = "only_active"
    renamed["paths"]["/api/v1/workflows/catalog"] = renamed["paths"].pop(
        "/api/v1/workflows/explore"
    )

    assert contract_problems(plans, renamed) == [
        "query parameter 'active_only' is not in the route"
    ]
    with pytest.raises(AssertionError, match="no such route"):
        contract_problems(next(t for t in API_TARGETS if t.name == "workflows-explore"), renamed)
