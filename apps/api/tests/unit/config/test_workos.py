"""The WorkOS clients exist only under WorkOS auth, and only once per process."""

from collections.abc import Callable, Iterator

import pytest
from workos import AsyncWorkOSClient, WorkOSClient

from app.config import workos
from app.config.workos import get_async_workos_client, get_workos_client

_GETTERS: list[Callable[[], WorkOSClient | AsyncWorkOSClient]] = [
    get_workos_client,
    get_async_workos_client,
]


@pytest.fixture(autouse=True)
def _fresh_clients() -> Iterator[None]:
    get_workos_client.cache_clear()
    get_async_workos_client.cache_clear()
    yield
    get_workos_client.cache_clear()
    get_async_workos_client.cache_clear()


@pytest.mark.parametrize("getter", _GETTERS)
def test_a_local_auth_instance_refuses_to_build_a_client(
    getter: Callable[[], WorkOSClient | AsyncWorkOSClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workos.settings, "ENV", "selfhost")
    monkeypatch.setattr(workos.settings, "AUTH_MODE", "local")

    with pytest.raises(
        RuntimeError, match="WorkOS is not used under AUTH_MODE=local; no client can be built"
    ):
        getter()


@pytest.mark.parametrize(
    ("getter", "client_type"),
    [(get_workos_client, WorkOSClient), (get_async_workos_client, AsyncWorkOSClient)],
)
def test_a_workos_instance_builds_one_client_from_its_settings(
    getter: Callable[[], WorkOSClient | AsyncWorkOSClient],
    client_type: type[WorkOSClient | AsyncWorkOSClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workos.settings, "ENV", "development")
    monkeypatch.setattr(workos.settings, "AUTH_MODE", "workos")
    monkeypatch.setattr(workos.settings, "WORKOS_API_KEY", "sk_test_configured")
    monkeypatch.setattr(workos.settings, "WORKOS_CLIENT_ID", "client_configured")

    client = getter()

    assert isinstance(client, client_type)
    assert (client._api_key, client.client_id) == ("sk_test_configured", "client_configured")
    assert getter() is client
