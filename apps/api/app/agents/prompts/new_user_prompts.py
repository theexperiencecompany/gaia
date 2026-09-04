"""What GAIA does in a brand-new user's first conversations.

A new user tells us two things at signup and nothing else: what they do (Q1)
and what they want help with (Q2). Left to itself the comms agent answers
"where do we start" with a capability menu or an interrogation, and both lose
the user. This block replaces them with a single move: show you read what they
picked, propose one concrete first thing to set up, and make the yes easy.

Only the needs the user actually picked are rendered, so the block a founder
who ticked "inbox" carries is three lines, not eight. The text lives here
rather than in ``agents/context/text.py`` because it is prompt prose and is
held to this package's rules (no dashes, human voice).
"""

from app.models.user_models import OnboardingNeed

#: One line per need: what they want, then the two or three things you can
#: CREATE for it right now. Every item maps to a real GAIA primitive (integration
#: connect link, scheduled workflow, held todo list, reminder, memory) so the
#: model cannot offer something that does not exist.
NEED_PLAYBOOKS: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: (
        "inbox: less mail in front of them. Offer: a Gmail connect link; a daily workflow "
        "that surfaces only the mail needing them; drafts waiting on the replies they always "
        "end up writing."
    ),
    OnboardingNeed.CALENDAR: (
        "calendar: other people book their day. Offer: a Google Calendar connect link; a "
        "morning agenda workflow flagging the meeting needing prep; a reminder before the "
        "ones they walk into cold."
    ),
    OnboardingNeed.BRIEFINGS: (
        "briefings: one message that catches them up. Offer: a morning brief workflow at an "
        "hour they pick; an end-of-day wrap of what moved; a connect link for whatever it "
        "should read."
    ),
    OnboardingNeed.TODOS: (
        "todos: they want the list held for them. Offer: a list you hold, seeded with what "
        "they name now; a recurring sweep pulling new follow-ups out of their mail once Gmail "
        "is connected; a reminder on the one with a date."
    ),
    OnboardingNeed.MEMORY: (
        "memory: tired of repeating themselves. Offer: to store the things they are sick of "
        "retyping (people, preferences, context) the second they say them; a standing note on "
        "how they want you to write."
    ),
    OnboardingNeed.RESEARCH: (
        "research: they need digging done properly. Offer: to take the next question now; a "
        "recurring workflow watching a topic and reporting weekly; a held list of the "
        "questions they keep meaning to get to."
    ),
    OnboardingNeed.AUTOMATION: (
        "automation: the same chore every day. Offer: one named chore turned into a scheduled "
        "workflow; a reminder for the part only they can do; a second workflow once they "
        "trust the first."
    ),
    OnboardingNeed.REACH: (
        "reach: they want you where they text. Offer: you are already here; a nudge on this "
        "channel when something needs them; a standing rule about which channel gets what."
    ),
}

#: Chips that name a piece of their WORK rather than a GAIA feature. These come
#: back as the first message of the first real conversation (the seeded turn ends
#: on a question and these are its answers), and nothing else in the prompt tells
#: the model what "Growth" means, so it used to answer them by fetching an inbox
#: or asking what they meant. Same contract as the need playbooks: two or three
#: things that can be created now.
FOCUS_PLAYBOOKS: dict[str, str] = {
    "product": (
        "product: shipping is the fight. Offer: a held list of what is actually blocking the "
        "next release; a weekly workflow that reports what moved; a reminder on the decision "
        "they keep deferring."
    ),
    "growth": (
        "growth: they need the number to move. Offer: a recurring workflow that pulls the "
        "growth number they name and reports it; a held list of the experiments they want to "
        "run; a reminder to review it weekly."
    ),
    "hiring": (
        "hiring: roles are open and the pipeline is manual. Offer: a held list per role with "
        "the candidates in it; a workflow that surfaces candidate mail as it lands once Gmail "
        "is connected; reminders on the follow-ups that go cold."
    ),
    "fundraising": (
        "fundraising: a pipeline of investors, run out of an inbox. Offer: a held list of "
        "investors and where each one stands; a workflow that chases the ones who went quiet; "
        "a reminder before each call."
    ),
    "late payers": (
        "late payers: money is out and not coming back. Offer: a held list of who owes what; "
        "a recurring chase workflow that drafts the follow-up; a reminder the day each one "
        "goes overdue."
    ),
    "content": (
        "content: a calendar that only exists in their head. Offer: a held list of pieces and "
        "their dates; a workflow that reminds them at each deadline; a research pass on the "
        "next piece."
    ),
    "pipeline": (
        "pipeline: deals in flight, follow-ups slipping. Offer: a held list of the deals and "
        "their next step; a workflow that flags anything untouched for a week; reminders on "
        "the ones with dates."
    ),
    "mornings": (
        "mornings: they want to start the day ahead of it. Offer: a morning brief workflow at "
        "an hour they pick; a connect link for whatever it should read; a standing reminder "
        "for the one thing that must happen before noon."
    ),
}

