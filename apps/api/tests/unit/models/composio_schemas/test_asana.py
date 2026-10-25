"""Unit tests for app/models/composio_schemas/asana.py."""

from app.models.trigger_configs import AsanaTaskTriggerConfig


class TestAsanaTaskTriggerConfigLegacyMigration:
    def test_legacy_project_id_migrates_to_project_gid(self):
        # Stored workflows from the retired unscoped trigger carry project_id.
        m = AsanaTaskTriggerConfig.model_validate(
            {"trigger_name": "asana_task_trigger", "project_id": "1213430481840948"}
        )
        assert m.project_gid == "1213430481840948"

    def test_explicit_project_gid_wins_over_legacy(self):
        m = AsanaTaskTriggerConfig(project_id="old", project_gid="new")
        assert m.project_gid == "new"

    def test_no_legacy_field_stays_empty(self):
        m = AsanaTaskTriggerConfig()
        assert m.project_gid == ""

    def test_empty_project_gid_falls_back_to_the_legacy_project_id(self):
        # A present-but-empty project_gid is no scope; the legacy project_id still is.
        m = AsanaTaskTriggerConfig.model_validate(
            {"trigger_name": "asana_task_trigger", "project_gid": "", "project_id": "123"}
        )
        assert m.project_gid == "123"
