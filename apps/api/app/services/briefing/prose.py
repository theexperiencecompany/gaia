"""Voice the brief, hold its slots to its facts, and build the payload from it.

Code builds every fact; the agent writes only the voice. Prose whose slots break a fact is sent
back once with the problems named; a second failure voices the brief plainly from its facts
(the checked-call policy, briefing.checked_call).
"""

from dataclasses import dataclass, field
import re

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agents.prompts.briefing_prompts import (
    RecentLines,
    reader_line,
    voice_correction_note,
    voice_unreadable_note,
)
from app.constants.briefing import (
    BRIEF_VOICE_LABEL,
    FREQUENCY_CLAIMS,
    MAX_BRIEF_MESSAGE_CHARS,
    MAX_VOICE_ATTEMPTS,
    PLAIN_BRIEF_EMPTY,
    PLAIN_BRIEF_HEADLINE,
)
from app.models.brief_document_models import BriefingModel
from app.models.brief_payload_models import BriefingMood, BriefVoice
from app.models.brief_slot_models import FactField, FactSlot, LinkSlot
from app.models.short_link_models import RecordTarget, ShortLinkTargetType
from app.models.user_models import UserDocument
from app.services.briefing.checked_call import CheckedCall, Rejected, checked_structured_call
from app.services.briefing.claims import claim_problems
from app.services.briefing.facts import Facts
from app.services.briefing.formats import opening_line
from app.services.briefing.slots import (
    SlotValues,
    referenced_facts,
    render_slots,
    slot_problems,
)
from app.services.links.service import attach_link
from app.services.links.urls import build_url
from app.utils.timezone import Timezone
from app.utils.user_display import display_first_name
from app.utils.user_preferences_utils import build_user_context_parts, onboarding_preferences


async def links_in(user_id: str, message: str, facts: Facts) -> dict[int, str]:
    """Return the address of each fact the message links, minting a deliverable's heygaia.link.

    Only a linked deliverable is minted, so a forwarded brief exposes exactly what it links;
    one whose sharing is off has no address, and its phrase stays text.
    """
    linked = referenced_facts(message)
    links = {i: url for i, url in facts.addresses.items() if i in linked}
    for fact_id, todo_id in facts.deliverables.items():
        if fact_id not in linked:
            continue
        link = await attach_link(
            user_id, RecordTarget(type=ShortLinkTargetType.TODO_DELIVERABLE, id=todo_id)
        )
        if link is not None:
            links[fact_id] = build_url(link.slug)
    return links


def reader_block(user: UserDocument) -> str:
    """Who the voice writes to: their name, their timezone and the profile onboarding gave them."""
    preferences, _ = onboarding_preferences(user.onboarding)
    return "\n".join(
        [
            reader_line(display_first_name(user)),
            f"Their timezone: {user.timezone or Timezone.utc().value}.",
            *build_user_context_parts(preferences or {}),
        ]
    )


@dataclass(frozen=True)
class Writing:
    """What the written brief is held to: the values its slots render and the fact it must lead with."""

    values: SlotValues
    #: The lead's fact, which the message refers to by a slot; None without a lead, or for a
    #: winback or wind-down note.
    lead: int | None
    #: What recent briefs printed; a line of it said again is sent back.
    recent: RecentLines = field(default_factory=RecentLines)
    #: The facts the voice was shown; a claim of how often something happens must be among them.
    grounds: str = ""


_VOICED_FIELDS = ("headline", "lede", "caption", "message")


def _draft(voice: BriefVoice, values: SlotValues) -> BriefVoice:
    """Fill the voice's slots, each link as its phrase; raises ValidationError past a field's limit."""
    return BriefVoice.model_validate(
        {
            "mood": voice.mood,
            **{name: render_slots(getattr(voice, name), values, {}) for name in _VOICED_FIELDS},
        }
    )


_FREQUENCY_RE = re.compile(rf"\b({'|'.join(FREQUENCY_CLAIMS)})\b", re.IGNORECASE)
_NOT_A_WORD_RE = re.compile(r"[^\w\s]")


def recent_lines(briefs: list[BriefingModel]) -> RecentLines:
    """Return what the recent briefs printed, newest first, daily and weekly alike."""
    payloads = [brief.payload for brief in briefs]
    return RecentLines(
        headlines=[p.headline for p in payloads if p.headline],
        ledes=[p.lede for p in payloads if p.lede],
        captions=[p.caption for p in payloads if p.caption],
        openings=[opening_line(p.message) for p in payloads if p.message],
    )


def _plain(line: str) -> tuple[str, ...]:
    """Return a line as its words alone, so punctuation and case never hide a repeat."""
    return tuple(_NOT_A_WORD_RE.sub(" ", line).casefold().split())


