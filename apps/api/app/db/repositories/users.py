"""Repository for the users collection.

Caching is on: every writer routes through this repository, so a write
refreshes the entity cache and bumps the generation — a read can never serve
a value staler than the last write, which is what makes caching safe for
get_by_email, the authentication hot path.

This repository is global, so any user's write bumps the single generation
and orphans *every* user's query-cache entries — deliberate, since
get_by_email cannot know which user it will resolve to before it reads.

The one exception is set_last_active, which writes last_active_at through
the cache-exempt path: it fires on every active minute, so bumping the
generation there would invalidate the whole cache. A cached read may carry a
stale last_active_at; activity is read through get_activity_dates instead.
"""

from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, datetime
from typing import cast

from bson import ObjectId

from app.config.feature_flags import FeatureFlag
from app.constants.briefing import BriefingBag
from app.constants.cache import (
    REPO_GLOBAL_SCOPE,
    USER_CACHE_PREFIX,
)
from app.constants.email import SignupDelivery
from app.constants.first_steps import (
    FIRST_STEPS_COLLAPSED_AT_FIELD,
    FIRST_STEPS_COLLAPSED_FIELD,
)
from app.constants.notifications import DEFAULT_CHANNEL_PREFERENCES
from app.constants.onboarding import (
    GETTING_STARTED_CONVERSATION_ID_FIELD,
    GMAIL_PERSONALIZATION_MARKER,
    HOLO_CONVERSATION_ID_FIELD,
)
from app.constants.user_activity import ActivityStatus
from app.db.repositories.base import MongoRepository, cached_query
from app.db.repositories.cache import CachePolicy
from app.models.briefing_models import BriefingSchedule
from app.models.notification.notification_models import QuietHours
from app.models.onboarding_models import (
    PersistedTriageSummary,
    SocialProfile,
    WritingStyleExampleBlocks,
)
from app.models.user_activity_models import UserActivityDates, status_window
from app.models.user_models import (
    BioStatus,
    BriefingBootstrap,
    DayZeroHello,
    OnboardingPhase,
    OnboardingPreferences,
    PersonalizationBundle,
    PlatformLinkRecord,
    ShuffleBag,
    UserDocument,
    UserUpdate,
)
from shared.py.wide_events import log

_SOCIAL_PROFILES_FIELD = "onboarding.social_profiles"
# $unset reads only the field names; the value is ignored.
_UNSET = ""


