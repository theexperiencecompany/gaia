"""Repository for the ``calendar`` collection — per-user calendar preferences.

Global, keyed by ``user_id`` (one preferences doc per user). Stores the ids of
the calendars a user has selected to surface in the app.
"""

from app.constants.cache import REPO_GLOBAL_SCOPE
from app.db.repositories.base import MongoRepository
from app.models.calendar_models import (
    CalendarPreferencesDocument,
    CalendarPreferencesUpdate,
)


class CalendarRepository(MongoRepository[CalendarPreferencesDocument, CalendarPreferencesUpdate]):
    collection_name = "calendar"
    document_model = CalendarPreferencesDocument
    update_model = CalendarPreferencesUpdate
    uses_object_id = True
    cache_policy = None

    async def get_for_user(self, user_id: str) -> CalendarPreferencesDocument | None:
        return await self._find_one({"user_id": user_id})

    async def set_selected_calendars(self, user_id: str, selected_calendars: list[str]) -> bool:
        """Upsert the user's selected-calendar ids. Returns whether anything
        changed — ``False`` when the stored selection already equals the given
        one (mirrors the pre-repository ``modified_count``/``upserted_id`` check)."""
        existing = await self._find_one({"user_id": user_id})
        if existing is not None and existing.selected_calendars == selected_calendars:
            return False
        await self._apply_raw_update(
            {"user_id": user_id},
            {"$set": {"selected_calendars": selected_calendars}},
            scope=REPO_GLOBAL_SCOPE,
            upsert=True,
        )
        return True


calendar_repository = CalendarRepository()