def _printed_lines(draft: BriefVoice) -> dict[str, str]:
    return {
        "headline": draft.headline,
        "lede": draft.lede,
        "caption": draft.caption,
        "message's opening": opening_line(draft.message),
    }


def _repeat_problems(draft: BriefVoice, recent: RecentLines) -> list[str]:
    said = {_plain(line) for line in recent.every()}
    return [
        f"the {name} repeats a recent brief's line ({line!r}); write today's in fresh words"
        for name, line in _printed_lines(draft).items()
        if _plain(line) in said
    ]


def _frequency_problems(draft: BriefVoice, grounds: str) -> list[str]:
    grounded = {claim.casefold() for claim in _FREQUENCY_RE.findall(grounds)}
    return [
        f"the {name} says how often something happens ({claim.casefold()!r}) and no fact says "
        "so; say only what today's facts show"
        for name, line in _printed_lines(draft).items()
        for claim in _FREQUENCY_RE.findall(line)
        if claim.casefold() not in grounded
    ]


def _length_problems(exc: ValidationError) -> list[str]:
    errors: list[ErrorDetails] = exc.errors()
    return [f"the {error['loc'][0]} once its slots are filled: {error['msg']}" for error in errors]


def _held_to_facts(voice: BriefVoice, writing: Writing) -> BriefVoice | list[str]:
    """Return the voice rendered from its facts, or every way its slots, lead or lengths break them."""
    problems = [
        problem
        for name in _VOICED_FIELDS
        for problem in slot_problems(name, getattr(voice, name), writing.values)
    ]
    problems += claim_problems("message", voice.message, writing.values)
    lead = writing.lead
    if lead is not None and lead not in referenced_facts(voice.message):
        problems.append(
            f"the message never refers to the lead, fact {lead} "
            f"({writing.values.facts[lead].title}); say it in your own words as "
            f"{LinkSlot('your phrase', lead)}"
        )
    if problems:
        return problems
    try:
        draft = _draft(voice, writing.values)
    except ValidationError as exc:
        return _length_problems(exc)
    said = _repeat_problems(draft, writing.recent) + _frequency_problems(draft, writing.grounds)
    return said or draft


async def written_brief(
    user_id: str, prompt: str, writing: Writing
) -> tuple[BriefVoice, BriefVoice]:
    """Voice the brief and hold it to its facts; return what the model wrote and its rendered draft.

    An unreadable reply, a bad slot, a missing lead or an overlong field is sent back to the
    model with the problems named; past the last attempt the brief is voiced plainly from its
    facts.
    """

    async def held(voice: BriefVoice) -> tuple[BriefVoice, BriefVoice] | Rejected[BriefVoice]:
        checked = _held_to_facts(voice, writing)
        if isinstance(checked, BriefVoice):
            return voice, checked
        return Rejected(checked, voice_correction_note(checked, voice.model_dump_json(indent=2)))

    def plainly(_last: BriefVoice | None) -> tuple[BriefVoice, BriefVoice]:
        plain = plain_voice(writing)
        return plain, _draft(plain, writing.values)

    return await checked_structured_call(
        user_id,
        prompt,
        CheckedCall(
            name="voice",
            schema=BriefVoice,
            label=BRIEF_VOICE_LABEL,
            attempts=MAX_VOICE_ATTEMPTS,
            check=held,
            unreadable=voice_unreadable_note,
            salvage=plainly,
        ),
    )


def plain_voice(writing: Writing) -> BriefVoice:
    """Write the brief from its facts alone, every placed fact by its slot, the lead first."""
    facts = writing.values.facts
    order = [writing.lead] if writing.lead is not None else []
    order += [fact_id for fact_id in facts if fact_id != writing.lead]
    lines = [
        f"- {FactSlot(fact_id)}"
        + (f" ({FactSlot(fact_id, FactField.TIME)})" if facts[fact_id].time else "")
        for fact_id in order
    ]
    message = "\n".join(lines) or PLAIN_BRIEF_EMPTY
    while len(_draft_message(message, writing)) > MAX_BRIEF_MESSAGE_CHARS and "\n" in message:
        message = message.rsplit("\n", 1)[0]
    return BriefVoice(
        headline=PLAIN_BRIEF_HEADLINE, lede="", caption="", mood=BriefingMood.CLEAR, message=message
    )


def _draft_message(message: str, writing: Writing) -> str:
    return render_slots(message, writing.values, {})  # pragma: no mutate — no link slot to look up


@dataclass(frozen=True)
class Prose:
    """The voice as written, its rendered draft, and the address of each fact its message links."""

    written: BriefVoice
    draft: BriefVoice
    links: dict[int, str]
