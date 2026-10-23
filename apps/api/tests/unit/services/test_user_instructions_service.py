"""The standing-instructions service: revision guard, scope validation, caps, projections, events.

The real repository runs against an in-memory collection, so only Mongo I/O is faked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.constants.error_codes import INSTRUCTIONS_CONFLICT
from app.models.user_instructions_models import (
    GLOBAL_INSTRUCTIONS_SCOPE,
    MAX_INSTRUCTIONS_CHARS,
    InstructionsEditor,
)
from app.services import user_instructions_service as svc
from app.utils.errors import AppError
from shared.py.analytics import UserId
from shared.py.analytics.catalog.settings import InstructionsConflict, InstructionsUpdated
from tests.helpers import captured_wide_event
from tests.user_instructions_fakes import (
    FakeCollection,
    always_connected,
    install_fake_collection,
    never_connected,
    new_user_id,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def fake_collection(monkeypatch: pytest.MonkeyPatch) -> FakeCollection:
    return install_fake_collection(monkeypatch)


@pytest.fixture
def connected_checks(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Every scope is connected; records the (user_id, scope) each check was asked about."""
    asked: list[tuple[str, str]] = []

    async def check(user_id: str, scope: str) -> bool:  # NOSONAR python:S7503
        asked.append((user_id, scope))
        return True

    monkeypatch.setattr(svc, "check_user_has_integration", check)
    return asked


@pytest.fixture
def account_syncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    synced: list[str] = []
    monkeypatch.setattr(svc, "schedule_account_sync", synced.append)
    return synced


