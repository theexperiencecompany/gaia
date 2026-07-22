"""Repository for the users collection.

Ships with ``cache_policy=None`` on purpose: many user writers are not migrated
yet and write the collection directly, so caching reads here would serve stale
user context after those un-migrated writes. Caching turns on once the domain is
fully routed through this repository. ``touch_last_active`` already uses the
cache-exempt write path so it needs no change when that happens.
"""

from datetime import UTC, datetime

from app.constants.cache import (
    LAST_ACTIVE_DEBOUNCE_SECONDS,
    LAST_ACTIVE_GATE_PREFIX,
    REPO_GLOBAL_SCOPE,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.base import MongoRepository
from app.models.user_models import UserDocument, UserUpdate
from shared.py.wide_events import log


class UserRepository(MongoRepository[UserDocument, UserUpdate]):
    collection_name = "users"
    document_model = UserDocument
    update_model = UserUpdate
    uses_object_id = True
    cache_policy = None

    # ---------------------------------------------------------------- reads

    async def get_by_email(self, email: str) -> UserDocument | None:
        return await self._find_one({"email": email})

    async def get_by_platform_id(self, platform: str, platform_user_id: str) -> UserDocument | None:
        return await self._find_one({f"platform_links.{platform}.id": platform_user_id})

    async def count_created_before(self, created_at: datetime) -> int:
        """Number of users created before ``created_at`` — the holo-card rank."""
        return await self._count({"created_at": {"$lt": created_at}})

    async def list_platform_user_ids(self, platform: str, *, limit: int = 500) -> list[str]:
        field = f"platform_links.{platform}.id"
        docs = await self._find({field: {"$exists": True}}, limit=limit)
        ids: list[str] = []
        for doc in docs:
            entry = (doc.platform_links or {}).get(platform)
            if isinstance(entry, dict):
                platform_user_id = entry.get("id")
                if isinstance(platform_user_id, str):
                    ids.append(platform_user_id)
        return ids

    # ------------------------------------------------------- last-active bump

    async def touch_last_active(self, email: str) -> None:
        """Debounced, cache-exempt ``last_active_at`` bump. Never raises into the
        caller — a failed touch logs and continues so it can't fail authentication.

        A Redis ``SET NX EX`` gate collapses the per-request writes to one per user
        per debounce window. If Redis is unavailable the gate is skipped and every
        call writes — correctness over the write-rate optimization.
        """
        try:
            client = redis_cache.redis
            if client is not None:
                acquired = await client.set(
                    f"{LAST_ACTIVE_GATE_PREFIX}:{email}",
                    "1",
                    nx=True,
                    ex=LAST_ACTIVE_DEBOUNCE_SECONDS,
                )
                if not acquired:
                    return
            await self._update_fields_no_invalidate(
                {"email": email}, {"last_active_at": datetime.now(UTC)}
            )
        except Exception as exc:
            log.warning(f"{LogTag.API} touch_last_active failed for {email}: {exc}")

    # ------------------------------------------------------- onboarding writes

    async def complete_onboarding(
        self,
        user_id: str,
        *,
        phase: str,
        bio_status: str,
        pipeline_mode: str,
        preferences: dict[str, object],
        name: str | None = None,
        timezone: str | None = None,
        completed_at: datetime | None = None,
        focus: str | None = None,
        clarify_answers: list[dict[str, object]] | None = None,
        selected_integrations: list[str] | None = None,
    ) -> UserDocument | None:
        """Atomically create the ``onboarding`` subdocument (gated on its absence).

        Returns ``None`` when the gate misses — either onboarding already exists
        (idempotent replay) or the user is gone; the caller distinguishes via
        ``get``.
        """
        now = datetime.now(UTC)
        set_fields: dict[str, object] = {
            "onboarding.completed": True,
            "onboarding.completed_at": completed_at or now,
            "onboarding.phase": phase,
            "onboarding.bio_status": bio_status,
            "onboarding.preferences": preferences,
            "onboarding.pipeline_mode": pipeline_mode,
        }
        if name is not None:
            set_fields["name"] = name
        if timezone is not None:
            set_fields["timezone"] = timezone
        if focus is not None:
            set_fields["onboarding.focus"] = focus
        if clarify_answers is not None:
            set_fields["onboarding.clarify_answers"] = clarify_answers
        if selected_integrations is not None:
            set_fields["onboarding.selected_integrations"] = selected_integrations
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={"onboarding": {"$exists": False}},
        )

    async def set_selected_integrations(self, user_id: str, integrations: list[str]) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.selected_integrations": integrations}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def update_onboarding_preferences(
        self, user_id: str, preferences_patch: dict[str, object]
    ) -> UserDocument | None:
        set_fields: dict[str, object] = {}
        for field, value in preferences_patch.items():
            set_fields[f"onboarding.preferences.{field}"] = value
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)}, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )

    async def reset_onboarding(self, user_id: str) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$unset": {"onboarding": ""}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def clear_onboarding(self, user_id: str) -> None:
        """Roll back a partially-created onboarding subdocument."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$unset": {"onboarding": ""}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # ---------------------------------------------------- intelligence writes

    async def set_pipeline_completion(
        self, user_id: str, *, phase: str, conversation_id: str | None = None
    ) -> None:
        set_fields: dict[str, object] = {"onboarding.phase": phase}
        if conversation_id is not None:
            set_fields["onboarding.first_message_conversation_id"] = conversation_id
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_first_message(self, user_id: str, first_message: str) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.first_message": first_message}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def mark_early_intelligence_done(self, user_id: str) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.early_intelligence_done_at": _now()}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_suggested_workflows(self, user_id: str, workflow_ids: list[str]) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.suggested_workflows": workflow_ids}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_social_profiles_if_unset(
        self, user_id: str, profiles: list[dict[str, object]]
    ) -> None:
        """Persist social profiles only if not already set (idempotent first-write)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.social_profiles": profiles}},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={
                "$or": [
                    {"onboarding.social_profiles": {"$exists": False}},
                    {"onboarding.social_profiles": None},
                    {"onboarding.social_profiles": []},
                ]
            },
            return_document=False,
        )

    async def set_writing_style_and_triage(
        self,
        user_id: str,
        *,
        writing_style_summary: str | None = None,
        writing_style_example: dict[str, object] | None = None,
        triage_summary: dict[str, object] | None = None,
    ) -> None:
        set_fields: dict[str, object] = {}
        if writing_style_summary is not None:
            set_fields["onboarding.writing_style.summary"] = writing_style_summary
        if writing_style_example is not None:
            set_fields["onboarding.writing_style.example"] = writing_style_example
        if triage_summary is not None:
            set_fields["onboarding.triage_summary"] = triage_summary
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # --------------------------------------------------- background-job markers

    async def set_active_job(self, user_id: str, field: str, job_id: str) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {field: job_id}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def clear_active_job(self, user_id: str, field: str) -> None:
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$unset": {field: ""}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def clear_active_job_if_matches(self, user_id: str, field: str, job_id: str) -> None:
        """Clear the job marker only if it still holds ``job_id`` (compare-and-clear)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$unset": {field: ""}},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={field: job_id},
            return_document=False,
        )

    # --------------------------------------------------------- settings writes

    async def set_channel_preferences(
        self,
        user_id: str,
        *,
        telegram: bool | None = None,
        discord: bool | None = None,
        whatsapp: bool | None = None,
        slack: bool | None = None,
    ) -> None:
        """Set the given notification channel flags; unspecified channels are left
        untouched (a ``None`` argument is not written)."""
        set_fields: dict[str, object] = {}
        if telegram is not None:
            set_fields["notification_channel_prefs.telegram"] = telegram
        if discord is not None:
            set_fields["notification_channel_prefs.discord"] = discord
        if whatsapp is not None:
            set_fields["notification_channel_prefs.whatsapp"] = whatsapp
        if slack is not None:
            set_fields["notification_channel_prefs.slack"] = slack
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_selected_voice(self, user_id: str, voice_id: str) -> None:
        """Persist the user's selected TTS voice id."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"selected_voice_id": voice_id}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_starred_voices(self, user_id: str, voice_ids: list[str]) -> None:
        """Replace the user's starred voice id set."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"starred_voice_ids": voice_ids}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_holo_card_colors(
        self, user_id: str, overlay_color: str, overlay_opacity: int
    ) -> bool:
        """Set the holo-card overlay color/opacity; returns whether the user existed."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    "onboarding.overlay_color": overlay_color,
                    "onboarding.overlay_opacity": overlay_opacity,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    async def set_provider_metadata(
        self, user_id: str, provider: str, metadata: dict[str, str]
    ) -> bool:
        """Store a provider's extracted user metadata under ``provider_metadata``.
        Returns whether the user existed (the write landed)."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {f"provider_metadata.{provider}": metadata}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    # ------------------------------------------------------- platform linking

    async def link_platform(
        self, user_id: str, platform: str, link: dict[str, object], connected_at: str
    ) -> UserDocument | None:
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    f"platform_links.{platform}": link,
                    f"platform_links_connected_at.{platform}": connected_at,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    async def unlink_platform(self, user_id: str, platform: str) -> UserDocument | None:
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$unset": {
                    f"platform_links.{platform}": "",
                    f"platform_links_connected_at.{platform}": "",
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )


def _now() -> datetime:
    return datetime.now(UTC)


user_repository = UserRepository()
