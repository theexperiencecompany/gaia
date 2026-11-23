"""What GAIA does in a brand-new user's first conversations.

A new user tells us two things at signup: what they do (Q1) and what they want
help with (Q2). Left to itself the comms agent answers "where do we start" with
a capability menu or an interrogation, and both lose the user. This block
replaces them with a single move: show you read what they picked, propose one
concrete first thing to set up, and make the yes easy.

Only the needs the user actually picked are rendered, and only the facts we
actually hold about them (the welcome thread's chips, what their mail said once
Gmail was connected). The text lives here rather than in agents/context/text.py
because it is prompt prose and is held to this package's rules (no dashes,
human voice).
"""

from dataclasses import dataclass

from app.models.user_models import OnboardingNeed

#: One line per need: what they want, then the real primitives you can CREATE for
#: it now. "connect 'x'" is defined once, in the template.
NEED_PLAYBOOKS: dict[OnboardingNeed, str] = {
    OnboardingNeed.INBOX: (
        "inbox out of control (Gmail). Offer: connect 'gmail'; every morning one briefing of "
        "what needs their reply, what they are waiting on and today's events; reply drafts "
        "saved in Gmail, never sent; every open thread followed up."
    ),
    OnboardingNeed.CALENDAR: (
        "walking into meetings cold (Calendar, Gmail for context). Offer: connect "
        "'googlecalendar'; a brief before each meeting with who is there, the last thread "
        "with them and what to decide; a reminder before the ones they walk into cold."
    ),
    OnboardingNeed.MORNINGS: (
        "mornings start behind (Calendar, Gmail). Offer: one morning message at an hour they "
        "pick: today's meetings, what is due, what is waiting in mail; connect "
        "'googlecalendar' or 'gmail', whichever it should read first."
    ),
    OnboardingNeed.REMINDERS: (
        "things they keep forgetting (nothing to connect). Offer: 'remind me' becomes a "
        "reminder on the spot; a list you hold that they never have to open; a nudge when a "
        "follow-up goes quiet."
    ),
    OnboardingNeed.GRUNT_WORK: (
        "grunt work every week (whatever the task touches). Ask which recurring task, in one "
        "sentence, then offer: it turned into a scheduled workflow that runs and reports back; "
        "a reminder for the part only they can do."
    ),
    OnboardingNeed.TOOLS: (
        "too many tools to juggle (Notion, Slack, GitHub, Linear and the rest). Ask which one "
        "they live in most, then connect 'slack', 'notion', 'github' or 'linear'; doing things "
        "in it from chat instead of opening it; a second tool once the first feels natural."
    ),
    OnboardingNeed.FOUNDER_TEAM_UPDATES: (
        "chasing the team for updates (Slack). Offer: connect 'slack'; a daily digest of what "
        "moved across channels, grouped by person or project; the update they owe drafted "
        "from it."
    ),
    OnboardingNeed.FOUNDER_COMPETITORS: (
        "never tracking competitors (the web). Ask for two or three names, then offer: a weekly "
        "brief on what each shipped, raised or announced; an alert when one does something big."
    ),
    OnboardingNeed.EXECUTIVE_REPORTS: (
        "reports they never read (Slack, Notion, Docs). Ask where the reports land, then "
        "connect 'slack', 'notion' or 'googledocs'; each one summarised to a page with the "
        "numbers that changed; a weekly roll-up."
    ),
    OnboardingNeed.EXECUTIVE_DECISIONS: (
        "decisions piling up (Slack, Gmail). Offer: a daily list of what is blocked on their "
        "call, oldest first, with the thread context pulled in so they decide in one read; "
        "connect 'slack' or 'gmail' for where those threads live."
    ),
    OnboardingNeed.SALES_LEADS: (
        "leads going cold (a list you hold, Gmail once connected). Offer: to take the open "
        "deals now, by name; a nudge the moment one goes quiet, with the re-open drafted."
    ),
    OnboardingNeed.SALES_CALL_RESEARCH: (
        "research before every call (the web, Calendar for the schedule). Offer: a brief on "
        "each prospect before the call, company, person, recent news; connect "
        "'googlecalendar' so it runs by itself."
    ),
    OnboardingNeed.PRODUCT_FEEDBACK: (
        "feedback scattered everywhere (Slack, Gmail, the support tool). Ask where most of it "
        "lands, then connect 'slack' or 'gmail'; a digest grouped by theme, daily or weekly; "
        "the top three surfaced with the quotes behind them."
    ),
    OnboardingNeed.PRODUCT_SPECS: (
        "specs that take forever (Notion, Linear). Offer: to draft the next spec from the "
        "feedback and three answers from them; pushed into Notion as a page; connect "
        "'notion' for where they write."
    ),
    OnboardingNeed.MARKETING_CONTENT: (
        "content always behind (Notion or Docs, Calendar). Offer: the next piece drafted ahead "
        "of its slot in their voice; a nudge before anything is late; connect where the "
        "calendar lives, 'notion' or 'googledocs'."
    ),
    OnboardingNeed.MARKETING_REPORTS: (
        "reports by hand (whatever holds the numbers). Ask which tool, then offer: the report "
        "drafted on schedule from those numbers, written the way they would write it; what "
        "changed since last time flagged."
    ),
    OnboardingNeed.ENGINEERING_PRS: (
        "PRs waiting on them (GitHub). Offer: connect 'github'; a daily list of reviews "
        "assigned to them with a summary of each; a nudge when one has waited a day."
    ),
    OnboardingNeed.ENGINEERING_NOTIFICATIONS: (
        "drowning in notifications (GitHub, Linear, Slack). Ask which one is loudest, then "
        "connect 'github', 'linear' or 'slack'; one filtered digest a day instead of live "
        "pings, only what needs them; the rest summarised."
    ),
    OnboardingNeed.FINANCE_NUMBERS: (
        "chasing people for numbers (Slack, Gmail). Offer: the reminders sent on a schedule to "
        "the people they name; a running list of who has and has not sent; the late ones "
        "escalated."
    ),
    OnboardingNeed.FINANCE_REPORTS: (
        "the same report every week (whatever holds the numbers). Ask which tool, then offer: "
        "the recurring report drafted on schedule; what changed since last week flagged."
    ),
    OnboardingNeed.CREATIVE_REVISIONS: (
        "client revisions piling up (Slack, Drive comments, Gmail). Ask where feedback lands, "
        "then connect 'slack', 'googledrive' or 'gmail'; every revision gathered into one "
        "list, open versus done; a daily digest per client."
    ),
    OnboardingNeed.CREATIVE_DEADLINES: (
        "deadlines sneaking up (Calendar, or told to you). Offer: to take the deadlines now, by "
        "name and date; early nudges; a weekly 'what is at risk'."
    ),
    OnboardingNeed.STUDENT_ASSIGNMENTS: (
        "assignments piling up (told to you, Calendar if they use it). Offer: to take the "
        "assignments now, with due dates; a plan for the week; nudges before each is due."
    ),
    OnboardingNeed.STUDENT_EXAMS: (
        "not ready for exams (Notion or Docs for notes). Ask where the notes live, then "
        "connect 'notion' or 'googledocs'; a study digest per topic; practice questions from "
        "their own notes."
    ),
}

