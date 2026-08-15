"""Unit tests for the Composio Linear tools schemas (linear_tools.py)."""

from pydantic import ValidationError
import pytest

from app.models.composio_schemas.linear_tools import (
    LinearGetAllTeamsData,
    LinearGetAllTeamsInput,
    LinearMember,
    LinearTeam,
)


class TestLinearGetAllTeamsInput:
    def test_valid_empty(self):
        m = LinearGetAllTeamsInput()
        assert m.model_dump() == {}


class TestLinearMember:
    def test_valid_minimal(self):
        m = LinearMember(id="mem1")
        assert m.id == "mem1"
        assert m.name == ""
        assert m.email == ""

    def test_valid_full(self):
        m = LinearMember(id="mem1", name="Alice", email="a@b.com")
        assert m.name == "Alice"
        assert m.email == "a@b.com"

    def test_extra_fields_ignored(self):
        m = LinearMember(id="mem1", displayName="ignored")
        assert not hasattr(m, "displayName")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            LinearMember()

    def test_wrong_type_email(self):
        with pytest.raises(ValidationError):
            LinearMember(id="mem1", email=123)


class TestLinearTeam:
    def test_valid_minimal(self):
        m = LinearTeam(id="team1")
        assert m.id == "team1"
        assert m.key == ""
        assert m.name == ""
        assert m.members == []

    def test_valid_full(self):
        m = LinearTeam(
            id="team1",
            key="ENG",
            name="Engineering",
            members=[LinearMember(id="mem1", name="Alice")],
        )
        assert m.key == "ENG"
        assert m.members[0].name == "Alice"

    def test_members_from_dicts(self):
        m = LinearTeam.model_validate({"id": "team1", "members": [{"id": "mem1", "name": "Alice"}]})
        assert m.members[0].name == "Alice"

    def test_extra_fields_ignored(self):
        m = LinearTeam(id="team1", icon="ignored")
        assert not hasattr(m, "icon")

    def test_missing_id(self):
        with pytest.raises(ValidationError):
            LinearTeam()

    def test_wrong_type_members(self):
        with pytest.raises(ValidationError):
            LinearTeam(id="team1", members=["not-a-member"])


class TestLinearGetAllTeamsData:
    def test_defaults(self):
        m = LinearGetAllTeamsData()
        assert m.items == []
        assert m.teams == []
        assert m.get_teams() == []

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

    def test_get_teams_skips_missing_id(self):
        m = LinearGetAllTeamsData(items=[{"name": "no-id"}])
        with pytest.raises(ValidationError):
            m.get_teams()

    def test_extra_fields_ignored(self):
        m = LinearGetAllTeamsData(items=[], extra="dropped")
        assert not hasattr(m, "extra")
