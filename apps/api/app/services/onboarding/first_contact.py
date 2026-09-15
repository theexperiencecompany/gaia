"""GAIA's whole first contact on a freshly linked platform, composed by the server.

Deterministic and LLM-free, by decision. The first version handed the composed
opener to the model as a normal turn and asked the prompt for the shape; live
runs showed it skipping the per-pick lines, delegating to the executor, and
sometimes never producing the connect links at all. The one message a user is
guaranteed to read is not something to leave to sampling.

Three bubbles (two when they picked nothing):

1. the hello,
2. one sentence that says what GAIA does from here for the things they
   picked (their picks become clauses, not a list), with their typed words,
3. the first move: either the connect links the picks cannot work without,
   with the reason, or one question about their first pick that they can
   answer in five words.

A connect link is only asked for when the job is impossible without the
account (the inbox needs Gmail, a meeting brief needs the calendar). Everything
else is a question, and the answer's playbook offers a link later, in context.

Links are written as markdown; every bot's ``send`` renders markdown for its
platform (Telegram: a real hyperlink; WhatsApp and iMessage: ``label (url)``).

The rules of the voice apply here as everywhere (``agents/prompts/comms_prompts``):
short lines, plain words, no exclamation marks, no emoji, never a feature list.
"""

from app.config.oauth_config import get_integration_by_id
from app.db.repositories.user_integrations import user_integration_repository
from app.models.user_models import OnboardingNeed, OnboardingPreferences
from app.services.connect_link_service import build_connect_link_url
from shared.py.wide_events import log

#: The hello a bot sends the moment a link code is redeemed. It opens the
#: promise sentence, so it ends on a comma and never stands alone as a bubble.
LINK_GREETING_WITH_NAME = "Hey {name}, I'm with you on {platform} now."
#: Same line with the name clause dropped: greeting a blank is worse than not
#: using a name at all.
LINK_GREETING = "Hey, I'm with you on {platform} now."


def compose_link_greeting(platform: str, name: str | None) -> str:
    """GAIA's hello on a freshly linked platform.

    ``name`` is the GAIA user's full name; only the first token is used, because
    a greeting that says the surname is an email, not a text.
    """
    from app.services.onboarding.first_conversation import (  # noqa: PLC0415 -- first_conversation imports the onboarding package for its phrases; a top-level import back would be a cycle
        platform_label,
    )

    label = platform_label(platform)
    tokens = (name or "").split()
    if tokens:
        return LINK_GREETING_WITH_NAME.format(name=tokens[0], platform=label)
    return LINK_GREETING.format(platform=label)


#: What GAIA does about each pick, as a clause that follows "From here, ...".
#: Present tense, second person, no full stop: the clauses are joined into one
#: sentence in the order the user tapped.
#:
#: Every member of ``OnboardingNeed`` has an entry and a drift test enforces it:
#: a need with no clause renders as a silently skipped pick, which is the one
#: failure this whole module exists to stop.
NEED_CLAUSES: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: "every morning your inbox comes sorted with replies drafted",
    OnboardingNeed.CALENDAR: "you get a brief before each meeting",
    OnboardingNeed.MORNINGS: "your day starts with a brief, not a scramble",
    OnboardingNeed.REMINDERS: "tell me once and I'll remind you when it matters",
    OnboardingNeed.GRUNT_WORK: "whatever grunt work you hand me gets done",
    OnboardingNeed.TOOLS: "name the tool you live in and I'll run it from here",
    OnboardingNeed.FOUNDER_TEAM_UPDATES: "I bring you what your team moved on, every day",
    OnboardingNeed.FOUNDER_COMPETITORS: "I watch your competitors and tell you what changed",
    OnboardingNeed.EXECUTIVE_REPORTS: "every report comes back as one page of what moved",
    OnboardingNeed.EXECUTIVE_DECISIONS: (
        "blocked decisions reach you with enough context to decide in one read"
    ),
    OnboardingNeed.SALES_LEADS: "I hold your open deals and nudge you the moment one goes quiet",
    OnboardingNeed.SALES_CALL_RESEARCH: "the brief is waiting before you dial",
    OnboardingNeed.PRODUCT_FEEDBACK: "feedback lands in one digest, grouped by theme",
    OnboardingNeed.PRODUCT_SPECS: "I draft the next spec from the feedback and you edit",
    OnboardingNeed.MARKETING_CONTENT: "the next piece is drafted before its slot, in your voice",
    OnboardingNeed.MARKETING_REPORTS: "the weekly report writes itself from your numbers",
    OnboardingNeed.ENGINEERING_PRS: "you get the list of PRs needing you, each with a summary",
    OnboardingNeed.ENGINEERING_NOTIFICATIONS: (
        "notifications become one digest a day, only what needs you"
    ),
    OnboardingNeed.FINANCE_NUMBERS: "I chase the numbers and track who has sent",
    OnboardingNeed.FINANCE_REPORTS: "the report drafts itself on schedule with what changed flagged",
    OnboardingNeed.CREATIVE_REVISIONS: "every revision sits in one list, open versus done",
    OnboardingNeed.CREATIVE_DEADLINES: "I hold your deadlines and warn you early",
    OnboardingNeed.STUDENT_ASSIGNMENTS: "I hold your assignments and nudge you before each is due",
    OnboardingNeed.STUDENT_EXAMS: "your notes become a study digest with practice questions",
}

