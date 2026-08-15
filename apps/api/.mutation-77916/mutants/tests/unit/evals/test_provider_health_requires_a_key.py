"""A lane exempt from the probe is not exempt from having credentials.

``configured()`` used to answer "yes" for the gemini lane whether or not
``GOOGLE_API_KEY`` was set, and ``health_check`` returned "verified by key
presence only" with no key present. The lane joined the rotation and then failed
at transport time on every single case — an outage the health check exists to
catch before the first model call.

The second half is the config loader: a lane that declares no ``base_url_env``
used to inherit ``DEV_LLM_BASE_URL``, so the native lanes' health probe (and any
rotation retry) pointed at the very backend they exist to be an alternative to.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.evals.core.providers import ProviderConfig, health_check, load_config

CONFIG = """
[providers.opencode]
lane = "custom"
base_url_env = "DEV_LLM_BASE_URL"
api_key_env = "DEV_LLM_API_KEY"
model_env = "DEV_LLM_MODEL"
budget_usd = 0.0

[providers.openrouter]
lane = "openrouter"
api_key_env = "OPENROUTER_API_KEY"
model_env = "OPENROUTER_MODEL"
budget_usd = 0.0

[rotation]
order = ["opencode", "openrouter"]

[cost]
default_max_usd = 8.0

[judge]
base_url_env = "DEV_LLM_BASE_URL"
api_key_env = "DEV_LLM_API_KEY"
model_env = "JUDGE_MODEL"
"""


def _lane(lane: str, api_key: str | None) -> ProviderConfig:
    return ProviderConfig(
        name=lane,
        lane=lane,
        base_url=None,
        api_key=api_key,
        model="a-model",
        budget_usd=0.0,
        price_in_per_1m=0.0,
        price_out_per_1m=0.0,
    )


@pytest.mark.parametrize("lane", ["gemini", "openrouter"])
def test_a_native_lane_without_a_key_is_not_healthy(lane: str) -> None:
    check = health_check(_lane(lane, None))

    assert not check.ok
    assert "no API key" in check.reason


@pytest.mark.parametrize("lane", ["gemini", "openrouter"])
def test_a_native_lane_with_a_key_is_healthy_without_a_probe(lane: str) -> None:
    # No base URL and no network: a native lane is served through the app's own
    # client, so the key is the only thing checkable from here.
    check = health_check(_lane(lane, "a-key"))

    assert check.ok
    assert "key presence only" in check.reason


def test_a_native_lane_does_not_inherit_the_custom_development_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(CONFIG)
    monkeypatch.setattr("scripts.evals.core.providers._load_app_env", lambda: None, raising=True)
    monkeypatch.setenv("DEV_LLM_BASE_URL", "http://localhost:9/api/v1")
    monkeypatch.setenv("DEV_LLM_API_KEY", "custom-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")

    cfg = load_config(config_path)

    assert cfg.providers["opencode"].base_url == "http://localhost:9/api/v1"
    assert cfg.providers["openrouter"].base_url is None
