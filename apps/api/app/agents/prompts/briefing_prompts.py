"""Execution prompts for the briefing system workflows.

Both prompts are written to be frozen into a playbook (see the docstring on
``app/models/playbook_models.py``): the gathering is a fixed, ordered list of
read-only calls, one per connected integration, with a fixed window each, and
no call whose presence depends on what an earlier call found. Integrations the
user has not connected are omitted, not branched on: the connected set is
stable between runs for one user, so the sequence a run makes is the same
sequence the next run makes. All judgement lives in the single prose slot at
the end, which is what a playbook's ``result_brief`` carries.

Weekly digest output shape, in this order, one block per line group. The HTML
rendering is a later step and reads exactly this; keep it stable:

    WEEK OF <Mon D> TO <Mon D>

    GAIA
    - workflows: <n> active of <n>, <n> runs to date
    - todos: <n> open, <n> completed, <n> overdue

    YOU
    - <integration>: <count> <noun>, <count> <noun>
    - <integration>: ...

    NOTABLE
    - <one line>
    - <one line>

    NEXT
    <one line>

An integration with nothing to count still gets its YOU line with zeros. An
integration that is not connected gets no line at all. The GAIA block reads
what ``list_workflows`` and ``get_todo_statistics`` return today, which are
to-date totals: a per-week count of runs, drafts and GAIA-created todos needs
a read the executor does not have yet, and the prompt does not pretend it does.
"""

_GATHER_RULES = """This is a read-only run. Gather, then write. Do not create, send, draft, edit, complete, or schedule anything, and do not search the web or search memory.

Gather in exactly this order, once. Your context lists the integrations the user has connected. For each integration below that is connected, make exactly the read named for it, with the window given, and nothing else for it. For one that is not connected, make no call and do not go looking for it. Never probe whether something is connected, never retry with a different query, never follow up on what a read returns with another read. If a read comes back empty, that integration simply has nothing this time.

"""

_VOICE = """Write like a person talking to someone they work with. Open on the point, vary sentence length, plain words, no headings, no markdown, no tables, no bullets unless the format below asks for them, no emoji, no throat clearing. Do not overcorrect into forced chattiness or slang. Never invent a number, a name, a link, or an outcome that is not in what you gathered."""


DAILY_BRIEFING_PROMPT = (
    """Write the user's daily briefing from what is in front of them today.

"""
    + _GATHER_RULES
    + """1. Google Calendar: events from the start of today to the end of today in the user's timezone.
2. Gmail: inbox threads that arrived in the last 24 hours, at most 25.
3. GitHub: pull requests the user opened, that were merged, or that are waiting on the user's review, updated in the last 24 hours.
4. Linear: issues assigned to the user updated in the last 24 hours, plus any due today.
5. Notion: pages updated in the last 24 hours.
6. Slack: messages mentioning the user in the last 24 hours, plus unread direct messages.
7. GAIA todos: the user's todos due today or overdue (get_today_todos).

Then write the briefing as plain text, at most 12 lines, in this order: the shape of the day (meetings, with times), then what is waiting on the user (mail from a real person that has no reply yet, reviews requested, issues due, mentions), then what moved since yesterday (merged, closed, edited). Skip newsletters, receipts, notifications from bots, and anything the user already replied to. Name senders and titles; give times in the user's timezone. Leave out any section that has nothing in it rather than saying it is empty.

If every read came back with nothing to act on, the whole briefing is one or two lines saying the calendar is clear and nothing is waiting, so the day is open. Never pad an empty day and never skip writing it.

End with one final line, on its own, starting with "Next:". It names one concrete thing GAIA could do for this user that it is not doing yet, chosen from the integrations NOT in the connected list (for example that pull requests waiting on their review would appear here once GitHub is connected) or, if every integration above is connected, from a GAIA feature this run's data shows unused (no todos at all, no reminders). One factual sentence, no pitch, no exclamation mark.

"""
    + _VOICE
)


WEEKLY_DIGEST_PROMPT = (
    """Write the user's weekly digest: the receipt for the last seven days, numbers first.

"""
    + _GATHER_RULES
    + """1. GAIA workflows: the user's workflows and their execution counts (list_workflows).
2. GAIA todos: the user's todo statistics (get_todo_statistics).
3. Google Calendar: events from seven days ago to now in the user's timezone.
4. Gmail: threads the user sent in the last 7 days, at most 50, and inbox threads that arrived in the last 7 days, at most 50.
5. GitHub: pull requests the user opened, merged, or reviewed in the last 7 days, and issues the user closed in the last 7 days.
6. Linear: issues assigned to the user that were completed in the last 7 days, and those still open.
7. Notion: pages the user created or edited in the last 7 days.
8. Slack: messages the user sent in the last 7 days, at most 100.

Then write the digest as plain text in exactly this shape, one item per line, counts before words. Include a YOU line for every connected integration above, with zeros when it had nothing, and no line for one that is not connected. NOTABLE holds at most three lines, each a single concrete thing from the week (the biggest merged PR, the longest meeting day, the thread that went back and forth most); leave the section out entirely if the week gives you nothing concrete. NEXT is one factual sentence naming one thing GAIA could do for this user that it is not doing yet, chosen from the integrations NOT connected, or, if all are, from a feature the numbers show unused. No pitch.

WEEK OF <Mon D> TO <Mon D>

GAIA
- workflows: <n> active of <n>, <n> runs to date
- todos: <n> open, <n> completed, <n> overdue

YOU
- Calendar: <n> meetings, <h> hours
- Gmail: <n> sent, <n> received
- GitHub: <n> PRs opened, <n> merged, <n> reviewed
- Linear: <n> completed, <n> open
- Notion: <n> pages edited
- Slack: <n> messages sent

NOTABLE
- <one line>

NEXT
<one line>

"""
    + _VOICE
)
