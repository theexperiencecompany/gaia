"""Repository for the users collection.

Caching is on: every writer of the users collection now routes through this
repository, so a write refreshes the entity cache and bumps the generation —
a read can never serve a value staler than the last write. That guarantee is
what makes caching safe here at all: ``get_by_email`` is the authentication hot
path, so a stale hit would mean stale auth context, permissions and preferences.

This repository is global, so all three key families live under the ``global``
scope: any user's write bumps the single generation and orphans *every* user's
query-cache entries. Correct, and deliberately so — ``get_by_email`` cannot know
which user it will resolve to before it reads, so a per-user generation is not
expressible. The entity cache is keyed per user id and unaffected by the bump.

The one deliberate exception is ``touch_last_active``, which writes
``last_active_at`` through the cache-exempt path: it fires on every
authenticated request, so bumping the generation there would invalidate the
whole cache on every request and make it worse than useless. The cost is that a
cached read may carry a slightly stale ``last_active_at``; nothing reads that
field off a cached path (the inactivity scan is an uncached query).
"""

from datetime import UTC, datetime

from bson import ObjectId

from app.constants.cache import (
    LAST_ACTIVE_DEBOUNCE_SECONDS,
    LAST_ACTIVE_GATE_PREFIX,
    REPO_GLOBAL_SCOPE,
    USER_CACHE_PREFIX,
)
from app.constants.log_tags import LogTag
from app.db.redis import redis_cache
from app.db.repositories.base import MongoRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.onboarding_models import (
    ClarifyAnswerRecord,
    PersistedTriageSummary,
    SocialProfile,
    WritingStyleExampleBlocks,
)
from app.models.user_models import (
    BioStatus,
    OnboardingPhase,
    OnboardingPreferences,
    PlatformLinkRecord,
    UserDocument,
    UserUpdate,
)
from shared.py.wide_events import log

_SOCIAL_PROFILES_FIELD = "onboarding.social_profiles"


