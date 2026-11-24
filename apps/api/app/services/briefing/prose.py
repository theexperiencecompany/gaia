"""Voice the brief, hold its slots to its facts, and build the payload from it.

Code builds every fact; the agent writes only the voice. Prose whose slots break a fact is sent
back once with the problems named; a second failure keeps every sentence that holds and drops
the rest, and voices the brief plainly from its facts only when no headline or lede is left
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
from app.services.briefing.claims import claim_problems, points_back
from app.services.briefing.facts import Facts
from app.services.briefing.formats import opening_line
from app.services.briefing.slots import (
    SlotValues,
    referenced_facts,
    render_slots,
    sentence_breaks,
    slot_problems,
)
from app.services.links.service import attach_link
from app.services.links.urls import build_url
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
#: The voice's checked call, which names its log events and its wide-event fields.
_VOICE_CALL = "voice"


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


def _unfounded_frequencies(line: str, grounds: str) -> list[str]:
    """Return each how-often claim in line that no fact makes, casefolded."""
    grounded = {claim.casefold() for claim in _FREQUENCY_RE.findall(grounds)}
    return [
        claim.casefold()
        for claim in _FREQUENCY_RE.findall(line)
        if claim.casefold() not in grounded
    ]


def _frequency_problems(name: str, line: str, grounds: str) -> list[str]:
    return [
        f"the {name} says how often something happens ({claim!r}) and no fact says "
        "so; say only what today's facts show"
        for claim in _unfounded_frequencies(line, grounds)
    ]


def _length_problems(exc: ValidationError) -> list[str]:
    errors: list[ErrorDetails] = exc.errors()
    return [f"the {error['loc'][0]} once its slots are filled: {error['msg']}" for error in errors]


def _field_problems(name: str, text: str, values: SlotValues) -> list[str]:
    """Name every way one voiced field's slots and claims break the facts they name."""
    problems = slot_problems(name, text, values)
    if name == "message":
        problems += claim_problems(name, text, values)
    return problems


def _held_to_facts(voice: BriefVoice, writing: Writing) -> BriefVoice | list[str]:
    """Return the voice rendered from its facts, or every way its slots, lead or lengths break them."""
    problems = [
        problem
        for name in _VOICED_FIELDS
        for problem in _field_problems(name, getattr(voice, name), writing.values)
    ]
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
    said = _repeat_problems(draft, writing.recent) + [
        problem
        for name, line in _printed_lines(draft).items()
        for problem in _frequency_problems(name, line, writing.grounds)
    ]
    return said or draft


def _holds(name: str, text: str, writing: Writing) -> bool:
    """Whether a field's text passes every check its sentences answer to, frequency included."""
    if _field_problems(name, text, writing.values):
        return False
    return not _unfounded_frequencies(render_slots(text, writing.values, {}), writing.grounds)


def _gap(kept: str, dropped: str) -> str:
    """Return the break that stands for a dropped sentence: the wider of the two around it."""
    return max(kept, dropped, key=lambda gap: gap.count("\n"))


def _sound_sentences(name: str, text: str, writing: Writing) -> tuple[str, int]:
    """Drop each sentence the checks reject, and any left pointing back at one; count the drops.

    Each sentence is checked after the ones kept before it, so a claim is read in the context
    the salvaged brief prints it in.
    """
    kept: list[tuple[str, str]] = []
    dropped_at: set[int] = set()
    for index, (sentence, gap) in enumerate(sentence_breaks(text)):
        dangling = index - 1 in dropped_at and points_back(sentence, writing.values)
        if dangling or not _holds(name, _joined(kept) + sentence, writing):
            dropped_at.add(index)
            if kept:
                kept[-1] = (kept[-1][0], _gap(kept[-1][1], gap))
            continue
        kept.append((sentence, gap))
    return _joined(kept).strip(), len(dropped_at)


def _joined(kept: list[tuple[str, str]]) -> str:
    return "".join(sentence + gap for sentence, gap in kept)


@dataclass(frozen=True)
class Voiced:
    """The checked voice as written, its rendered draft, and whether code salvaged it."""

    written: BriefVoice
    draft: BriefVoice
    #: Code kept what held, or voiced it plainly, because the model's last answer failed its check.
    salvaged: bool


def _salvaged(voice: BriefVoice | None, writing: Writing) -> Voiced:
    """Keep what holds of the last voice; plainly only when no headline or lede is left.

    A dropped headline gets the plain one, a message missing the lead gets its plain line first,
    and a message left empty gets the plain list.
    """
    plain = plain_voice(writing)
    salvage = None if voice is None else _held_salvage(voice, writing, plain)
    log.set_ns(f"brief_{_VOICE_CALL}", plain=salvage is None)
    written, draft = salvage or (plain, _draft(plain, writing.values))
    return Voiced(written, draft, salvaged=True)


