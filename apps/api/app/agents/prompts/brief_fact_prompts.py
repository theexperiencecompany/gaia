"""What a brief's composition and voice are told about their facts, besides the fact lines themselves."""

from collections.abc import Mapping
from types import MappingProxyType

from app.constants.todos import TodoCompleter, WaitingOn
from app.models.brief_item_models import ItemState
from app.models.brief_slot_models import CountName, CountSlot
from app.models.calendar_models import CalendarResponse
from app.models.scheduler_models import DeactivationReason

#: How the composition names a reader whose name GAIA does not know.
UNNAMED_READER = "the user"

# The span each kind of brief reads the calendar over, as its composition is told.
TODAY_SPAN = "today"
WEEK_AHEAD_SPAN = "in the week ahead"
#: What the brief is told when no calendar is connected, so it never calls the user's day empty.
NO_CALENDAR_CONNECTED = (
    "No calendar is connected, so nothing is known about the user's schedule: "
    "never say it is empty, open or clear."
)
CALENDAR_UNAVAILABLE = (
    "The user's calendar could not be read this time, so nothing is known about their "
    "schedule: never say it is empty, open or clear; say once that it could not be read."
)
CALENDAR_EMPTY_IN = "Nothing on the calendar {span}."
CALENDAR_LISTED_IN = "Calendar {span}: {count} event(s), every one listed below."

#: How an undated todo of the user's own reads in the pool and the facts: background, not news.
BACKLOG_STATE = "on their list, undated"
#: How an item an earlier brief already showed, unchanged, is marked: still open, not news.
REPEAT_MARK = "already shown, still open"
#: The head state of GAIA's open work that is not being worked on right now.
OPEN_STATE = "open"
#: How many tracked todos one item stands for, as its line says it.
ON_ONE_SUBJECT = "todos on this one subject"
#: How a done todo reads, by who closed it.
DONE_BY: Mapping[TodoCompleter | None, str] = MappingProxyType(
    {
        TodoCompleter.GAIA: "done by GAIA",
        TodoCompleter.USER: "done by the user",
        TodoCompleter.TRIGGER: "closed by an event it watched",
        TodoCompleter.SYSTEM: "closed by GAIA's housekeeping",
        None: "done, who finished it is not recorded",
    }
)
#: What each item state means, said beside the pool's items so every reader reads them alike.
ITEM_STATES_LEGEND = (
    "done by GAIA / done by the user / closed: finished since {done_since}, by whoever its "
    f"state names; {ItemState.GAIA.label.lower()}: GAIA is working on it; "
    f"{OPEN_STATE}: GAIA's work that is not being worked on now, its line says where it stands; "
    f"{ItemState.YOU.label.lower()}: needs the user; "
    f"{ItemState.FAILED.label.lower()}: broke and needs the user; "
    f"{ItemState.NOTE.label.lower()}: news that needs nothing; "
    f"{BACKLOG_STATE}: an undated todo of their own, never news and never the lead. "
    f"An item marked {REPEAT_MARK} was already shown, unchanged: not news, so it never leads"
)
#: Where open tracked work stands when GAIA is not simply working on it.
STANDING_PAUSED = "paused: {why}"
PAUSED_BECAUSE: Mapping[DeactivationReason, str] = MappingProxyType(
    {
        DeactivationReason.USER_DORMANT: "while the user was away",
        DeactivationReason.INTEGRATION_EXPIRED: "its app's connection expired",
        DeactivationReason.INTEGRATION_NEVER_CONNECTED: "the app it needs was never connected",
        DeactivationReason.SUBSCRIPTION_LAPSED: "the user's plan lapsed",
        DeactivationReason.INVALID_SCHEDULE: "its schedule is invalid",
        DeactivationReason.OWNER_NOT_FOUND: "its owner is gone",
    }
)
STANDING_WAITING_ON_OTHERS = "waiting on someone else's reply, not the user's"
STANDING_WAITS: Mapping[WaitingOn, str] = MappingProxyType(
    {
        WaitingOn.EVENT: "waiting on an event it watches",
        WaitingOn.SUB_TODOS: "its sub-todos are doing the work",
        WaitingOn.TIME: "GAIA looks at it again",
        WaitingOn.UNPLANNED: "captured, not started: GAIA plans it",
    }
)
#: The waits whose standing goes on to say when GAIA comes back to the work.
STANDING_TIMED_WAITS = frozenset({WaitingOn.TIME, WaitingOn.UNPLANNED})