#: Their own words under "Something else". Nobody parsed the text, so GAIA
#: says it back and commits rather than inventing a plan for it.
OTHER_NEED_SENTENCE = 'You also said "{other_need}". That\'s mine too.'

#: The first move when nothing needs connecting: one question about their
#: first pick, with the reason it is being asked, answerable in a few words.
#: For a pick that normally needs an account, this is the version for when the
#: account is already connected.
#:
#: Every member of ``OnboardingNeed`` has an entry (drift test).
NEED_ASKS: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: (
        "Gmail's already on, so the inbox starts tomorrow morning. "
        "Anyone whose emails I should always flag?"
    ),
    OnboardingNeed.CALENDAR: (
        "Your calendar's already on, so the briefs start with your next meeting. "
        "Want one for today's?"
    ),
    OnboardingNeed.MORNINGS: (
        "Gmail's on, so your first brief lands tomorrow morning. What time do you want it?"
    ),
    OnboardingNeed.REMINDERS: (
        "For the forgetting, start me off with the first thing you don't want to lose. "
        "Tell me once and it's held."
    ),
    OnboardingNeed.GRUNT_WORK: (
        "The grunt work is the fastest win, so tell me the first thing you want off your "
        "plate this week."
    ),
    OnboardingNeed.TOOLS: (
        "Since you're spread across tools, which one are you in most? I'll run it from here."
    ),
    OnboardingNeed.FOUNDER_TEAM_UPDATES: (
        "For the team updates, where does your team post them, Slack or email? "
        "I'll pick them up from there."
    ),
    OnboardingNeed.FOUNDER_COMPETITORS: (
        "For the competitor watch, name two and I'll start today."
    ),
    OnboardingNeed.EXECUTIVE_REPORTS: (
        "For the reports, forward me the next one you're dreading and I'll cut it to a page."
    ),
    OnboardingNeed.EXECUTIVE_DECISIONS: (
        "For the decisions, what's one stuck on you right now? "
        "I'll bring you what you need to call it."
    ),
    OnboardingNeed.SALES_LEADS: (
        "Gmail's on, so I'll start on the open deals. Which one worries you most?"
    ),
    OnboardingNeed.SALES_CALL_RESEARCH: (
        "Your calendar's on, so the brief for your next call is mine. Which call is it?"
    ),
    OnboardingNeed.PRODUCT_FEEDBACK: (
        "For the feedback, where does most of it land right now, email, Slack or a doc?"
    ),
    OnboardingNeed.PRODUCT_SPECS: (
        "For the specs, what's the next one you need? One line is enough and I'll draft it."
    ),
    OnboardingNeed.MARKETING_CONTENT: (
        "For the content, what's the next piece due and when? I'll have a draft ahead of it."
    ),
    OnboardingNeed.MARKETING_REPORTS: (
        "For the reports, send me last week's and I'll build the next one from it."
    ),
    OnboardingNeed.ENGINEERING_PRS: (
        "For the PRs, paste the repo link and I'll pull what's waiting on you."
    ),
    OnboardingNeed.ENGINEERING_NOTIFICATIONS: (
        "For the notifications, which are loudest, Slack or GitHub? I'll start the digest there."
    ),
    OnboardingNeed.FINANCE_NUMBERS: (
        "For the numbers, who do you chase most? I'll take over the chasing."
    ),
    OnboardingNeed.FINANCE_REPORTS: (
        "For the weekly report, send me the last one and I'll take the next."
    ),
    OnboardingNeed.CREATIVE_REVISIONS: (
        "For the revisions, where do they come in, email or a doc? I'll gather them into one list."
    ),
    OnboardingNeed.CREATIVE_DEADLINES: (
        "For the deadlines, what's the next one? I'll hold it and warn you early."
    ),
    OnboardingNeed.STUDENT_ASSIGNMENTS: (
        "For the assignments, what's due first? I'll hold the dates and nudge you."
    ),
    OnboardingNeed.STUDENT_EXAMS: (
        "For the exam, when is the next one? Send me your notes and I'll start the digest."
    ),
}

#: The first move when they typed something and picked nothing else.
OTHER_NEED_ASK = "Tell me a bit more about that and I'll start on it."
#: The first move when they picked nothing at all.
NO_PICKS_ASK = "Tell me one thing off your plate and I'll start there."

#: What each pick cannot work without, in ``OAUTH_INTEGRATIONS`` ids. Only the
#: jobs that are impossible without the account: sorting an inbox needs Gmail,
#: a meeting brief needs the calendar. Every other pick asks a question first
#: and its playbook offers a link later, in context, once the answer says where
#: the work lives.
NEED_INTEGRATIONS: dict[OnboardingNeed, tuple[str, ...]] = {
    OnboardingNeed.INBOX: ("gmail",),
    OnboardingNeed.CALENDAR: ("googlecalendar",),
    OnboardingNeed.MORNINGS: ("gmail",),
    OnboardingNeed.SALES_LEADS: ("gmail",),
    OnboardingNeed.SALES_CALL_RESEARCH: ("googlecalendar",),
}