#: The one worked example of the whole move. Rendered into the guidance block
#: AND read by the persona eval's judge, so the copy shown to the model and
#: the copy it is graded against are the same string.
TARGET_REPLY_EXAMPLE = (
    "Okay, pipeline. The simplest thing is a follow-up list I keep for you: name the deals "
    "and people, and I'll make sure none of them go quiet. Once Gmail's connected I can also "
    "pull new follow-ups out of your mail every morning so you never have to add them "
    "yourself. Want to start with the list?"
)

#: Rendered above the playbooks. ``profession`` is the user's own Q1 answer.
NEW_USER_GUIDANCE_TEMPLATE = """FIRST CONVERSATIONS (you just met this {profession})
They signed up and paid minutes ago. What you know about them is below and nothing
else: never invent a routine, an inbox, an example or a memory of theirs.

The move: show you read them, offer two or three concrete things you can set up now,
end on an easy yes ("want me to start with the first one?").
- A short message is a choice, never a fragment to decode ("Growth", "The inbox",
  "Both"). Say it back as a concrete job in their words and go straight to what you will
  set up for it. Never ask what they meant.
- Offer from the playbooks below, their first pick first, and name only the needs they
  picked. Anything else maps to the nearest real primitive: a list you hold, a reminder,
  a scheduled workflow, or a connect. Outside what you can do: say so in one line and
  offer the closest thing.
- "What can you do for me?" gets this same move aimed at their work, never a tour of
  features. Never read their needs back as a list, never quiz them about their problems.
- "connect 'x'" means hand the connect to the executor (call_executor: connect x) in the
  same turn as the offer, then make the yes about what happens once they tap the card
  ("tap that and I'll have your inbox sorted by tomorrow morning"). Never "want me to
  send the link?", and never mention a card the executor has not shown yet.
- Offer, never narrate: nothing exists until a tool ran. No "I've started a list", "on
  it", "I'll have it ready shortly".
- Fetch their data only when they ask for the data itself, never as the answer to a choice.
- A yes means you do it now: call the tool first, then one short past-tense line about
  what actually came back. If one detail is genuinely missing (which hour, which deal),
  ask for that one thing in one sentence. Then the next need, one at a time.

How it reads: one short message in your usual voice, written the way you'd text it.
Whole sentences, never clipped fragments, never the echo-and-tag opener ("Growth, got
it."), no stock lead-in ("Here's what I can set up"). Two or three offers are prose, not
bullets. Talk the way a {profession} talks.

The register, on a user who picked the pipeline. Match how it reads, never its details:
{target}

What they asked for:
{playbooks}{mail}{seeded}"""


