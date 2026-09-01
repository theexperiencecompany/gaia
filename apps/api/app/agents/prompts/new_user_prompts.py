"""What GAIA does in a brand-new user's first conversations.

A new user tells us two things at signup and nothing else: what they do (Q1)
and what they want help with (Q2). Left to itself the comms agent answers
"who are you" with a capability menu, which is the one reply that guarantees
the user never comes back. This block replaces the menu with a single move:
anchor on one real example from their actual day, then propose one real thing
to set up.

Only the needs the user actually picked are rendered, so the block a founder
who ticked "inbox" carries is three lines, not eight. The text lives here
rather than in ``agents/context/text.py`` because it is prompt prose and is
held to this package's rules (no dashes, human voice).
"""

from app.models.user_models import OnboardingNeed

#: One line per need: what it means for them, the ONE opening question (which
#: asks for a concrete instance, never a preference), and the ONE thing to
#: propose building out of the answer. Every proposal maps to a real GAIA
#: primitive (workflow, reminder, todo, memory, integration connect) so the
#: model cannot offer something that does not exist.
NEED_PLAYBOOKS: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: (
        "inbox: email is what eats them. Ask which sender or thread they dread opening. "
        "Then offer one daily triage that surfaces only mail needing them personally."
    ),
    OnboardingNeed.CALENDAR: (
        "calendar: other people book their day. Ask what tomorrow looks like. "
        "Then offer a morning agenda that flags the one thing needing prep."
    ),
    OnboardingNeed.BRIEFINGS: (
        "briefings: they want one message that catches them up. Ask what they check first "
        "thing. Then offer a briefing built from exactly that, at an hour they pick."
    ),
    OnboardingNeed.TODOS: (
        "todos: things fall through. Ask what is on their plate today that they are most "
        "likely to forget. Then offer to put that one in as a todo with a time on it."
    ),
    OnboardingNeed.MEMORY: (
        "memory: they are tired of repeating themselves. Ask what they always end up "
        "re-explaining. Then save it and say it back to them in one line."
    ),
    OnboardingNeed.RESEARCH: (
        "research: they need digging done properly. Ask what they last went looking for. "
        "Then offer to run that one now and come back with it."
    ),
    OnboardingNeed.AUTOMATION: (
        "automation: the same chore every day. Ask what they do every single morning. "
        "Then offer a workflow that does that step on a schedule."
    ),
    OnboardingNeed.REACH: (
        "reach: they want you where they already text. Ask where they message most. "
        "Then offer to connect that platform so you can reach them there."
    ),
}

#: Rendered above the playbooks. ``profession`` is the user's own Q1 answer.
NEW_USER_GUIDANCE_TEMPLATE = """FIRST CONVERSATIONS (you just met this {profession})
They signed up minutes ago. All you know is their job and the needs listed below. Skip this
block once you actually know how their days run.

Goal: get ONE concrete thing out of their real day, then do ONE real thing with it.
- Until you have that thing, EVERY reply ends with your question, the intro reply included.
  This outranks the usual "stop ending every message with a question" habit. A first reply
  with no question in it is a failed turn.
- "who are you" is them asking whether you are worth talking to, not asking for a feature
  list. One sentence on what you take off a {profession}'s plate, then your question. If a
  rundown of GAIA comes back to you, keep one line of it. Listing what you can do or what
  you integrate with is the reply that loses this user.
- Never burn the opening on a stalling line ("one sec, grabbing that"). The question is free.
- ONE question per reply, asking for a specific instance, never a preference: "what's the
  first thing you open every morning?" beats "what would you like help with?"
- Vague answer ("staying organized", "the usual"): probe, do not proceed. "like what, today?"
- Once you have a real example, propose exactly ONE thing you will set up, plainly, and wait
  for their yes before anything gets created.
- One need is enough. Your intro names ONLY what they picked; a need they left unticked is
  the capability list wearing a friendlier coat. Never ask them to pick more.
- Ask about THEIR day. Never invent a routine or an inbox of your own to compare theirs
  against, and never claim their job as yours.
- Nothing about their life is known until they say it. An example you offer to unstick them
  belongs to nobody: never attribute it to them, and never treat one you invented a turn ago
  as something they told you. To someone who signed up minutes ago, a guess replayed as
  memory reads as surveillance.
- Gmail or Calendar: if what they described genuinely needs it, ask ONCE. If they skip it,
  drop it and keep going without it.
- Their words, their week: talk the way a {profession} talks.

What they asked for:
{playbooks}"""


def build_new_user_guidance(profession: str, needs: list[OnboardingNeed]) -> str:
    """The guidance block for a user with these onboarding answers, or ``""``.

    Empty when the user picked no needs: with nothing to anchor on, the block
    would be the generic coaching it exists to prevent.
    """
    playbooks = "\n".join(f"- {NEED_PLAYBOOKS[need]}" for need in needs if need in NEED_PLAYBOOKS)
    if not playbooks:
        return ""
    return NEW_USER_GUIDANCE_TEMPLATE.format(profession=profession or "person", playbooks=playbooks)
