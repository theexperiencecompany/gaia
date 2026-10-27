"""The provider catalog's own behaviour: a gateway preset's fill and the favicon a card shows."""

import pytest

from app.constants.providers import CUSTOM_PRESETS, ProviderPreset, favicon_url

pytestmark = pytest.mark.unit

_GATEWAY = ProviderPreset(
    label="Gateway",
    base_url="https://gw.example/v1",
    default_model="gw-model",
    favicon_url=favicon_url("gw.example"),
)


@pytest.mark.parametrize(
    ("base_url", "model", "filled"),
    [
        (None, None, ("https://gw.example/v1", "gw-model")),
        ("https://proxy.example/v1", None, ("https://proxy.example/v1", "gw-model")),
        (None, "my-model", ("https://gw.example/v1", "my-model")),
        ("https://proxy.example/v1", "my-model", ("https://proxy.example/v1", "my-model")),
    ],
)
def test_a_preset_fills_only_what_the_caller_omitted(
    base_url: str | None, model: str | None, filled: tuple[str, str]
) -> None:
    assert _GATEWAY.fill(base_url, model) == filled


def test_a_preset_without_a_default_model_leaves_the_model_to_the_caller() -> None:
    assert CUSTOM_PRESETS["nous"].fill(None, None) == (
        "https://inference-api.nousresearch.com/v1",
        None,
    )


def test_a_card_icon_is_the_favicon_service_image_for_its_domain() -> None:
    assert favicon_url("ollama.com") == (
        "https://www.google.com/s2/favicons?domain=ollama.com&sz=128"
    )