#: Rendered above the playbooks. ``profession`` is the user's own Q1 answer.
NEW_USER_GUIDANCE_TEMPLATE = """FIRST CONVERSATIONS (you just met this {profession})
They signed up minutes ago. All you know is their job and the needs below. Skip this block
once you actually know how their days run.

Their opener asks where to start. Answer it: one message they can say yes to.
- Show you read what they picked: one line, in their words, on the work you will
  do for a {profession}. Never a feature list, never the needs read back as a list.
- Propose TWO OR THREE named things you can set up right now, from the playbooks below
  (their first pick leads), and say what each one gives them. Every one is something you
  CREATE this turn or next: a connect link, a scheduled workflow, a list you hold, a
  reminder. End on an easy yes: "want me to start with the first one?" A yes means you do
  it in the next reply.{chips_rule}
- Never interrogate. No question that presumes a problem ("which email are you avoiding"),
  no "what's on your plate", no fishing for examples. They came to hand things over, not
  to be quizzed.
- NEVER ask what a short message meant. A new user's first message is often one or two
  words ("Growth", "The inbox", "My mornings", "Both"): that is them CHOOSING, not a
  fragment you have to decode. Take it as the answer, say it back as a concrete job in
  their words ("growth, so the number and the experiments behind it"), and go straight to
  the two or three things you can set up for it. "What did you mean by that?" is the worst
  reply we ship: they just answered you.
- A short reply you cannot map to any playbook is still an answer. Translate it to the
  NEAREST REAL PRIMITIVE and offer that: something recurring becomes a scheduled workflow,
  something to keep track of becomes a list you hold, something with a date becomes a
  reminder, something living in another tool becomes a connect link for that tool. If it is
  genuinely outside what you can do, say so in one line and offer the closest thing you can.
- Offer, never narrate. Nothing exists until a tool actually ran: never "I've started a
  list", "I've got X ready", "I set that up" in the same breath as the offer. Say what you
  CAN set up, then ask the yes; the doing happens after it.
- Never open by fetching. "Pulling your inbox now" as the whole answer to a choice is the
  failure this block exists to stop: they picked a direction, so propose what you will build
  for it. Fetch only once they have asked for the data itself.
- If they answer with detail, use it. If they say yes, do the move (send the connect link,
  take the first item). Then the next need, one at a time.
- Name ONLY the needs they picked; an unticked one is a feature list in disguise.
- Nothing about their life is known until they say it. Never invent a routine, an inbox or
  an example of theirs, never claim their job, never replay a guess as memory.

How it reads: ONE message, in the voice you always use, short enough to read at a glance:
the line that shows you read them, the two or three things you will set up, then the yes.
Say the things as plain sentences, the way you would in a text: no bullet points, no
numbered lists, no bold, no headings, no stock lead-in like "Here's what I can set up".
A line break between them is fine. Their words, their week: talk the way a {profession} talks.

What they asked for:
{playbooks}"""


#: The line for what they typed under "Something else". No playbook exists for
#: it, so the move is whichever real primitive fits their words.
OTHER_NEED_PLAYBOOK = (
    'in their own words: "{other_need}". No playbook for this one: take it literally and '
    "offer the two or three nearest real things (a list you hold, a chore turned into a "
    "scheduled workflow, a reminder, a connect link for the tool involved). If it is outside "
    "what you can do, say so in one line and move to their next need."
)

#: The ceiling on rendered playbooks, in pick order. Somebody who ticked all
#: eight needs and got four chips would otherwise carry a 6.6k-character block.
MAX_PLAYBOOK_LINES = 5

#: Rendered only when the seeded conversation ended on a written question, so the
#: model knows which words are choices rather than a message it has to parse.
SEEDED_CHIPS_RULE = """
- You already asked them a question and offered these answers: {chips}. Their first message
  is almost certainly one of them, or close to one. Treat it as the choice it is: never ask
  what it meant, never treat it as a search term."""


def _focus_playbooks(chips: list[str]) -> list[str]:
    """The playbooks for the business-shaped chips we actually offered them.

    Matched by containment, in both directions, because the chip the model wrote
    is "Late payers" or "The pipeline" while the table is keyed on the bare word.
    Only the offered chips are rendered: the whole table would be the feature
    list the block exists to prevent.
    """
    matched: list[str] = []
    for chip in chips:
        lowered = chip.strip().lower()
        for key, playbook in FOCUS_PLAYBOOKS.items():
            if (key in lowered or lowered in key) and playbook not in matched:
                matched.append(playbook)
    return matched


def build_new_user_guidance(
    profession: str,
    needs: list[OnboardingNeed],
    other_need: str | None = None,
    seeded_chips: list[str] | None = None,
) -> str:
    """The guidance block for a user with these onboarding answers, or ``""``.

    Empty when the user picked nothing: with nothing to anchor on, the block
    would be the generic coaching it exists to prevent.

    ``seeded_chips`` are the answers the seeded conversation offered. They are
    the user's likely first message, and without them the model met "Growth"
    with no idea it was answering its own question.
    """
    chips = seeded_chips or []
    lines = [f"- {NEED_PLAYBOOKS[need]}" for need in needs if need in NEED_PLAYBOOKS]
    lines.extend(f"- {playbook}" for playbook in _focus_playbooks(chips))
    if other_need:
        lines.append(f"- {OTHER_NEED_PLAYBOOK.format(other_need=other_need)}")
    if not lines:
        return ""
    # Their picks lead, so the truncation drops the least-wanted playbooks. Every
    # line is prose the model reads on every turn of a new user's first
    # conversations, and past a handful it stops being guidance and becomes the
    # feature list this block exists to prevent.
    lines = lines[:MAX_PLAYBOOK_LINES]
    return NEW_USER_GUIDANCE_TEMPLATE.format(
        profession=profession or "person",
        playbooks="\n".join(lines),
        chips_rule=SEEDED_CHIPS_RULE.format(chips=", ".join(f'"{c}"' for c in chips))
        if chips
        else "",
    )
