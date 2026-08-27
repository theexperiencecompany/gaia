"""Unit tests for app/models/composio_schemas/asana.py."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.asana import AsanaTaskCreatedPayload


class TestAsanaTaskCreatedPayload:
    # Field set verified against Composio triggers_types API (2026-08).
    def test_valid_full(self):
        m = AsanaTaskCreatedPayload(
            created_at="2025-01-01T00:00:00Z",
            project_gid="1213430481840948",
            task_gid="1213430481840949",
            user_gid="1200000000000001",
        )
        assert m.project_gid == "1213430481840948"
        assert m.task_gid == "1213430481840949"
        assert m.user_gid == "1200000000000001"

    def test_valid_minimal(self):
        m = AsanaTaskCreatedPayload()
        assert m.task_gid is None

    def test_wrong_type_project_gid(self):
        with pytest.raises(ValidationError):
            AsanaTaskCreatedPayload(project_gid=123)


class TestAsanaTaskTriggerConfigLegacyMigration:
    def test_legacy_project_id_migrates_to_project_gid(self):
        from app.models.trigger_configs import AsanaTaskTriggerConfig

        # Stored workflows from the retired unscoped trigger carry project_id.
        m = AsanaTaskTriggerConfig.model_validate(
            {"trigger_name": "asana_task_trigger", "project_id": "1213430481840948"}
        )
        assert m.project_gid == "1213430481840948"

    def test_explicit_project_gid_wins_over_legacy(self):
        from app.models.trigger_configs import AsanaTaskTriggerConfig

        m = AsanaTaskTriggerConfig(project_id="old", project_gid="new")
        assert m.project_gid == "new"

    def test_no_legacy_field_stays_empty(self):
        from app.models.trigger_configs import AsanaTaskTriggerConfig

        m = AsanaTaskTriggerConfig()
        assert m.project_gid == ""


# ---------------------------------------------------------------------------
# todoist trigger payloads
# ---------------------------------------------------------------------------
