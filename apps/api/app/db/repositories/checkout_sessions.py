"""Repository for the ``checkout_sessions`` collection.

Records the Dodo checkout session id at checkout-creation time so the
result page can resolve what a user bought even when the
``subscription.active`` webhook has not landed yet (the webhook-vs-redirect
race): the session id is the stable reference Dodo can answer for before a
subscription row exists.
"""

from app.db.repositories.base import UserScopedRepository
from app.models.payment_models import CheckoutSessionDocument


class CheckoutSessionsRepository(
    UserScopedRepository[CheckoutSessionDocument, CheckoutSessionDocument]
):
    collection_name = "checkout_sessions"
    document_model = CheckoutSessionDocument
    update_model = CheckoutSessionDocument
    uses_object_id = True
    cache_policy = None

    async def list_recent_for_user(
        self, user_id: str, *, limit: int
    ) -> list[CheckoutSessionDocument]:
        """This user's most recently minted sessions, newest first.

        Deliberately not a "latest" read: every paywall block mints a session,
        so the newest row is usually one nobody paid, and the paid one the
        caller is looking for sits below it.
        """
        return await self._find(
            {"user_id": user_id},
            sort=[("created_at", -1)],
            limit=limit,
        )


checkout_session_repository = CheckoutSessionsRepository()
