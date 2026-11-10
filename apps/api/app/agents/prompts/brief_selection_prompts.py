"""The prompts for the one call that chooses what a brief says, across every source: daily and weekly."""

_ITEM_LINES = """Each line: its id, [app], where its producer would file it (needs_you, update, gaia_did or
event), then its title, detail, due date and people, and its action or outcome when its source
knows it. "important" marks what a scout already judged important.
{items}"""

_LEAD = """- lead: at most one id, the single thing most worth starting the {period} on, and only when GAIA can
  concretely help with it. offer is what GAIA will do when the user says "Let's do it", in one
  short sentence naming the action ("Draft the reply to Priya"). Leave lead and offer empty when
  nothing fits. The lead is not repeated in any other list. An event can only be the lead."""

_PLACEMENT = """Every id that is not an event goes in exactly one list. Never invent an id.

Word every id you keep in lead, needs_you, updates or gaia_did, from that line's facts alone:
- title: a noun phrase of at most {title_max} characters, never a sentence: "Acme invoice",
  "Priya's offsite venues", "CRM sync". Name the thing, not the action.
- detail: at most one line of {detail_max} characters adding the one fact that matters (who,
  when, why), or null. Never repeat the title.
- lead and needs_you carry action, what the user does: one of {actions}. updates and
  gaia_did carry outcome, where it got to: one of {outcomes}. A line that names its action or
  outcome already has it: give that one."""

BRIEF_SELECTION_PROMPT = f"""You choose what goes in the user's morning brief. Today is {{today}} ({{timezone}}).

Below is everything GAIA found: items from the user's connected apps, GAIA's own tracked work,
results it held for this brief, approvals and reminders waiting on them, failed runs and today's
calendar. App items are every row a scout's calls returned, so most are noise. When each app's
scout first looked, it wrote down how to tell what in that app needs this user:
{{criteria}}

{_ITEM_LINES}

Choose by importance to this user today, never by source or by order:
- needs_you: what only the user can act on: a person waiting on their reply or decision, an
  approval, work assigned to them that is due or overdue, something that failed and needs a call.
  At most {{needs_you_cap}}, most important first.
- updates: what moved in their apps that they would want to know, but need not act on. At most
  {{updates_cap}}.
- gaia_did: what GAIA finished or is doing for them that is worth a line. At most {{gaia_did_cap}}.
{_LEAD.format(period="day")}
- dropped: every other id. Drop recurring personal routines, shopping, entertainment, reference
  items, anything done or closed, and anything only informational. An item earlier briefs already
  mentioned that has not moved is not news: keep it only if it still needs them.

{_PLACEMENT}
"""

WEEKLY_SELECTION_PROMPT = f"""You choose what goes in the user's weekly digest. Today is {{today}} ({{timezone}}).
The digest looks back on the week since Monday and ahead to the next seven days.

Below is everything GAIA found: what the user finished this week, what GAIA finished for them,
workflow runs that failed this week, and the calendar for the week ahead. Finished work is what
this digest is for, so a finished item is never dropped for being done.

{_ITEM_LINES}

Choose by what mattered most to this user this week, never by source or by order:
- needs_you: what still waits on the user, such as a workflow that failed and needs a call. At most
  {{needs_you_cap}}, most important first.
- updates: what the user finished this week that is worth a line. At most {{updates_cap}}.
- gaia_did: what GAIA finished for them this week that is worth a line. At most {{gaia_did_cap}}.
{_LEAD.format(period="week")}
- dropped: every other id: routine chores, repeats of an item already kept, and anything too small
  to mention.

{_PLACEMENT}
"""