@pytest.fixture(autouse=True)
def integration_syncs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record each re-materialization of integrations/<id>/agent/instructions.md."""
    synced: list[str] = []
    monkeypatch.setattr(svc, "schedule_user_integrations_sync", synced.append)
    return synced


@pytest.fixture
def captured() -> MagicMock:
    with patch.object(svc, "capture") as capture:
        yield capture


class TestWriteAndRead:
    async def test_roundtrip_bumps_revision_and_records_editor(
        self, fake_collection: FakeCollection, connected_checks: list[tuple[str, str]]
    ) -> None:
        uid = new_user_id()
        first = await svc.write_instructions(
            uid, "slack", "focus #eng", updated_by=InstructionsEditor.USER
        )
        second = await svc.write_instructions(
            uid, "slack", "default project backend", updated_by=InstructionsEditor.AGENT
        )

        assert (first.scope, first.content, first.revision, first.updated_by) == (
            "slack",
            "focus #eng",
            1,
            InstructionsEditor.USER,
        )
        assert (second.content, second.revision, second.updated_by) == (
            "default project backend",
            2,
            InstructionsEditor.AGENT,
        )
        assert second.updated_at is not None
        record = await svc.get_instructions_record(uid, "slack")
        assert (record.scope, record.content, record.revision, record.updated_by) == (
            "slack",
            "default project backend",
            2,
            InstructionsEditor.AGENT,
        )
        assert record.updated_at == second.updated_at
        assert await svc.get_all_instructions(uid) == {"slack": "default project backend"}
        assert connected_checks == [(uid, "slack"), (uid, "slack")]

    async def test_an_unwritten_scope_reads_as_revision_zero(
        self, fake_collection: FakeCollection
    ) -> None:
        record = await svc.get_instructions_record(new_user_id(), GLOBAL_INSTRUCTIONS_SCOPE)
        assert (record.scope, record.content, record.revision, record.updated_by) == (
            GLOBAL_INSTRUCTIONS_SCOPE,
            "",
            0,
            None,
        )

    async def test_reads_are_scoped_to_their_user(self, fake_collection: FakeCollection) -> None:
        a, b = new_user_id(), new_user_id()
        await svc.write_instructions(
            a, GLOBAL_INSTRUCTIONS_SCOPE, "tenant-a-secret", updated_by=InstructionsEditor.USER
        )
        assert await svc.get_instructions(b, GLOBAL_INSTRUCTIONS_SCOPE) is None
        assert await svc.get_all_instructions(b) == {}
        assert await svc.get_instructions(a, GLOBAL_INSTRUCTIONS_SCOPE) == "tenant-a-secret"

    async def test_whitespace_only_is_stored_as_cleared(
        self, fake_collection: FakeCollection
    ) -> None:
        uid = new_user_id()
        saved = await svc.write_instructions(
            uid, GLOBAL_INSTRUCTIONS_SCOPE, "   \n\t  ", updated_by=InstructionsEditor.USER
        )
        assert saved.content == ""
        assert fake_collection.docs[0]["content"] == ""
        assert GLOBAL_INSTRUCTIONS_SCOPE not in await svc.get_all_instructions(uid)


class TestRevisionGuard:
    async def test_a_stale_base_revision_is_a_409_and_keeps_the_newer_text(
        self, fake_collection: FakeCollection, captured: MagicMock
    ) -> None:
        uid = new_user_id()
        await svc.write_instructions(
            uid,
            GLOBAL_INSTRUCTIONS_SCOPE,
            "v1",
            updated_by=InstructionsEditor.USER,
            base_revision=0,
        )
        await svc.write_instructions(
            uid, GLOBAL_INSTRUCTIONS_SCOPE, "agent v2", updated_by=InstructionsEditor.AGENT
        )
        captured.reset_mock()

        with pytest.raises(AppError) as exc_info:
            await svc.write_instructions(
                uid,
                GLOBAL_INSTRUCTIONS_SCOPE,
                "editor v2",
                updated_by=InstructionsEditor.USER,
                base_revision=1,
            )

        error = exc_info.value
        assert (error.status_code, error.code, error.public) == (
            409,
            INSTRUCTIONS_CONFLICT,
            {"current_revision": 2},
        )
        assert error.message == (
            "These instructions were changed somewhere else since you opened them"
        )
        assert error.fix == "Load the latest version, or save again to overwrite it"
        assert await svc.get_instructions(uid, GLOBAL_INSTRUCTIONS_SCOPE) == "agent v2"
        captured.assert_called_once_with(UserId(uid), InstructionsConflict(scope_kind="global"))

    async def test_a_first_save_racing_an_agent_write_is_a_409(
        self, fake_collection: FakeCollection
    ) -> None:
        uid = new_user_id()
        await svc.write_instructions(
            uid, GLOBAL_INSTRUCTIONS_SCOPE, "agent", updated_by=InstructionsEditor.AGENT
        )
        with pytest.raises(AppError) as exc_info:
            await svc.write_instructions(
                uid,
                GLOBAL_INSTRUCTIONS_SCOPE,
                "editor",
                updated_by=InstructionsEditor.USER,
                base_revision=0,
            )
        assert exc_info.value.status_code == 409
        assert len(fake_collection.docs) == 1


class TestValidation:
    async def test_over_the_cap_is_refused_not_truncated(
        self, fake_collection: FakeCollection
    ) -> None:
        with pytest.raises(AppError) as exc_info:
            await svc.write_instructions(
                new_user_id(),
                GLOBAL_INSTRUCTIONS_SCOPE,
                "x" * (MAX_INSTRUCTIONS_CHARS + 1),
                updated_by=InstructionsEditor.USER,
            )
        error = exc_info.value
        assert error.status_code == 400
        assert error.message == f"Instructions must be {MAX_INSTRUCTIONS_CHARS} characters or less"
        assert error.fix == "Shorten the instructions and try again"
        assert fake_collection.docs == []

    async def test_exactly_the_cap_is_accepted(self, fake_collection: FakeCollection) -> None:
        saved = await svc.write_instructions(
            new_user_id(),
            GLOBAL_INSTRUCTIONS_SCOPE,
            "x" * MAX_INSTRUCTIONS_CHARS,
            updated_by=InstructionsEditor.USER,
        )
        assert len(saved.content) == MAX_INSTRUCTIONS_CHARS

    async def test_the_global_scope_needs_no_connected_integration(
        self, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(svc, "check_user_has_integration", never_connected)
        saved = await svc.write_instructions(
            new_user_id(),
            GLOBAL_INSTRUCTIONS_SCOPE,
            "reply in Spanish",
            updated_by=InstructionsEditor.USER,
        )
        assert saved.revision == 1

    async def test_an_unconnected_integration_scope_is_a_404(
        self, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(svc, "check_user_has_integration", never_connected)
        with pytest.raises(AppError) as exc_info:
            await svc.write_instructions(
                new_user_id(), "slack", "hi", updated_by=InstructionsEditor.USER
            )
        error = exc_info.value
        assert error.status_code == 404
        assert error.message == "'slack' is not one of this user's connected integrations"
        assert error.fix == "Connect the integration first, or set global instructions instead"
        assert fake_collection.docs == []

    @pytest.mark.parametrize(
        "evil", ["../../x", "..", "a/b", "/abs", "with space", "x" * 65, "café"]
    )
    async def test_an_unsafe_scope_is_a_400(
        self, fake_collection: FakeCollection, monkeypatch: pytest.MonkeyPatch, evil: str
    ) -> None:
        monkeypatch.setattr(svc, "check_user_has_integration", always_connected)
        with pytest.raises(AppError) as exc_info:
            await svc.write_instructions(
                new_user_id(), evil, "hi", updated_by=InstructionsEditor.USER
            )
        error = exc_info.value
        assert error.status_code == 400
        assert error.message == f"Invalid instructions scope '{evil}'"
        assert error.fix == "Use 'global' or a connected integration's id"
        assert isinstance(error.__cause__, ValueError)
        assert fake_collection.docs == []

    async def test_a_safe_scope_is_checked_against_this_users_integrations(
        self, connected_checks: list[tuple[str, str]]
    ) -> None:
        uid = new_user_id()
        await svc.validate_scope(uid, "slack")
        await svc.validate_scope(uid, GLOBAL_INSTRUCTIONS_SCOPE)
        assert connected_checks == [(uid, "slack")]


class TestSideEffects:
    async def test_a_global_write_refreshes_the_account_projection_only(
        self,
        fake_collection: FakeCollection,
        account_syncs: list[str],
        integration_syncs: list[str],
    ) -> None:
        uid = new_user_id()
        await svc.write_instructions(
            uid, GLOBAL_INSTRUCTIONS_SCOPE, "be brief", updated_by=InstructionsEditor.USER
        )
        assert account_syncs == [uid]
        assert integration_syncs == []

    async def test_an_integration_write_refreshes_its_workspace_projection(
        self,
        fake_collection: FakeCollection,
        connected_checks: list[tuple[str, str]],
        account_syncs: list[str],
        integration_syncs: list[str],
    ) -> None:
        """Before this, the projection refreshed only on connect or boot, so edits stayed stale."""
        uid = new_user_id()
        await svc.write_instructions(uid, "slack", "only #eng", updated_by=InstructionsEditor.USER)
        await svc.write_instructions(
            uid, "slack", "", updated_by=InstructionsEditor.USER, base_revision=1
        )
        assert integration_syncs == [uid, uid]
        assert account_syncs == []

    async def test_each_save_emits_one_instructions_updated(
        self,
        fake_collection: FakeCollection,
        connected_checks: list[tuple[str, str]],
        captured: MagicMock,
    ) -> None:
        uid = new_user_id()
        await svc.write_instructions(uid, "slack", "only #eng", updated_by=InstructionsEditor.AGENT)
        captured.assert_called_once_with(
            UserId(uid),
            InstructionsUpdated(
                scope_kind="integration", updated_by=InstructionsEditor.AGENT, cleared=False
            ),
        )

    async def test_a_cleared_save_is_reported_as_cleared(
        self, fake_collection: FakeCollection, captured: MagicMock
    ) -> None:
        uid = new_user_id()
        await svc.write_instructions(
            uid, GLOBAL_INSTRUCTIONS_SCOPE, "  ", updated_by=InstructionsEditor.USER
        )
        captured.assert_called_once_with(
            UserId(uid),
            InstructionsUpdated(
                scope_kind="global", updated_by=InstructionsEditor.USER, cleared=True
            ),
        )

    async def test_the_wide_event_names_the_scope_kind_editor_revision_and_size(
        self, fake_collection: FakeCollection
    ) -> None:
        async with captured_wide_event() as event:
            await svc.write_instructions(
                new_user_id(),
                GLOBAL_INSTRUCTIONS_SCOPE,
                "be brief",
                updated_by=InstructionsEditor.USER,
            )
        assert event["instructions"] == {
            "scope_kind": "global",
            "updated_by": "user",
            "revision": 1,
            "chars": 8,
        }


class TestProjectionInputs:
    def test_the_signature_is_a_stable_32_char_digest(self) -> None:
        assert svc.instructions_signature({"slack": "focus #eng", "github": "triage"}) == (
            "5d9b930bab9ac32f51a58af28c9f63dc"
        )

    def test_the_signature_is_order_independent(self) -> None:
        assert svc.instructions_signature({"a": "1", "b": "2"}) == svc.instructions_signature(
            {"b": "2", "a": "1"}
        )

    def test_the_signature_changes_on_any_content_change(self) -> None:
        base = svc.instructions_signature({"slack": "a"})
        assert base != svc.instructions_signature({"slack": "b"})
        assert base != svc.instructions_signature({"slack": "a", "github": "c"})

    def test_the_projection_input_excludes_the_global_scope(self) -> None:
        every_scope = {GLOBAL_INSTRUCTIONS_SCOPE: "reply in Spanish", "slack": "focus #eng"}
        assert svc.integration_instructions(every_scope) == {"slack": "focus #eng"}