class UserRepository(MongoRepository[UserDocument, UserUpdate]):
    """The ``users`` collection repository — see the module docstring for the
    caching contract that makes reads here safe."""

    collection_name = "users"
    document_model = UserDocument
    update_model = UserUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix=USER_CACHE_PREFIX)

    # ---------------------------------------------------------------- reads

    @cached_query(UserDocument)
    async def get_by_email(self, email: str) -> UserDocument | None:
        """A user by email — the authentication hot path."""
        return await self._find_one({"email": email})

    async def find_by_ids(self, user_ids: list[str]) -> list[UserDocument]:
        """Users whose ``_id`` is in ``user_ids`` (invalid ids skipped) — the
        creator-join for the integrations marketplace."""
        oids = [ObjectId(uid) for uid in user_ids if ObjectId.is_valid(uid)]
        if not oids:
            return []
        return await self._find({"_id": {"$in": oids}})

    async def get_by_platform_id(self, platform: str, platform_user_id: str) -> UserDocument | None:
        """A user linked to ``platform_user_id`` on ``platform``."""
        return await self._find_one({f"platform_links.{platform}.id": platform_user_id})

    async def list_all_ids(self) -> list[str]:
        """Every user id — the bulk workspace-provisioning scan."""
        return [doc.id for doc in await self._find({})]

    async def count_created_before(self, created_at: datetime) -> int:
        """Number of users created before ``created_at`` — the holo-card rank."""
        return await self._count({"created_at": {"$lt": created_at}})

    # ------------------------------------------------------------ worker scans

    async def find_stuck_personalization(
        self, cutoff: datetime, *, limit: int = 50
    ) -> list[UserDocument]:
        """Users stuck at personalization-pending whose last update predates
        ``cutoff`` (or was never stamped) — the re-queue candidates."""
        return await self._find(
            {
                "onboarding.phase": OnboardingPhase.PERSONALIZATION_PENDING.value,
                "$or": [
                    {"updated_at": {"$lt": cutoff}},
                    {"updated_at": {"$exists": False}},
                ],
            },
            limit=limit,
        )

    async def find_inactive_email_candidates(self, before: datetime) -> list[UserDocument]:
        """Active users inactive since ``before`` who have not been emailed since
        then — the inactivity-email candidates (throttling is decided per user)."""
        return await self._find(
            {
                "last_active_at": {"$lt": before},
                "is_active": {"$ne": False},
                "$or": [
                    {"last_inactive_email_sent": {"$exists": False}},
                    {"last_inactive_email_sent": {"$lt": before}},
                ],
            }
        )

    async def find_dormant_since(self, before: datetime) -> list[UserDocument]:
        """Users with no activity since ``before`` — the dormancy sweep's cohort.
        ``last_active_at`` missing means the account has never been seen active, so
        those count as dormant too; without the ``$exists`` arm a `$lt` comparison
        silently skips them."""
        return await self._find(
            {
                "is_active": {"$ne": False},
                "$or": [
                    {"last_active_at": {"$lt": before}},
                    {"last_active_at": {"$exists": False}},
                    {"last_active_at": None},
                ],
            }
        )

    async def find_nurture_candidates(self, created_since: datetime) -> list[UserDocument]:
        """Recently-signed-up, still-active users — the nurture-sequence cohort.
        Send eligibility (timezone hour, frequency caps, step windows) is decided
        per user per run, not by this query."""
        return await self._find(
            {"created_at": {"$gte": created_since}, "is_active": {"$ne": False}},
        )

    def _backfill_query(
        self, active_since: datetime, eligible_before: datetime
    ) -> dict[str, object]:
        # ``_id`` is an ObjectId whose generation time is the account's creation
        # instant, so the launch cutoff is expressed against it directly — the
        # id-codec that belongs inside the repository.
        return {
            "last_active_at": {"$gte": active_since},
            "_id": {"$lt": ObjectId.from_datetime(eligible_before)},
            "memory_backfilled": {"$exists": False},
        }

    async def count_backfill_candidates(
        self, active_since: datetime, eligible_before: datetime
    ) -> int:
        """Recently-active, pre-launch users not yet memory-backfilled."""
        return await self._count(self._backfill_query(active_since, eligible_before))

    async def find_backfill_candidate_ids(
        self, active_since: datetime, eligible_before: datetime, *, limit: int
    ) -> list[str]:
        """Ids of the next batch of backfill candidates, most-recently-active first."""
        docs = await self._find(
            self._backfill_query(active_since, eligible_before),
            sort=[("last_active_at", -1)],
            limit=limit,
        )
        return [doc.id for doc in docs]

    async def list_platform_user_ids(self, platform: str, *, limit: int = 500) -> list[str]:
        """External ids of every user linked to ``platform``."""
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
            log.warning(
                f"{LogTag.API} touch_last_active failed for",
                email=email,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # ------------------------------------------------------- onboarding writes

    async def complete_onboarding(
        self,
        user_id: str,
        *,
        phase: OnboardingPhase,
        bio_status: BioStatus,
        pipeline_mode: str,
        preferences: OnboardingPreferences,
        name: str | None = None,
        timezone: str | None = None,
        completed_at: datetime | None = None,
        focus: str | None = None,
        clarify_answers: list[ClarifyAnswerRecord] | None = None,
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
            "onboarding.preferences": preferences.model_dump(),
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
        """Persist the user's selected integrations (onboarding)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.selected_integrations": integrations}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def update_onboarding_preferences(
        self, user_id: str, preferences: OnboardingPreferences
    ) -> UserDocument | None:
        """PATCH ``onboarding.preferences`` — only the fields the caller actually
        set are written, each at its own dotted path, so a partial save from one
        settings surface cannot clobber a field owned by another."""
        set_fields: dict[str, object] = {}
        for field, value in preferences.model_dump(exclude_unset=True).items():
            set_fields[f"onboarding.preferences.{field}"] = value
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)}, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )

    async def reset_onboarding(self, user_id: str) -> None:
        """Wipe the user's onboarding subdocument."""
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

    async def set_onboarding_phase(self, user_id: str, phase: OnboardingPhase) -> bool:
        """Set ``onboarding.phase``; returns whether the user existed (for a 404)."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.phase": phase}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    async def set_pipeline_completion(
        self, user_id: str, *, phase: OnboardingPhase, conversation_id: str | None = None
    ) -> None:
        """Advance the onboarding pipeline phase (optionally tying the first conversation)."""
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
        """Store the user's first message on their onboarding subdocument."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.first_message": first_message}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def mark_early_intelligence_done(self, user_id: str) -> None:
        """Stamp the early-intelligence onboarding completion."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.early_intelligence_done_at": _now()}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # ---------------------------------------------------------- HIL preferences

    async def set_hil_preference_fields(
        self,
        user_id: str,
        *,
        mode: str | None = None,
        tool_overrides: dict[str, bool] | None = None,
    ) -> None:
        """``$set`` the provided ``hil_preferences`` fields, leaving the rest alone."""
        set_fields: dict[str, object] = {}
        if mode is not None:
            set_fields["hil_preferences.mode"] = mode
        if tool_overrides is not None:
            set_fields["hil_preferences.tool_overrides"] = tool_overrides
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_hil_tool_override(self, user_id: str, tool_name: str, ask: bool | None) -> None:
        """Set (``ask`` = True/False) or clear (``ask`` = None) one HIL tool override.

        Touches only this tool's key, so toggling several tools at once (each switch
        on the integration panel fires its own request) cannot lose an override: a
        read-modify-write of the whole map would have each request overwrite the
        others' keys with the snapshot it read before they landed.

        ``$setField`` in an aggregation-pipeline update rather than a dotted ``$set``
        path because MCP tool names can contain dots (e.g. ``server.action``), which
        Mongo would split into a nested subdocument, diverging from the flat map the
        read path expects. A pipeline update cannot travel through
        ``_apply_raw_update`` (it takes an update *document*), so the cache steps it
        would have done — evict the entity, bump the generation — are applied here.
        """
        overrides_path = "hil_preferences.tool_overrides"
        await self._raw_collection().update_one(
            {"_id": self._id_value(user_id)},
            [
                {
                    "$set": {
                        overrides_path: {
                            "$setField": {
                                "field": {"$literal": tool_name},
                                "input": {"$ifNull": [f"${overrides_path}", {}]},
                                "value": "$$REMOVE" if ask is None else ask,
                            }
                        }
                    }
                }
            ],
        )
        await self._cache_evict(REPO_GLOBAL_SCOPE, user_id)
        await self._invalidate(REPO_GLOBAL_SCOPE)

    async def set_suggested_workflows(self, user_id: str, workflow_ids: list[str]) -> None:
        """Persist the suggested workflows shown to the user during onboarding."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.suggested_workflows": workflow_ids}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_social_profiles_if_unset(
        self, user_id: str, profiles: list[SocialProfile]
    ) -> None:
        """Persist social profiles only if not already set (idempotent first-write)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {_SOCIAL_PROFILES_FIELD: [p.model_dump() for p in profiles]}},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={
                "$or": [
                    {_SOCIAL_PROFILES_FIELD: {"$exists": False}},
                    {_SOCIAL_PROFILES_FIELD: None},
                    {_SOCIAL_PROFILES_FIELD: []},
                ]
            },
            return_document=False,
        )

    async def set_writing_style_and_triage(
        self,
        user_id: str,
        *,
        writing_style_summary: str | None = None,
        writing_style_example: WritingStyleExampleBlocks | None = None,
        triage_summary: PersistedTriageSummary | None = None,
    ) -> None:
        """Persist any provided writing-style / triage summaries on onboarding."""
        set_fields: dict[str, object] = {}
        if writing_style_summary is not None:
            set_fields["onboarding.writing_style.summary"] = writing_style_summary
        if writing_style_example is not None:
            set_fields["onboarding.writing_style.example"] = writing_style_example.model_dump()
        if triage_summary is not None:
            set_fields["onboarding.triage_summary"] = triage_summary.model_dump()
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_bio_status(self, user_id: str, bio_status: BioStatus) -> None:
        """Update the onboarding bio-generation status (e.g. back to processing on a
        post-onboarding Gmail reconnect)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.bio_status": bio_status}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_writing_style_user_summary(self, user_id: str, summary: str) -> None:
        """Persist a user-edited writing-style summary as the canonical style."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.writing_style.user_edited_summary": summary}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_social_profiles(self, user_id: str, profiles: list[SocialProfile]) -> None:
        """Overwrite the stored social profiles (user-confirmed selection)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {_SOCIAL_PROFILES_FIELD: [p.model_dump() for p in profiles]}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def save_personalization(
        self,
        user_id: str,
        *,
        house: str,
        personality_phrase: str,
        user_bio: str,
        bio_status: BioStatus,
        account_number: int,
        member_since: str,
        overlay_color: str,
        overlay_opacity: int,
        workflow_ids: list[str],
    ) -> None:
        """Persist the generated personalization bundle and advance the phase to
        personalization-complete."""
        set_fields: dict[str, object] = {
            "onboarding.house": house,
            "onboarding.personality_phrase": personality_phrase,
            "onboarding.user_bio": user_bio,
            "onboarding.bio_status": bio_status,
            "onboarding.phase": OnboardingPhase.PERSONALIZATION_COMPLETE.value,
            "onboarding.account_number": account_number,
            "onboarding.member_since": member_since,
            "onboarding.overlay_color": overlay_color,
            "onboarding.overlay_opacity": overlay_opacity,
        }
        if workflow_ids:
            set_fields["onboarding.suggested_workflows"] = workflow_ids
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # ---------------------------------------------------- lifecycle-job markers

    async def record_inactive_email(self, user_id: str, count: int) -> None:
        """Stamp the inactivity-email send: the send time and the episode counter.

        ``count`` is set (not incremented) so the counter restarts at 1 for a new
        inactivity episode and absorbs pre-counter docs whose one prior send is
        recorded only in the timestamp."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    "last_inactive_email_sent": datetime.now(UTC),
                    "inactive_email_count": count,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def record_nurture_step(
        self, user_id: str, step_key: str, *, at: datetime, status: str
    ) -> None:
        """Record one nurture-step outcome on the user document.

        ``completed_steps`` uses ``$addToSet`` (a step can never be re-sent), and
        ``history`` appends the outcome so the frequency caps can be enforced."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$addToSet": {"nurture.completed_steps": step_key},
                "$push": {"nurture.history": {"step": step_key, "at": at, "status": status}},
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def claim_limit_email_slot(
        self, user_id: str, *, stale_before: datetime
    ) -> UserDocument | None:
        """Take the weekly limit-email slot, or return None if it is already taken.

        Stamping the marker AFTER sending let two concurrent limit hits both read
        an eligible user and both send — the read and the write straddle a network
        send, so the window is wide, not theoretical. The claim is one conditional
        update: only a document whose marker is missing or older than
        ``stale_before`` matches, so exactly one caller wins and the loser sends
        nothing.

        Returns the BEFORE image, whose ``last_limit_email_sent`` is the value to
        put back if the send then fails (see ``release_limit_email_slot``).
        """
        return await self._apply_raw_update(
            {
                "_id": self._id_value(user_id),
                "$or": [
                    {"last_limit_email_sent": None},
                    {"last_limit_email_sent": {"$lt": stale_before}},
                ],
            },
            {"$set": {"last_limit_email_sent": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def release_limit_email_slot(self, user_id: str, previous: datetime | None) -> None:
        """Put the weekly marker back after a claimed send failed.

        Without this a failed send burns the whole week: the marker says an email
        went out when none did, and the user hears nothing for seven days.
        """
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"last_limit_email_sent": previous}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def record_activity_tier_promotion(
        self, user_id: str, tier: str, lower_tiers: list[str]
    ) -> UserDocument | None:
        """Persist ``tier`` as the user's highest activity badge ever reached;
        return the updated document only on a FIRST-TIME promotion, else None.

        The guard is monotonic — a stored tier is only ever replaced by one in
        ``lower_tiers``' complement — so downgrades are silent and re-crossing a
        boundary can never re-fire. The filtered update is also the idempotency
        lock: a retried job matches zero documents the second time.

        A ``user_id`` that is not a valid ObjectId (synthetic/dev identities in
        the rollups) is skipped with a warning rather than failing the sweep —
        id-encoding concerns stay inside the repository layer.
        """
        if not ObjectId.is_valid(user_id):
            log.warning(
                "[repository] tier promotion skipped non-ObjectId user_id",
                user={"id": user_id},
            )
            return None
        return await self._apply_raw_update(
            {
                "_id": self._id_value(user_id),
                "$or": [
                    {"highest_activity_tier": {"$exists": False}},
                    {"highest_activity_tier": {"$in": lower_tiers}},
                ],
            },
            {
                "$set": {
                    "highest_activity_tier": tier,
                    "highest_activity_tier_at": datetime.now(UTC),
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    async def mark_memory_backfilled(self, user_id: str) -> None:
        """Stamp the memory-backfill marker so the daily cron won't re-select the user."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"memory_backfilled": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # --------------------------------------------------- background-job markers

    async def set_active_job(self, user_id: str, field: str, job_id: str) -> None:
        """Mark an in-flight background job for the user (``field`` → ``job_id``)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {field: job_id}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def clear_active_job(self, user_id: str, field: str) -> None:
        """Clear the user's in-flight background-job marker."""
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
        email: bool | None = None,
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
        if email is not None:
            set_fields["notification_channel_prefs.email"] = email
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def mark_email_processing_complete(self, user_id: str, memory_count: int) -> None:
        """Mark the user's Gmail→memory processing as complete."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    "email_memory_processed": True,
                    "email_memory_processed_at": datetime.now(UTC),
                    "email_memory_count": memory_count,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_gmail_scan_timestamp(self, user_id: str, timestamp: datetime) -> None:
        """Record the last Gmail scan time so the next scan only fetches newer mail."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"integration_scan_states.gmail.last_scan_timestamp": timestamp}},
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
        self, user_id: str, platform: str, link: PlatformLinkRecord, connected_at: str
    ) -> UserDocument | None:
        """Link the user to an external platform account."""
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
        """Remove the user's link to an external platform account."""
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
