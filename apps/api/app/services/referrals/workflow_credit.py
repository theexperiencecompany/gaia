"""Remix credit: a visitor who signs up to use a community workflow is attributed to its creator."""

from app.db.repositories.subscriptions import subscription_repository
from app.db.repositories.users import user_repository
from app.db.repositories.workflows import workflow_repository
from app.services.referrals.codes import ensure_code
from shared.py.wide_events import log


async def workflow_creator_code(workflow_id: str) -> str | None:
    """Return the referral code of a community workflow's creator; None when they can't refer anyone.

    Only a creator with an active subscription has a referral link, the same rule
    the referral page applies. Curated explore cards belong to GAIA, not a creator.
    """
    workflow = await workflow_repository.get_public_with_creator(workflow_id, by_slug=False)
    if workflow is None or workflow.is_explore or not workflow.created_by:
        log.set_ns("referral", workflow_credit="not_community")
        return None
    creator = await user_repository.get(workflow.created_by)
    if creator is None:
        log.set_ns("referral", workflow_credit="creator_missing")
        return None
    if await subscription_repository.get_active_for_user(creator.id) is None:
        log.set_ns("referral", workflow_credit="creator_not_subscribed")
        return None
    log.set_ns("referral", workflow_credit="eligible", referrer_id=creator.id)
    return await ensure_code(creator)
