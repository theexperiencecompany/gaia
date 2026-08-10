"""Repository for the ``skills`` collection — the installed-skills registry.

Global (system skills, ``user_id="system"``, are shared across all users), keyed
by a caller-minted UUID stored as the string ``_id``. Timestamps are stored as
ISO-format strings, so the base's datetime auto-stamp is turned off and the
repository writes ``updated_at`` itself.
"""

from datetime import UTC, datetime

from app.agents.skills.models import Skill, SkillUpdate
from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository

SYSTEM_USER_ID = "system"


class SkillsRepository(MongoRepository[Skill, SkillUpdate]):
    collection_name = "skills"
    document_model = Skill
    update_model = SkillUpdate
    uses_object_id = False
    cache_policy = None
    auto_stamp_timestamps = False  # installed_at/updated_at are ISO strings, written by hand

    async def find_by_name(
        self, user_id: str, name: str, target: str | None = None
    ) -> Skill | None:
        query: dict[str, object] = {"user_id": user_id, "name": name}
        if target:
            query["target"] = target
        return await self._find_one(query)

    async def get_for_user(self, skill_id: str, user_id: str) -> Skill | None:
        return await self._find_one({"_id": skill_id, "user_id": user_id})

    async def delete_for_user(self, skill_id: str, user_id: str) -> bool:
        deleted = await self._delete_many(
            {"_id": skill_id, "user_id": user_id}, scope=REPO_GLOBAL_SCOPE
        )
        return deleted > 0

    async def list_for_user(
        self, user_id: str, *, target: str | None = None, enabled_only: bool = False
    ) -> list[Skill]:
        query: dict[str, object] = {"user_id": user_id}
        if target:
            query["target"] = target
        if enabled_only:
            query["enabled"] = True
        return await self._find(query, sort=[("installed_at", -1)], limit=500)

    async def for_agent(self, user_id: str, agent_name: str) -> list[Skill]:
        """Enabled skills targeting ``agent_name`` — the user's own plus the
        shared system skills (``user_id="system"``)."""
        return await self._find(
            {
                "enabled": True,
                "target": agent_name,
                "$or": [{"user_id": user_id}, {"user_id": SYSTEM_USER_ID}],
            },
            sort=[("installed_at", -1)],
            limit=500,
        )

    async def set_enabled(self, user_id: str, skill_id: str, enabled: bool) -> bool:
        """Flip a skill's enabled flag. Returns whether it actually changed — the
        ``$ne`` guard makes a no-op toggle report ``False`` (matches the old
        ``modified_count`` check)."""
        matched = await self._apply_raw_update_unfetched(
            {"_id": skill_id, "user_id": user_id, "enabled": {"$ne": enabled}},
            {"$set": {"enabled": enabled, "updated_at": datetime.now(UTC).isoformat()}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return matched > 0

    async def patch(self, user_id: str, skill_id: str, *, update: SkillUpdate) -> Skill | None:
        """Apply a metadata patch (always stamping ``updated_at``); ``None`` if no
        matching skill exists for the user."""
        set_fields = update.model_dump(exclude_unset=True)
        set_fields["updated_at"] = datetime.now(UTC).isoformat()
        return await self._apply_raw_update(
            {"_id": skill_id, "user_id": user_id},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
        )


skill_repository = SkillsRepository()
