"""Who to invite: people the user met or emailed in the last 90 days, ranked by how often.

Computed on demand from the connected Google Calendar and Gmail, and nothing
about these contacts is stored. Automated senders, mailing lists and big
meetings are skipped; so are people already invited, people who opted out
of invites, and anyone who already has an account (silently, so suggestions
never reveal who uses GAIA).
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import getaddresses
import re

from app.constants.integrations import GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID
from app.constants.referrals import (
    AUTOMATED_DOMAIN_MARKERS,
    AUTOMATED_LOCAL_PART_MARKERS,
    GMAIL_LIST_SEND_AS_TOOL,
    LOCAL_PART_WORD_SEPARATORS,
    ROLE_LOCAL_PART_WORDS,
    SELF_NAME_MIN_WORD_LENGTH,
    SELF_NAME_MIN_WORDS,
    SEND_AS_READ_FAILED_MESSAGE,
    SEND_AS_READ_FAILED_WHY,
    SUGGESTION_GMAIL_MAX_PAGES,
    SUGGESTION_GMAIL_PAGE_SIZE,
    SUGGESTION_GMAIL_QUERY,
    SUGGESTION_LIMIT,
    SUGGESTION_LOOKBACK,
    SUGGESTION_MAX_MEETING_SIZE,
)
from app.db.repositories.email_suppressions import email_suppression_repository
from app.db.repositories.referral_invites import referral_invite_repository
from app.db.repositories.users import user_repository
from app.models.composio_schemas.gmail import GmailSendAsList
from app.models.referral_models import ReferralSuggestionReason
from app.models.user_models import UserDocument
from app.schemas.referrals import ReferralSuggestion, ReferralSuggestionsResponse
from app.services.calendar_service import get_calendar_events
from app.services.integrations.integration_accounts import get_account_record
from app.services.mail.mail_service import (
    MessageFetchOptions,
    invoke_gmail_tool,
    search_messages,
)
from app.services.oauth.oauth_service import check_multiple_integrations_status
from app.services.referrals.codes import load_user
from app.utils.email_utils import email_identity, normalize_email
from app.utils.errors import AppError
from shared.py.wide_events import log

_METADATA_ONLY = MessageFetchOptions(output_format="metadata", include_payload=False, verbose=False)
_LOCAL_PART_WORDS = re.compile(LOCAL_PART_WORD_SEPARATORS)
_NAME_WORDS = re.compile(r"[\W_]+")


@dataclass
class _Tally:
    """Per-person interaction counts, keyed by mailbox identity, with the best address and name seen."""

    met: Counter[str] = field(default_factory=Counter)
    emailed: Counter[str] = field(default_factory=Counter)
    addresses: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    def add(self, counter: Counter[str], address: str, name: str | None) -> None:
        identity = email_identity(address)
        counter[identity] += 1
        self.addresses.setdefault(identity, address.lower())
        if name and identity not in self.names:
            self.names[identity] = name


def _local_and_domain(address: str) -> tuple[str, str]:
    """Split at the last @: a quoted local part may hold one, the domain never does."""
    local, _, domain = address.lower().rpartition("@")
    return local, domain


def is_automated(address: str) -> bool:
    """Whether an address is a robot or a list rather than a person someone would invite."""
    local, domain = _local_and_domain(address)
    return (
        any(marker in local for marker in AUTOMATED_LOCAL_PART_MARKERS)
        or not ROLE_LOCAL_PART_WORDS.isdisjoint(_LOCAL_PART_WORDS.split(local))
        or any(marker in domain for marker in AUTOMATED_DOMAIN_MARKERS)
    )


async def _tally_meetings(user_id: str, since: datetime, now: datetime, tally: _Tally) -> None:
    events = await get_calendar_events(
        user_id, time_min=since.isoformat(), time_max=now.isoformat(), fetch_all=True
    )
    for event in events.events:
        attendees = event.attendees or []
        if len(attendees) > SUGGESTION_MAX_MEETING_SIZE:
            continue
        for attendee in attendees:
            if attendee.email:
                tally.add(tally.met, attendee.email, attendee.displayName)


async def _tally_sent_mail(user_id: str, tally: _Tally) -> None:
    query = SUGGESTION_GMAIL_QUERY.format(days=SUGGESTION_LOOKBACK.days)
    page_token: str | None = None
    for _ in range(SUGGESTION_GMAIL_MAX_PAGES):
        page = await search_messages(
            user_id,
            query=query,
            max_results=SUGGESTION_GMAIL_PAGE_SIZE,
            page_token=page_token,
            options=_METADATA_ONLY,
        )
        for message in page.messages:
            for name, address in getaddresses([message.to, message.cc]):
                if "@" in address:
                    tally.add(tally.emailed, address, name)
        page_token = page.next_page_token
        if not page_token:
            return


async def _send_as_addresses(user_id: str) -> list[str]:
    """Return every address the user's primary Gmail sends as: its own and each alias."""
    result = await invoke_gmail_tool(user_id, GMAIL_LIST_SEND_AS_TOOL, {"user_id": "me"})
    if not result.successful:
        raise AppError(
            message=SEND_AS_READ_FAILED_MESSAGE,
            why=SEND_AS_READ_FAILED_WHY,
            status_code=502,
            meta={"provider_error": result.error},
        )
    return [alias.send_as_email for alias in GmailSendAsList.model_validate(result.data).send_as]


