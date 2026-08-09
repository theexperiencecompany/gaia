"""Tests for app.constants.vfs."""

from __future__ import annotations

from app.constants.vfs import SYSTEM_USER_ID
from app.db.repositories.skills import SYSTEM_USER_ID as SKILLS_REPO_SYSTEM_USER_ID


class TestSystemUserId:
    def test_value(self) -> None:
        assert SYSTEM_USER_ID == "system"

    def test_matches_the_skills_repository_copy(self) -> None:
        # The same sentinel is defined in two places (constants/vfs.py and
        # db/repositories/skills.py); skills are seeded and filtered by
        # user_id="system", so a drift here would silently isolate every
        # system skill from every user.
        assert SYSTEM_USER_ID == SKILLS_REPO_SYSTEM_USER_ID