def _held_salvage(
    voice: BriefVoice, writing: Writing, plain: BriefVoice
) -> tuple[BriefVoice, BriefVoice] | None:
    """Return what holds of voice and its rendered draft; None when nothing that holds is left."""
    kept = _kept_voice(voice, writing, plain)
    if kept is None:
        return None
    held = _held_to_facts(kept, writing)
    return (kept, held) if isinstance(held, BriefVoice) else None


def _kept_text(
    name: str, text: str, writing: Writing, said: set[tuple[str, ...]]
) -> tuple[str, int]:
    """Return a field's sound sentences and how many it dropped.

    A field that repeats recent prose drops whole; the message drops only the opening
    sentences that keep its first line on a recent brief's.
    """
    kept, drops = _sound_sentences(name, text, writing)
    if name == "message":
        return _fresh_opening(kept, drops, writing, said)
    if kept and _plain(render_slots(kept, writing.values, {})) in said:
        return "", drops + 1
    return kept, drops


def _fresh_opening(
    message: str, drops: int, writing: Writing, said: set[tuple[str, ...]]
) -> tuple[str, int]:
    """Drop the message's leading sentences while its opening line repeats a recent brief's."""
    pieces = sentence_breaks(message)
    while (
        pieces and _plain(opening_line(render_slots(_joined(pieces), writing.values, {}))) in said
    ):
        pieces, drops = pieces[1:], drops + 1
    return _joined(pieces).strip(), drops


def _kept_voice(voice: BriefVoice, writing: Writing, plain: BriefVoice) -> BriefVoice | None:
    """Return the voice with its rejected sentences dropped; None when no headline or lede is left."""
    said = {_plain(line) for line in writing.recent.every()}
    (headline, by_headline), (lede, by_lede), (caption, by_caption), (written, by_message) = (
        _kept_text(name, getattr(voice, name), writing, said) for name in _VOICED_FIELDS
    )
    log.set_ns(
        f"brief_{_VOICE_CALL}", dropped_sentences=by_headline + by_lede + by_caption + by_message
    )
    if not headline and not lede:
        return None
    message = written or plain.message
    lead = writing.lead
    if lead is not None and lead not in referenced_facts(message):
        message = f"{_plain_line(lead, writing.values)}\n\n{message}"
    return BriefVoice(
        headline=headline or plain.headline,
        lede=lede,
        caption=caption,
        mood=voice.mood,
        message=message,
    )


async def written_brief(user_id: str, prompt: str, writing: Writing) -> Voiced:
    """Voice the brief and hold it to its facts; return what the model wrote and its rendered draft.

    An unreadable reply, a bad slot, a missing lead or an overlong field is sent back to the
    model with the problems named; past the last attempt what holds of it is kept.
    """

    async def held(voice: BriefVoice) -> Voiced | Rejected[BriefVoice]:
        checked = _held_to_facts(voice, writing)
        if isinstance(checked, BriefVoice):
            return Voiced(voice, checked, salvaged=False)
        note = voice_correction_note(checked, voice.model_dump_json(indent=2))
        return Rejected(checked, note, voice)

    return await checked_structured_call(
        user_id,
        prompt,
        CheckedCall(
            name=_VOICE_CALL,
            schema=BriefVoice,
            label=BRIEF_VOICE_LABEL,
            attempts=MAX_VOICE_ATTEMPTS,
            check=held,
            unreadable=voice_unreadable_note,
            salvage=lambda last: _salvaged(last, writing),
        ),
    )


def plain_voice(writing: Writing) -> BriefVoice:
    """Write the brief from its facts alone, every placed fact by its slot, the lead first."""
    facts = writing.values.facts
    order = [writing.lead] if writing.lead is not None else []
    order += [fact_id for fact_id in facts if fact_id != writing.lead]
    lines = [_plain_line(fact_id, writing.values) for fact_id in order]
    message = "\n".join(lines) or PLAIN_BRIEF_EMPTY
    while len(_draft_message(message, writing)) > MAX_BRIEF_MESSAGE_CHARS and "\n" in message:
        message = message.rsplit("\n", 1)[0]
    return BriefVoice(
        headline=PLAIN_BRIEF_HEADLINE, lede="", caption="", mood=BriefingMood.CLEAR, message=message
    )


def _plain_line(fact_id: int, values: SlotValues) -> str:
    """One fact as the plain list prints it: its slot, and its time where it has one."""
    timed = values.facts[fact_id].time
    return f"- {FactSlot(fact_id)}" + (f" ({FactSlot(fact_id, FactField.TIME)})" if timed else "")


def _draft_message(message: str, writing: Writing) -> str:
    return render_slots(message, writing.values, {})  # pragma: no mutate — no link slot to look up


@dataclass(frozen=True)
class Prose:
    """The voice as written, its rendered draft, and the address of each fact its message links."""

    written: BriefVoice
    draft: BriefVoice
    links: dict[int, str]
