"""Voice the brief, hold its slots to its facts, and build the payload from it.

Code builds every fact; the agent writes only the voice. Prose whose slots break a fact is sent
back once with the problems named; a second failure voices the brief plainly from its facts.
"""

from dataclasses import dataclass, field
import re

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agents.llm.client import StructuredCallOptions, ainvoke_structured, metered_config
from app.agents.llm.exceptions import MalformedStructuredOutputError
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
    hue_for_day,
)
from app.models.briefing_models import (
    BriefingModel,
    BriefingMood,
    BriefingPayload,
    BriefVoice,
)
from app.models.short_link_models import ShortLinkTargetType
from app.models.user_models import UserDocument
from app.services.briefing.claims import claim_problems
from app.services.briefing.context import UserClock
from app.services.briefing.errors import BriefingGenerationError, VoiceUnreadableError
from app.services.briefing.facts import (
    Facts,
)
from app.services.briefing.slots import (
    SlotValues,
    referenced_facts,
    render_slots,
    slot_problems,
)
from app.services.links.service import attach_link, build_url
from app.utils.timezone import Timezone
from app.utils.user_display import display_first_name
from app.utils.user_preferences_utils import build_user_context_parts, onboarding_preferences
from shared.py.wide_events import log


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
        link = await attach_link(user_id, ShortLinkTargetType.TODO_DELIVERABLE, todo_id)
        if link is not None:
            links[fact_id] = build_url(link.slug)
    return links


#: The provider holds the voice to its schema, so every field arrives and each is a string.
_SCHEMA_HELD = StructuredCallOptions(schema_held=True)


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


def _unreadable_problems(exc: MalformedStructuredOutputError) -> list[str]:
    """Name each field the reply got wrong, never its text; a reply with no voice at all, why."""
    cause = exc.__cause__
    if not isinstance(cause, ValidationError):
        return [exc.reason]
    errors: list[ErrorDetails] = cause.errors()
    return [f"{error['loc'][0]}: {error['msg']}" for error in errors]


async def _voice(user_id: str, prompt: str) -> BriefVoice:
    """Voice the brief in one structured call: briefing work, never charged to the user's allowance."""
    try:
        return await ainvoke_structured(
            BriefVoice,
            prompt,
            label=BRIEF_VOICE_LABEL,
            config=metered_config(user_id),
            options=_SCHEMA_HELD,
        )
    except MalformedStructuredOutputError as exc:
        raise VoiceUnreadableError(_unreadable_problems(exc), exc.llm_output) from exc


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


def opening_line(message: str) -> str:
    """Return a message's first non-blank line."""
    return next((line.strip() for line in message.splitlines() if line.strip()), "")


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
            f"[your phrase](fact:{lead})"
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

    An unreadable reply, a bad slot, a missing lead or an overlong field is sent back to
    the model once with the problems named; after a second failure the brief is voiced plainly
    from its facts, and the failure is logged as an error.
    """
    note = ""
    failure: BriefingGenerationError
    rejections: list[str] = []
    for attempt in range(1, MAX_VOICE_ATTEMPTS + 1):
        attempt_prompt = f"{prompt}\n\n{note}" if note else prompt
        try:
            voice = await _voice(user_id, attempt_prompt)
        except VoiceUnreadableError as exc:
            # Logged here, not where the reply failed: that error's text quotes the reply.
            log.warning("briefing.voice_unreadable", problems=exc.problems)
            rejections.append("; ".join(exc.problems))
            failure, note = exc, voice_unreadable_note(exc.problems, exc.reply)
            continue
        checked = _held_to_facts(voice, writing)
        if isinstance(checked, BriefVoice):
            log.set_ns("brief_voice", attempts=attempt, plain=False, rejections=rejections)
            return voice, checked
        log.warning("briefing.voice_rejected", problems=checked)
        rejections.append("; ".join(checked))
        failure = BriefingGenerationError(
            f"The brief's prose does not hold to its facts: {'; '.join(checked)}"
        )
        note = voice_correction_note(checked, voice.model_dump_json(indent=2))
    # Loud, but never the user's loss: the brief goes out in plain words built from its facts.
    log.set_ns("brief_voice", attempts=MAX_VOICE_ATTEMPTS, plain=True, rejections=rejections)
    log.error("briefing.voice_salvaged", problems=str(failure))
    plain = plain_voice(writing)
    return plain, _draft(plain, writing.values)


def plain_voice(writing: Writing) -> BriefVoice:
    """Write the brief from its facts alone, every placed fact by its slot, the lead first."""
    facts = writing.values.facts
    order = [writing.lead] if writing.lead is not None else []
    order += [fact_id for fact_id in facts if fact_id != writing.lead]
    lines = [
        f"- [[fact:{fact_id}]]" + (f" ([[fact:{fact_id}.time]])" if facts[fact_id].time else "")
        for fact_id in order
    ]
    message = "\n".join(lines) or PLAIN_BRIEF_EMPTY
    while len(_draft_message(message, writing)) > MAX_BRIEF_MESSAGE_CHARS and "\n" in message:
        message = message.rsplit("\n", 1)[0]
    return BriefVoice(
        headline=PLAIN_BRIEF_HEADLINE, lede="", caption="", mood="clear", message=message
    )


def _draft_message(message: str, writing: Writing) -> str:
    return render_slots(message, writing.values, {})  # pragma: no mutate — no link slot to look up


@dataclass(frozen=True)
class Prose:
    """The voice as written, its rendered draft, and the address of each fact its message links."""

    written: BriefVoice
    draft: BriefVoice
    links: dict[int, str]


def voiced_payload(
    clock: UserClock,
    prose: Prose,
    facts: Facts,
    *,
    kicker: str,
    mood: BriefingMood,
    family: str,
) -> BriefingPayload:
    """Build the brief from its rendered prose; an item the message links carries its link."""
    linked = {todo: prose.links[i] for i, todo in facts.deliverables.items() if i in prose.links}
    for item in (item for section in facts.sections for item in section.items):
        if item.todo_id in linked:
            item.link = linked[item.todo_id]
    draft = prose.draft
    return BriefingPayload(
        kicker=kicker,
        date=clock.date_str,
        headline=draft.headline,
        lede=draft.lede,
        sections=facts.sections,
        mood=mood,
        caption=draft.caption,
        hue=hue_for_day(clock.day_of_year),
        generated_at=clock.now_local.strftime("%-I:%M %p"),
        message=render_slots(prose.written.message, facts.values, prose.links),
        template_family=family,
    )