class UserRepository(MongoRepository[UserDocument, UserUpdate]):
    """The users collection repository — see the module docstring for the caching contract."""

    collection_name = "users"
    document_model = UserDocument
    update_model = UserUpdate
    uses_object_id = True
    cache_policy = CachePolicy(prefix=USER_CACHE_PREFIX)

    # ---------------------------------------------------------------- reads

    @cached_query(UserDocument)
    async def get_by_email(self, email: str) -> UserDocument | None:
        """Return a user by email — the authentication hot path."""
        return await self._find_one({"email": email})

    async def find_by_ids(self, user_ids: list[str]) -> list[UserDocument]:
        """Return users whose _id is in user_ids (invalid ids skipped) — the marketplace creator-join."""
        oids = [ObjectId(uid) for uid in user_ids if ObjectId.is_valid(uid)]
        if not oids:
            return []
        return await self._find({"_id": {"$in": oids}})

    async def get_by_platform_id(self, platform: str, platform_user_id: str) -> UserDocument | None:
        """Return a user linked to platform_user_id on platform."""
        return await self._find_one({f"platform_links.{platform}.id": platform_user_id})

    async def list_all_ids(self) -> list[str]:
        """Return every user id — the bulk workspace-provisioning scan."""
        return [doc.id for doc in await self._find({})]

    async def find_named_with_email(self) -> list[UserDocument]:
        """Return every user holding both a name and an email — the derived-name cleanup scan."""
        return await self._find({"name": {"$nin": [None, ""]}, "email": {"$nin": [None, ""]}})

    async def count_created_before(self, created_at: datetime) -> int:
        """Return the number of users created before created_at — the holo-card rank."""
        return await self._count({"created_at": {"$lt": created_at}})

    # ------------------------------------------------------------ worker scans

    # The cohort reads below are lenient: a legacy row with a malformed
    # ``onboarding`` used to raise above the per-user try/except in every
    # sweep, denying mail to the whole cohort. It is now skipped and logged.
    async def find_stuck_personalization(
        self, cutoff: datetime, *, limit: int = 50
    ) -> list[UserDocument]:
        """Users stuck at personalization-pending, last updated before cutoff or never stamped."""
        return await self._find_lenient(
            {
                "onboarding.phase": OnboardingPhase.PERSONALIZATION_PENDING.value,
                "$or": [
                    {"updated_at": {"$lt": cutoff}},
                    {"updated_at": {"$exists": False}},
                ],
            },
            limit=limit,
        )

    def _activity_filter(self, status: ActivityStatus, now: datetime) -> dict[str, object]:
        """Match users whose last-seen instant (last_active_at, else created_at) is in status."""
        after, until = status_window(status, now)
        window: dict[str, datetime] = {}
        if after is not None:
            window["$gt"] = after
        if until is not None:
            window["$lte"] = until
        branches: list[dict[str, object]] = [
            {"last_active_at": window},
            {"last_active_at": None, "created_at": window},
        ]
        if status is ActivityStatus.DORMANT:
            branches.append({"last_active_at": None, "created_at": None})
        return {"$or": branches}

    async def find_by_activity_status(
        self, status: ActivityStatus, *, among: Collection[str] | None = None
    ) -> list[UserDocument]:
        """Live users in status now, optionally only those whose id is in among (invalid ids skipped)."""
        query: dict[str, object] = {
            **self._activity_filter(status, datetime.now(UTC)),
            "is_active": {"$ne": False},
        }
        if among is not None:
            query["_id"] = {
                "$in": [self._id_value(user_id) for user_id in among if self.is_valid_id(user_id)]
            }
        return await self._find_lenient(query)

    async def find_nurture_candidates(self, created_since: datetime) -> list[UserDocument]:
        """Recently-signed-up, still-active users — the nurture-sequence cohort.

        Send eligibility (timezone hour, frequency caps, step windows) is
        decided per user per run, not by this query.
        """
        return await self._find_lenient(
            {"created_at": {"$gte": created_since}, "is_active": {"$ne": False}},
        )

    async def find_undelivered_signup_ids(
        self, created_since: datetime, *, limit: int
    ) -> list[str]:
        """Ids of recent signups still missing at least one delivery stamp.

        created_since is load-bearing rather than cosmetic: every account
        that predates the stamps is missing both, so an unbounded window would
        hand the entire user base to the recovery sweep.
        """
        docs = await self._find(
            {
                "created_at": {"$gte": created_since},
                "$or": [{delivery.value: {"$exists": False}} for delivery in SignupDelivery],
            },
            sort=[("created_at", -1)],
            limit=limit,
        )
        return [doc.id for doc in docs]

    def _backfill_query(self, eligible_before: datetime) -> dict[str, object]:
        # ``_id`` is an ObjectId whose generation time is the account's creation
        # instant, so the launch cutoff is expressed against it directly — the
        # id-codec that belongs inside the repository.
        return {
            **self._activity_filter(ActivityStatus.ACTIVE, datetime.now(UTC)),
            "_id": {"$lt": ObjectId.from_datetime(eligible_before)},
            "memory_backfilled": {"$exists": False},
        }

    async def count_backfill_candidates(self, eligible_before: datetime) -> int:
        """Active, pre-launch users not yet memory-backfilled."""
        return await self._count(self._backfill_query(eligible_before))

    async def find_backfill_candidate_ids(
        self, eligible_before: datetime, *, limit: int
    ) -> list[str]:
        """Ids of the next batch of backfill candidates, most-recently-active first."""
        docs = await self._find(
            self._backfill_query(eligible_before),
            sort=[("last_active_at", -1)],
            limit=limit,
        )
        return [doc.id for doc in docs]

    async def list_platform_user_ids(self, platform: str, *, limit: int = 500) -> list[str]:
        """External ids of every user linked to platform."""
        field = f"platform_links.{platform}.id"
        docs = await self._find({field: {"$exists": True}}, limit=limit)
        ids: list[str] = []
        for doc in docs:
            entry = (doc.platform_links or {}).get(platform)
            if isinstance(entry, dict):
                link: PlatformLinkRecord = cast(PlatformLinkRecord, entry)
                platform_user_id = link.get("id")
                if isinstance(platform_user_id, str):
                    ids.append(platform_user_id)
        return ids

    # ------------------------------------------------------- activity

    async def get_activity_dates(self, user_id: str) -> UserActivityDates | None:
        """Read the user's activity dates from Mongo, never the cache.

        set_last_active skips the cache, so a cached user can carry a
        last_active_at that is days old.
        """
        return await self._find_one_projected(
            self._identity_filter(user_id),
            {"last_active_at": 1, "created_at": 1},
            UserActivityDates,
        )

    async def set_last_active(self, user_id: str, at: datetime) -> None:
        """Write last_active_at past the cache: it moves on every active minute.

        Bumping the generation that often would invalidate every user's cache,
        and nothing reads activity off a cached user (see get_activity_dates).
        """
        await self._update_fields_no_invalidate(
            self._identity_filter(user_id), {"last_active_at": at}
        )

    # ------------------------------------------------------- onboarding writes

    async def complete_onboarding(
        self,
        user_id: str,
        *,
        phase: OnboardingPhase,
        bio_status: BioStatus,
        preferences: OnboardingPreferences,
        timezone: str | None = None,
        completed_at: datetime | None = None,
    ) -> UserDocument | None:
        """Atomically mark onboarding complete (gated on it not being complete yet).

        The gate is onboarding.completed, not the subdocument's existence,
        since the wizard writes onboarding.preferences before payment. None
        when the gate misses — already completed, or the user is gone.
        """
        now = datetime.now(UTC)
        set_fields: dict[str, object] = {
            "onboarding.completed": True,
            "onboarding.completed_at": completed_at or now,
            "onboarding.phase": phase,
            "onboarding.bio_status": bio_status,
            "onboarding.preferences": preferences.model_dump(),
        }
        if timezone is not None:
            set_fields["timezone"] = timezone
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            extra_filter={"onboarding.completed": {"$ne": True}},
        )

    async def update_onboarding_preferences(
        self, user_id: str, preferences: OnboardingPreferences
    ) -> UserDocument | None:
        """PATCH onboarding.preferences, field by dotted path, so one settings surface can't clobber another."""
        set_fields: dict[str, object] = {}
        for field, value in preferences.model_dump(exclude_unset=True).items():
            set_fields[f"onboarding.preferences.{field}"] = value
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)}, {"$set": set_fields}, scope=REPO_GLOBAL_SCOPE
        )

    async def set_first_conversation_id(
        self, user_id: str, conversation_id: str
    ) -> UserDocument | None:
        """Record the seeded "Getting started" conversation on the onboarding subdoc.

        Its own field, not the legacy first_message_conversation_id: a user
        who ran the pre-relocation flow and onboards again carries both, and
        reusing the one field would overwrite the legacy id and orphan the
        conversation it points at.
        """
        return await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {f"onboarding.{GETTING_STARTED_CONVERSATION_ID_FIELD}": conversation_id}},
            scope=REPO_GLOBAL_SCOPE,
        )

    async def reset_onboarding(self, user_id: str) -> None:
        """Wipe the user's onboarding subdocument."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$unset": {"onboarding": _UNSET}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # ---------------------------------------------------- intelligence writes

    async def set_onboarding_phase(self, user_id: str, phase: OnboardingPhase) -> bool:
        """Set onboarding.phase; returns whether the user existed (for a 404)."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"onboarding.phase": phase}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    async def mark_gmail_personalization_done(
        self, user_id: str, *, conversation_id: str | None = None
    ) -> None:
        """Stamp the Gmail personalization pipeline as run for this user.

        The marker is what makes a later Gmail reconnect a no-op. The seeded
        holo-card conversation id rides along so reset_onboarding can tear it
        down with the rest of the personalization state.
        """
        set_fields: dict[str, object] = {
            f"onboarding.{GMAIL_PERSONALIZATION_MARKER}": _now(),
        }
        if conversation_id is not None:
            set_fields[f"onboarding.{HOLO_CONVERSATION_ID_FIELD}"] = conversation_id
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
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
        never_auto_tools: list[str] | None = None,
    ) -> None:
        """$set the provided hil_preferences fields, leaving the rest alone."""
        set_fields: dict[str, object] = {}
        if mode is not None:
            set_fields["hil_preferences.mode"] = mode
        if tool_overrides is not None:
            set_fields["hil_preferences.tool_overrides"] = tool_overrides
        if never_auto_tools is not None:
            set_fields["hil_preferences.never_auto_tools"] = never_auto_tools
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_hil_tool_override(self, user_id: str, tool_name: str, ask: bool | None) -> None:
        """Set (ask = True/False) or clear (ask = None) one HIL tool override.

        Touches only this tool's key so concurrent toggles can't overwrite each
        other. Uses $setField in a pipeline update, not a dotted $set, since MCP
        tool names can contain dots that Mongo would otherwise nest; that update
        shape can't go through _apply_raw_update, so cache eviction is done here.
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

    async def set_chat_channel_priority(self, user_id: str, priority: list[str]) -> None:
        """Store the order a proactive message picks its ONE chat platform from."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"chat_channel_priority": priority}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_quiet_hours(self, user_id: str, quiet_hours: QuietHours) -> None:
        """Store the daily window in which proactive pushes hold."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"quiet_hours": quiet_hours.model_dump()}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_briefing_schedule(self, user_id: str, schedule: BriefingSchedule) -> None:
        """Store how often the user wants briefs and the daily brief's hour."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"briefing_schedule": schedule.model_dump()}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def clear_name_if_unchanged(self, user_id: str, name: str) -> bool:
        """Unset the user's name while it still equals name; False when it changed or the user is gone."""
        before = await self._apply_raw_update(
            {"_id": self._id_value(user_id), "name": name},
            {"$unset": {"name": ""}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return before is not None

    async def set_bio_status(self, user_id: str, bio_status: BioStatus) -> None:
        """Update the onboarding bio-generation status (e.g. back to processing on a Gmail reconnect)."""
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

    async def set_social_profiles(self, user_id: str, profiles: Iterable[SocialProfile]) -> None:
        """Overwrite the stored social profiles (user-confirmed selection)."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {_SOCIAL_PROFILES_FIELD: [p.model_dump() for p in profiles]}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def save_personalization(self, user_id: str, bundle: PersonalizationBundle) -> None:
        """Persist the generated personalization bundle and advance the phase to personalization-complete."""
        set_fields: dict[str, object] = {
            f"onboarding.{field}": value for field, value in bundle.model_dump().items()
        }
        set_fields["onboarding.phase"] = OnboardingPhase.PERSONALIZATION_COMPLETE.value
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # ---------------------------------------------------- lifecycle-job markers

    async def record_inactive_email(self, user_id: str, count: int) -> None:
        """Stamp the inactivity-email send: the send time and the episode counter.

        count is set (not incremented) so the counter restarts at 1 for a new
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

        completed_steps uses $addToSet (a step can never be re-sent), and
        history appends the outcome so the frequency caps can be enforced."""
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

        One conditional update matches only a document whose marker is missing
        or older than stale_before, so exactly one caller wins. Returns the
        BEFORE image, whose last_limit_email_sent is the value to restore if
        the send then fails (see release_limit_email_slot).
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
        """Persist tier as the user's highest badge, returning the document only on a first-time promotion.

        The guard is monotonic, so downgrades are silent and a re-crossed
        boundary can't re-fire; the filtered update also makes a retried job
        idempotent. A non-ObjectId user_id (synthetic/dev identities) is
        skipped with a warning rather than failing the sweep.
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

    async def set_first_steps_collapsed(self, user_id: str, collapsed: bool) -> bool:
        """Persist the checklist's collapse; returns whether the user existed (for a 404)."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    FIRST_STEPS_COLLAPSED_FIELD: collapsed,
                    FIRST_STEPS_COLLAPSED_AT_FIELD: datetime.now(UTC) if collapsed else None,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )
        return updated is not None

    async def stamp_signup_deliveries(
        self, user_id: str, deliveries: Iterable[SignupDelivery]
    ) -> bool:
        """Record signup deliveries as settled; False when no such user exists.

        Written on each delivery's own success, once the ESP has accepted it.
        Unfetched because nothing here needs the document back, and a stamp is
        the job's hot path — two per signup. A False is a delivery that
        landed for a user who has since been deleted.
        """
        now = datetime.now(UTC)
        matched = await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {"$set": {delivery.value: now for delivery in deliveries}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )
        return matched > 0

    async def mark_memory_backfilled(self, user_id: str) -> None:
        """Stamp the memory-backfill marker so the daily cron won't re-select the user."""
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {"memory_backfilled": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    # --------------------------------------------------------- settings writes

    async def set_channel_preferences(self, user_id: str, preferences: Mapping[str, bool]) -> None:
        """Set the given notification channel flags; unlisted channels are left untouched."""
        unknown = sorted(set(preferences) - set(DEFAULT_CHANNEL_PREFERENCES))
        if unknown:
            raise ValueError(f"Unknown notification channels: {unknown}")
        set_fields: dict[str, object] = {
            f"notification_channel_prefs.{channel}": enabled
            for channel, enabled in preferences.items()
        }
        if not set_fields:
            return
        await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": set_fields},
            scope=REPO_GLOBAL_SCOPE,
            return_document=False,
        )

    async def set_feature_flag(self, user_id: str, flag: FeatureFlag, enabled: bool) -> bool:
        """Store the user's choice for one flag, leaving their other choices alone; returns whether the user existed."""
        updated = await self._apply_raw_update(
            {"_id": self._id_value(user_id)},
            {"$set": {f"feature_flags.{flag.value}": enabled}},
            scope=REPO_GLOBAL_SCOPE,
        )
        return updated is not None

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
                    f"platform_links.{platform}": _UNSET,
                    f"platform_links_connected_at.{platform}": _UNSET,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
        )

    # ------------------------------------------------------------ briefing engine

    async def clear_briefing_bootstrap(self, user_id: str) -> None:
        """Clear the pending-bootstrap marker once a real briefing goes out."""
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {"$unset": {"briefing_bootstrap": _UNSET}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def set_briefing_bag(self, user_id: str, bag: BriefingBag, state: ShuffleBag) -> None:
        """Persist one shuffle bag's advanced state (see shuffle_bag.draw)."""
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {"$set": {f"briefing_shuffle_bags.{bag.value}": state.model_dump()}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def set_briefing_bootstrap_pending(self, user_id: str) -> None:
        """Hold briefings for a sparse existing-user rollout.

        Held until a goal arrives or the grace window elapses. Only a user with no
        marker yet is stamped, so a re-run never restarts a running grace window.
        """
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id), "briefing_bootstrap": {"$exists": False}},
            {
                "$set": {
                    "briefing_bootstrap": BriefingBootstrap(
                        pending=True, since=datetime.now(UTC)
                    ).model_dump()
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def set_dormancy_day(self, user_id: str, *, idle_days: int, date_str: str) -> None:
        """Persist today's idle/active outcome on the dormancy ladder."""
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    "briefing_dormancy.idle_days": idle_days,
                    "briefing_dormancy.date": date_str,
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def enter_briefing_dormancy(self, user_id: str) -> None:
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {"$set": {"briefing_dormancy.dormant_since": datetime.now(UTC)}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def clear_briefing_dormancy(self, user_id: str) -> None:
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {"$unset": {"briefing_dormancy": _UNSET}},
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )

    async def mark_day_zero_hello_sent(self, user_id: str, platform: str) -> None:
        await self._apply_raw_update_unfetched(
            {"_id": self._id_value(user_id)},
            {
                "$set": {
                    "day_zero_hello": DayZeroHello(
                        sent_at=datetime.now(UTC), platform=platform
                    ).model_dump()
                }
            },
            scope=REPO_GLOBAL_SCOPE,
            doc_id=user_id,
        )


def _now() -> datetime:
    return datetime.now(UTC)


user_repository = UserRepository()