#: What a calendar event's line adds to its title and start.
ALL_DAY = "all day"
#: How every item's line reads, to the composition and the voice alike.
ITEM_LINE_FORM = "id. [app] state: title | detail | due | people | action or outcome"
#: Tells the voice how its facts read: the composition's lines, numbered by fact.
FACT_LINES_NOTE = (
    f"Each item reads {ITEM_LINE_FORM}, its id the fact number its slots take; "
    "a slot's value follows it in brackets."
)
#: Heads the voice's block of the app signals the brief placed.
SIGNALS_HEADER = "[ACROSS THEIR APPS]"
#: A scout reads one page of an app, capped at SCOUT_SIGNAL_CEILING, and the judge keeps
#: only what matters: a count here is what the brief shows, never how many the app holds.
SHOWN_NOT_TOTAL = "Counts are of the items shown here, not each app's total: an app may hold more."
#: Marks a fact with something to open: the voice may link it.
LINKABLE = "linkable"
#: Marks GAIA's work whose deliverable waits on the user.
WAITING_ON_YOU = "waiting on you"
EVENT_UNTIL = "until {time}"
EVENT_ON_CALENDAR = "on the {calendar} calendar"
EVENT_ORGANIZED_BY = "organized by {organizer}"
EVENT_GUESTS = "{guests} other(s) invited"
EVENT_ANSWERED: Mapping[CalendarResponse, str] = MappingProxyType(
    {
        CalendarResponse.TENTATIVE: "the user answered tentative",
        CalendarResponse.NEEDS_ACTION: "the user has not answered the invite",
    }
)

#: Said of a series summed over the items a scout read: its total is no account's total.
SHOWN_NOT_TOTAL_SERIES = (
    "summed over the items read from one page of the app: its total is of those items, "
    "never the app's whole total"
)
#: The pool's parts, and what a part with nothing in it says.
POOL_PARTS = ("ITEMS", "SERIES", "QUOTES", "GOALS")
POOL_PART_EMPTY = "(none)"
RECENT_OPENINGS = (
    "Recent briefs opened on: {openings}. Lead somewhere new unless the same thing still matters "
    "most."
)

UNREAD_NOTE = (
    "Not read this time: {apps}. Nothing is known about what they hold today: never say "
    "they hold nothing, or that nothing there needs the user."
)
SIGNED_OUT_NOTE = (
    " Signed out: {apps}. Their sign-in expired, so they stay unread until the user reconnects "
    "them in Settings, Integrations: say so in one short line."
)

#: Said after a day or week whose facts hold no item.
NO_CLAIM = "Do not claim anything ran, finished, or is pending beyond what is stated here."
TODAY_HEADING = "Today's calendar"
TODAY_EMPTY = "The user's calendar has nothing today."
TODAY_NO_ITEMS = f"No tracked work, results or app items need them today. {NO_CLAIM}"
WEEK_AHEAD_HEADING = "The week ahead"
WEEK_AHEAD_EMPTY = "The user's calendar has nothing in the week ahead."
WEEK_AHEAD_NO_ITEMS = f"The digest holds no items from this week. {NO_CLAIM}"

COUNTS_HEADER = "[COUNTS]"
BLOCKS_HEADER = "[ALSO IN THE BRIEF]"
WEEK_IN_NUMBERS_HEADER = (
    "[THE WEEK IN NUMBERS] (voice these as one grouped recap of the week, never as a list)"
)
GOALS_THIS_WEEK_HEADER = "[GOALS THIS WEEK]"
#: A goal's todos the brief also places, pointed to as those items so the voice says each once.
PLACED_GOAL_TODOS = "also {items} above (say each only once, as its item)"

_OPEN_TRACKED = CountSlot(CountName.OPEN_TRACKED)
TRACKED_BESIDE_OWN = f" GAIA's tracked work holds {_OPEN_TRACKED} open beside them."
ONLY_TRACKED_TODOS = (
    f"The user has no todos of their own outside GAIA's tracked work, which holds {_OPEN_TRACKED} "
    "open: never call their todo list empty or clear."
)
OWN_TODOS_EMPTY = "The user's own todo list is empty."
OWN_TODOS_COUNTED = (
    f"The user's own open todos are counted in {COUNTS_HEADER}; never voice that list as clear or "
    "empty."
)
_OVERDUE_TODOS = CountSlot(CountName.OVERDUE_TODOS)
OWN_TODOS_OVERDUE = (
    f" {_OVERDUE_TODOS} of them are past due: say that count in one plain line that names them "
    f'as the user\'s GAIA todos ("{_OVERDUE_TODOS} of your GAIA todos are overdue"), never beside '
    "another app's items, and never list them."
)

#: What a weekly digest that places nothing is sent back with: it recaps the week.
EMPTY_DIGEST = (
    "a weekly digest recaps the week: place what its pool holds of it (what got done, "
    "its series, each goal's progress, even a stalled one) instead of nothing"
)
UNREADABLE_COMPOSITION = "the answer was not a whole BriefComposition tool call ({problems})"
NO_WHOLE_COMPOSITION = "(no whole composition)"
