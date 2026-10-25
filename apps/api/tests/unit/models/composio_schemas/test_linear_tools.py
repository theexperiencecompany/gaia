"""Unit tests for the Composio Linear tools schemas (linear_tools.py)."""

from app.models.composio_schemas.linear_tools import LinearGetAllTeamsData


class TestLinearGetAllTeamsData:
    def test_get_teams_prefers_items(self):
        m = LinearGetAllTeamsData(
            items=[{"id": "t1", "name": "ItemTeam"}],
            teams=[{"id": "t2", "name": "TeamTeam"}],
        )
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t1"]

    def test_get_teams_falls_back_to_teams(self):
        m = LinearGetAllTeamsData(
            items=[],
            teams=[{"id": "t2", "name": "TeamTeam"}],
        )
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t2"]

    def test_get_teams_skips_non_dicts(self):
        # `items` is list[dict], so non-dicts can only exist via model_construct
        # (bypasses validation); get_teams must still filter them out.
        m = LinearGetAllTeamsData.model_construct(items=[{"id": "t1"}, "junk", 42, None])
        teams = m.get_teams()
        assert [t.id for t in teams] == ["t1"]
