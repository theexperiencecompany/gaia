"""The shared PostHog client evaluates flags in-process when it holds a secret key, so a flag check is no network call."""

from unittest.mock import MagicMock, patch

import pytest

from app.config import posthog as posthog_config
from app.core.lazy_loader import providers

pytestmark = pytest.mark.unit


def _built_with(secret_key: str | None) -> MagicMock:
    """Register the provider against a double registry, then run the loader it registered."""
    with (
        patch.object(providers, "register") as register,
        patch.object(posthog_config, "Posthog") as client,
        patch.object(posthog_config.settings, "POSTHOG_SECRET_KEY", secret_key),
    ):
        posthog_config.init_posthog()
        register.call_args.kwargs["loader_func"]()
    return client


def test_the_client_is_given_the_secret_key_that_turns_on_local_flag_evaluation() -> None:
    client = _built_with("phx_secret")

    assert client.call_args.kwargs["secret_key"] == "phx_secret"


def test_with_no_secret_key_the_client_evaluates_flags_remotely_as_before() -> None:
    client = _built_with(None)

    assert client.call_args.kwargs["secret_key"] is None