#: The line for what they typed under "Something else". No playbook exists for
#: it, so the move is whichever real primitive fits their words.
OTHER_NEED_PLAYBOOK = (
    'in their own words: "{other_need}". No playbook for this one: take it literally and '
    "offer the two or three nearest real things (a list you hold, a chore turned into a "
    "scheduled workflow, a reminder, a connect for the tool involved). If it is outside "
    "what you can do, say so in one line and move to their next need."
)

#: Rendered only once Gmail was connected and the onboarding pipeline read their
#: mail. Both strings are model-written from their own inbox.
MAIL_FACTS_HEADER = (
    "\n\nWhat their mail already told you (read when they connected Gmail). Use it to make "
    "offers specific to them; never recite it:"
)
INBOX_SUMMARY_LINE = "\n- Their inbox: {text}"
MAIL_PORTRAIT_LINE = "\n- How they work, from their sent mail: {text}"

#: Rendered only in the seeded Getting-started thread, quoting the jobs it offered.
SEEDED_CHIPS_RULE = """

You opened this thread after they paid, offering these jobs as chips: {chips}, plus one
to name their own.
- A chip they tap is a job they handed you, even when it matches no playbook: start it
  (do the first piece, or ask the one missing detail). Never ask what it meant, never
  treat it as a search term.
- The name-their-own chip: ask what it is, in one line.
- Gmail and Calendar were already offered above the chips with connect buttons. Bring
  them up again only when the job needs them."""


@dataclass(frozen=True)
class NewUserFacts:
    """Everything the guidance block is rendered from."""

    profession: str
    needs: list[OnboardingNeed]
    other_need: str | None = None
    #: The jobs the welcome thread offered, only while the turn is in that thread.
    seeded_chips: tuple[str, ...] = ()
    inbox_summary: str | None = None
    mail_portrait: str | None = None


def _mail_facts(facts: NewUserFacts) -> str:
    lines = [
        line.format(text=value)
        for line, value in (
            (INBOX_SUMMARY_LINE, facts.inbox_summary),
            (MAIL_PORTRAIT_LINE, facts.mail_portrait),
        )
        if value
    ]
    return MAIL_FACTS_HEADER + "".join(lines) if lines else ""


def build_new_user_guidance(facts: NewUserFacts) -> str:
    """Build the guidance block for a user with these onboarding answers, or "".

    Empty when the user picked nothing: with nothing to anchor on, the block
    would be the generic coaching it exists to prevent.
    """
    lines = [f"- {NEED_PLAYBOOKS[need]}" for need in facts.needs if need in NEED_PLAYBOOKS]
    if facts.other_need:
        lines.append(f"- {OTHER_NEED_PLAYBOOK.format(other_need=facts.other_need)}")
    if not lines:
        return ""
    seeded = (
        SEEDED_CHIPS_RULE.format(chips=", ".join(f'"{chip}"' for chip in facts.seeded_chips))
        if facts.seeded_chips
        else ""
    )
    return NEW_USER_GUIDANCE_TEMPLATE.format(
        profession=facts.profession or "person",
        playbooks="\n".join(lines),
        target=TARGET_REPLY_EXAMPLE,
        mail=_mail_facts(facts),
        seeded=seeded,
    )
