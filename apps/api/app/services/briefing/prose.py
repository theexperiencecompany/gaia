"""Voice the brief, hold its prose to its facts, and build the payload from it.

Code builds every fact; the agent writes only the voice. Prose that breaks a fact is sent
back once with the problems named, and a second failure fails the run before anything is
stored or sent.
"""

from dataclasses import dataclass

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from app.agents.prompts.briefing_prompts import (
    voice_correction_note,
    voice_unreadable_note,
)
from app.constants.briefing import (
    MAX_VOICE_ATTEMPTS,
    hue_for_day,
)
from app.models.briefing_models import (
    BriefingKind,
    BriefingMood,
    BriefingPayload,
    BriefVoice,
)
from app.models.short_link_models import ShortLinkTargetType
from app.models.user_models import AuthenticatedUser
from app.services.briefing.context import UserClock
from app.services.briefing.errors import BriefingGenerationError, VoiceUnreadableError
from app.services.briefing.facts import (
    Facts,
)
from app.services.briefing.faithfulness import CheckedProse, unsupported_claims
from app.services.briefing.silent_turn import run_briefing_turn
from app.services.briefing.slots import (
    SlotValues,
    referenced_facts,
    render_slots,
    slot_problems,
)
from app.services.short_link_service import optional_short_link
from app.utils.markdown_utils import model_from_reply
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
        url = await optional_short_link(user_id, ShortLinkTargetType.TODO_DELIVERABLE, todo_id)
        if url is not None:
            links[fact_id] = url
    return links


def _parse_voice(raw: str) -> BriefVoice:
    """Extract the voice-only JSON (headline/lede/caption/mood/message)."""
    parsed = model_from_reply(raw, BriefVoice)
    if isinstance(parsed, BriefVoice):
        return parsed
    log.warning("briefing.voice_unreadable", raw_length=len(raw), problems=parsed)
    raise VoiceUnreadableError(parsed)


@dataclass(frozen=True)
class Writing:
    """What the written brief is held to: the values its slots render and everything the model was shown."""

    values: SlotValues
    context: str
    #: The facts the message must refer to by a slot; empty for a winback or wind-down note.
    must_mention: frozenset[int]
    kind: BriefingKind


_VOICED_FIELDS = ("headline", "lede", "caption", "message")


def _draft(voice: BriefVoice, values: SlotValues) -> BriefVoice:
    """Fill the voice's slots, each link as its phrase; raises ValidationError past a field's limit."""
    return BriefVoice.model_validate(
        {
            "mood": voice.mood,
            **{name: render_slots(getattr(voice, name), values, {}) for name in _VOICED_FIELDS},
        }
    )


def _length_problems(exc: ValidationError) -> list[str]:
    errors: list[ErrorDetails] = exc.errors(include_url=False, include_input=False)
    return [f"the {error['loc'][0]} once its slots are filled: {error['msg']}" for error in errors]


async def _held_to_facts(
    user_id: str, voice: BriefVoice, writing: Writing
) -> BriefVoice | list[str]:
    """Return the voice rendered from its facts, or every way it breaks them.

    Slots, coverage and lengths are checked in code; the rendered prose's claims by one model call.
    """
    problems = [
        problem
        for name in _VOICED_FIELDS
        for problem in slot_problems(name, getattr(voice, name), writing.values)
    ]
    problems += [
        f"the message never refers to fact {fact_id} ({writing.values.facts[fact_id].title}); "
        f"say it in your own words as [your phrase](fact:{fact_id})"
        for fact_id in sorted(writing.must_mention - referenced_facts(voice.message))
    ]
    if problems:
        return problems
    try:
        draft = _draft(voice, writing.values)
    except ValidationError as exc:
        return _length_problems(exc)

    def marked(text: str) -> str:
        return render_slots(text, writing.values, {}, mark_filled=True)

    prose = CheckedProse(
        headline=marked(voice.headline),
        lede=marked(voice.lede),
        caption=marked(voice.caption),
        message=marked(voice.message),
    )
    claims = await unsupported_claims(user_id, writing.context, prose)
    return [claim.problem() for claim in claims] or draft


async def written_brief(
    user: AuthenticatedUser, clock: UserClock, prompt: str, writing: Writing
) -> tuple[BriefVoice, BriefVoice]:
    """Voice the brief and hold it to its facts; return what the model wrote and its rendered draft.

    An unreadable reply, a bad slot, an overlong field or an unsupported claim is sent back to
    the model once with the problems named; a second failure fails the run before anything is
    stored or sent.
    """
    note = ""
    failure: BriefingGenerationError
    for _ in range(MAX_VOICE_ATTEMPTS):
        attempt_prompt = f"{prompt}\n\n{note}" if note else prompt
        raw = await run_briefing_turn(user, clock, attempt_prompt, conversation_key=writing.kind)
        try:
            voice = _parse_voice(raw)
        except VoiceUnreadableError as exc:
            failure, note = exc, voice_unreadable_note(exc.problems)
            continue
        checked = await _held_to_facts(user.user_id, voice, writing)
        if isinstance(checked, BriefVoice):
            return voice, checked
        log.warning("briefing.voice_rejected", problems=checked)
        failure = BriefingGenerationError(
            f"The brief's prose does not hold to its facts: {'; '.join(checked)}"
        )
        note = voice_correction_note(checked)
    raise failure


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
