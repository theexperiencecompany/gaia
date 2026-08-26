"""Shared seams for the sandbox unit tests.

``lifecycle._resolved_e2b_api_key`` is THE credential seam every E2B decision
reads (routing to the local Docker backend, fresh creates, reconnects); it
resolves through provider_credentials_service, so binding it here keeps every
unit test off Mongo. The default is a resolvable key — the hosted posture;
tests on the missing-key paths rebind it per-case with
``patch.object(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value=None))``.
"""

from unittest.mock import AsyncMock

import pytest

from app.services.sandbox import lifecycle


@pytest.fixture(autouse=True)
def _e2b_key_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle, "_resolved_e2b_api_key", AsyncMock(return_value="test-e2b-key"))