#: How the connect ask names each account: what of theirs it unlocks, and the
#: link label. The reason is what makes the ask read as a step, not a demand.
_CONNECT_PHRASES: dict[str, tuple[str, str]] = {
    "gmail": ("your inbox", "Connect Gmail"),
    "googlecalendar": ("your calendar", "Connect Google Calendar"),
}


def needed_integration_ids(preferences: OnboardingPreferences) -> list[str]:
    """The integrations this user's picks need, deduped, in the order they picked.

    Pick order matters: the first thing they tapped is the thing they came for,
    so its connect link is the first one they see.
    """
    seen: list[str] = []
    for need in preferences.needs or []:
        for integration_id in NEED_INTEGRATIONS.get(need, ()):
            if integration_id not in seen:
                seen.append(integration_id)
    return seen


def _integration_display_name(integration_id: str) -> str:
    """The name the OAuth config gives this integration, for user-facing copy."""
    integration = get_integration_by_id(integration_id)
    return integration.name if integration else integration_id


def _join_clauses(clauses: list[str]) -> str:
    """Speech, not a list: "a and b", "a, b, and c"."""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + ", and " + clauses[-1]


def _opening_bubbles(
    platform: str, name: str | None, preferences: OnboardingPreferences
) -> list[str]:
    """The hello, then the promise as its own bubble (with their typed words
    folded in), so the message reads as a few texts, not one paragraph."""
    bubbles = [compose_link_greeting(platform, name)]
    clauses = [NEED_CLAUSES[need] for need in preferences.needs or [] if need in NEED_CLAUSES]
    promise: list[str] = []
    if clauses:
        promise.append(f"From here, {_join_clauses(clauses)}.")
    other = (preferences.other_need or "").strip().rstrip(".!")
    if other:
        promise.append(OTHER_NEED_SENTENCE.format(other_need=other))
    if promise:
        bubbles.append(" ".join(promise))
    return bubbles


def _connect_bubble(connect_links: list[tuple[str, str]]) -> str:
    unlocks: list[str] = []
    links: list[str] = []
    for integration_id, url in connect_links:
        unlock, label = _CONNECT_PHRASES.get(
            integration_id,
            (
                _integration_display_name(integration_id),
                f"Connect {_integration_display_name(integration_id)}",
            ),
        )
        unlocks.append(unlock)
        links.append(f"[{label}]({url})")
    if len(links) == 1:
        return f"That starts with {unlocks[0]}, which I can't see yet. One tap: {links[0]}."
    return (
        f"{_join_clauses(unlocks).capitalize()} are where I start, and I can't see them yet. "
        f"{_join_clauses(links)}. Either one first."
    )


def _ask_bubble(preferences: OnboardingPreferences) -> str:
    for need in preferences.needs or []:
        ask = NEED_ASKS.get(need)
        if ask:
            return ask
    if (preferences.other_need or "").strip():
        return OTHER_NEED_ASK
    return NO_PICKS_ASK


def compose_first_contact(
    platform: str,
    name: str | None,
    preferences: OnboardingPreferences,
    connect_links: list[tuple[str, str]],
) -> list[str]:
    """Every bubble a bot sends right after a one-tap link, in order.

    ``connect_links`` are ``(integration_id, url)`` pairs already minted by the
    caller for whatever :func:`needed_integration_ids` returned MINUS what the
    user already has connected. Minting is I/O and this stays pure, so the copy
    can be asserted without a Redis or a Mongo in the room.

    With links, the second bubble is the connect ask: a tap does more than a
    typed answer, so it wins over the question even for mixed picks. Without
    links it is one question about the first pick.
    """
    first_move = _connect_bubble(connect_links) if connect_links else _ask_bubble(preferences)
    return [*_opening_bubbles(platform, name, preferences), first_move]


async def build_first_contact(
    user_id: str,
    platform: str,
    name: str | None,
    preferences: OnboardingPreferences,
) -> list[str]:
    """:func:`compose_first_contact` with the connect links resolved and minted.

    An integration the user already connected is dropped rather than re-offered:
    the whole point of the links is that they are the first move, and a link to
    something already on is a tap that does nothing.

    A link that could not be minted (Redis down) is dropped too — an unusable
    URL in a first message is worse than one fewer.
    """
    connect_links: list[tuple[str, str]] = []
    for integration_id in needed_integration_ids(preferences):
        if await user_integration_repository.is_connected(user_id, integration_id):
            continue
        url = await build_connect_link_url(user_id, integration_id)
        if not url:
            # Dropped rather than sent broken (see above), but a first contact
            # missing the tap it exists to offer is the feature failing quietly:
            # nothing retries it and the user simply never connects.
            log.error(
                "connect link could not be minted for first contact",
                user={"id": user_id},
                integration_id=integration_id,
                platform=platform,
            )
            continue
        connect_links.append((integration_id, url))

    return compose_first_contact(platform, name, preferences, connect_links)