def _named_after(address: str, name: str | None) -> bool:
    """Whether an address's local part holds every word of the user's full name."""
    if name is None:
        return False
    words = [w for w in _NAME_WORDS.split(name.lower()) if len(w) >= SELF_NAME_MIN_WORD_LENGTH]
    if len(words) < SELF_NAME_MIN_WORDS:
        return False
    local, _ = _local_and_domain(address)
    return all(word in local for word in words)


async def _own_identities(user: UserDocument, gmail_connected: bool) -> set[str]:
    """Return the user's own mailboxes: their login, every connected Gmail and its send-as aliases."""
    addresses = [user.email] if user.email else []
    record = await get_account_record(user.id, GMAIL_INTEGRATION_ID)
    if record is not None:
        addresses += [
            email
            for account in record.accounts
            for value in account.identity.values()
            if (email := normalize_email(value))
        ]
    if gmail_connected:
        addresses += await _send_as_addresses(user.id)
    return {email_identity(address) for address in addresses}


async def _excluded(user: UserDocument, tally: _Tally, *, gmail_connected: bool) -> set[str]:
    """Return the identities never to suggest: the user's own, the invited, the opted out, existing accounts."""
    identities = list(tally.addresses)
    invited = await referral_invite_repository.invited_by(user.id)
    suppressed = await email_suppression_repository.suppressed_among(identities)
    registered = await user_repository.registered_emails(list(tally.addresses.values()))
    own = await _own_identities(user, gmail_connected)
    return (
        own
        | invited
        | suppressed
        | {identity for identity, address in tally.addresses.items() if address in registered}
        | {identity for identity, address in tally.addresses.items() if is_automated(address)}
        | {
            identity
            for identity, address in tally.addresses.items()
            if _named_after(address, user.name)
        }
    )


def _rank(tally: _Tally, excluded: set[str]) -> list[ReferralSuggestion]:
    totals = tally.met + tally.emailed
    ranked = [identity for identity, _ in totals.most_common() if identity not in excluded]
    suggestions = []
    for identity in ranked[:SUGGESTION_LIMIT]:
        met, emailed = tally.met[identity], tally.emailed[identity]
        reason = (
            ReferralSuggestionReason.MET if met >= emailed else ReferralSuggestionReason.EMAILED
        )
        suggestions.append(
            ReferralSuggestion(
                name=tally.names.get(identity),
                email=tally.addresses[identity],
                reason=reason,
                count=met if reason is ReferralSuggestionReason.MET else emailed,
            )
        )
    return suggestions


async def suggest_invitees(user_id: str) -> ReferralSuggestionsResponse:
    """Rank the people this user meets and emails most; empty when neither Google source is connected."""
    user = await load_user(user_id)
    connected = await check_multiple_integrations_status(
        [GMAIL_INTEGRATION_ID, GOOGLE_CALENDAR_INTEGRATION_ID], user.id
    )
    now = datetime.now(UTC)
    tally = _Tally()
    if connected.get(GOOGLE_CALENDAR_INTEGRATION_ID):
        await _tally_meetings(user.id, now - SUGGESTION_LOOKBACK, now, tally)
    gmail_connected = bool(connected.get(GMAIL_INTEGRATION_ID))
    if gmail_connected:
        await _tally_sent_mail(user.id, tally)
    suggestions = _rank(tally, await _excluded(user, tally, gmail_connected=gmail_connected))
    log.set_ns(
        "referral",
        suggestion_sources=sorted(source for source, on in connected.items() if on),
        suggestion_candidates=len(tally.addresses),
        suggestions=len(suggestions),
    )
    return ReferralSuggestionsResponse(suggestions=suggestions)
