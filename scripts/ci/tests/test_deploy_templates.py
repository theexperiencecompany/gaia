"""Tests for the one-click deploy template generator (scripts/ci/lib/deploy_templates.py)."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "deploy_templates", REPO_ROOT / "scripts" / "ci" / "lib" / "deploy_templates.py"
)
assert _SPEC is not None and _SPEC.loader is not None
dt = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dt)


def _load(text: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


@pytest.fixture
def compose() -> dict[str, Any]:
    return _load((REPO_ROOT / "packages/cli/selfhost/docker-compose.selfhost.yml").read_text())


@pytest.fixture
def secrets() -> list[str]:
    names: list[str] = dt._machine_secrets()
    return names


def _coolify(compose: dict[str, Any], secrets: list[str]) -> dict[str, Any]:
    return _load(dt.render_yaml(*dt.build_coolify(compose, secrets)))


def _render(compose: dict[str, Any], secrets: list[str]) -> dict[str, Any]:
    return _load(dt.render_yaml(*dt.build_render(compose, secrets)))


def test_every_cli_machine_secret_reaches_both_templates(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    coolify_env = _coolify(compose, secrets)["services"]["gaia-backend"]["environment"]
    render_group = _render(compose, secrets)["envVarGroups"][0]["envVars"]

    assert "GAIA_BOT_API_KEY" in secrets
    for name in secrets:
        assert coolify_env[name].startswith("${SERVICE_PASSWORD_64_")
        assert {"key": name, "generateValue": True} in render_group


def test_a_secret_coolify_cannot_map_fails_the_generator(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    with pytest.raises(SystemExit, match="NEW_SIGNING_SECRET"):
        dt.build_coolify(compose, [*secrets, "NEW_SIGNING_SECRET"])


def test_a_compose_service_no_platform_maps_fails_the_generator(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    grown = copy.deepcopy(compose)
    grown["services"]["meilisearch"] = {
        "image": "getmeili/meilisearch:v1",
        "healthcheck": {"test": ["CMD", "true"]},
    }

    with pytest.raises(SystemExit, match="meilisearch"):
        dt.build_coolify(grown, secrets)
    with pytest.raises(SystemExit, match="meilisearch"):
        dt.build_render(grown, secrets)


def test_a_compose_key_coolify_does_not_carry_fails_the_generator(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    grown = copy.deepcopy(compose)
    grown["services"]["redis"]["cap_add"] = ["SYS_RESOURCE"]

    with pytest.raises(SystemExit, match="cap_add"):
        dt.build_coolify(grown, secrets)


def test_a_compose_change_reaches_both_templates(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    changed = copy.deepcopy(compose)
    changed["services"]["mongo"]["image"] = "mongo:9"
    changed["services"]["mongo"]["environment"]["MONGO_NEW_FLAG"] = "1"

    coolify_mongo = _coolify(changed, secrets)["services"]["mongo"]
    render_mongo = next(
        s for s in _render(changed, secrets)["services"] if s["name"] == "gaia-mongo"
    )

    assert coolify_mongo["image"] == "mongo:9"
    assert "MONGO_NEW_FLAG=1" in coolify_mongo["environment"]
    assert render_mongo["image"]["url"] == "docker.io/library/mongo:9"
    assert {"key": "MONGO_NEW_FLAG", "value": "1"} in render_mongo["envVars"]


def test_the_inline_caddyfile_holds_no_compose_interpolation(
    compose: dict[str, Any], secrets: list[str]
) -> None:
    content = _coolify(compose, secrets)["services"]["proxy"]["volumes"][0]["content"]

    assert "$" not in content
    assert ":80 {" in content
    assert "reverse_proxy gaia-backend:8000" in content


@pytest.mark.parametrize(
    ("image", "full"),
    [
        ("mongo:8", "docker.io/library/mongo:8"),
        ("chromadb/chroma:1.5.1", "docker.io/chromadb/chroma:1.5.1"),
        ("ghcr.io/theexperiencecompany/gaia:latest", "ghcr.io/theexperiencecompany/gaia:latest"),
    ],
)
def test_render_images_name_their_registry(image: str, full: str) -> None:
    assert dt._docker_hub(image) == full
