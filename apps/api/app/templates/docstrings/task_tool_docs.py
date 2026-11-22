CREATE_TASK = """
    Create a task: work GAIA takes on (assignee "gaia"), or a to-do the user does (assignee "user").

    When to use:
    - assignee "gaia": GAIA itself performs or schedules a real action it must remember,
      follow up on, or repeat (sent an email and awaits the reply, watches a page, checks
      back on something the user asked about). Work that only reads and that nobody asked
      to follow up on is never a task: return the answer instead.
    - assignee "user": the user asks to put something on their own list ("remind me to
      call the bank", "add milk to my list"). GAIA never runs it; it nudges them when due.

    Every open GAIA task that does not repeat has a next step, enforced in code:
    waiting_on (what it waits for) plus next_check (when GAIA next looks: '4h', '3d', or an
    ISO datetime with the user's offset). Waiting on the user means one question, passed as
    question, with if_no_reply decided now: ask_again, proceed (with default_action) or hold.

    Work about one email thread (waiting on a reply, answering it) passes gmail_thread_id:
    the task runs on the thread's next mail either way, and the thread keeps one open task.

    Splitting GAIA work: create each part with parent_id set to the open top-level GAIA task,
    then set the parent waiting_on "sub_todos" with a backup next_check. Each finished
    subtask wakes the parent; closing the parent closes its open subtasks. A subtask
    reports to its parent, not the user, unless notify is set.

    Search existing tasks first (search_tasks) and update a match instead of creating a twin.
    Never repeat a task id in user-visible text.
    """

UPDATE_TASK = """
    Change a task: its title, details, priority, date, notes, what it waits on, its next check,
    or its notify setting.

    When to use:
    - A run of a GAIA task is still open after its work: set waiting_on and a new next_check.
    - You asked the user something: waiting_on "user" with question and if_no_reply.
    - The user changes one of their to-dos (rename it, move its date).
    - A GAIA task belongs under another open top-level GAIA task: pass parent_id.

    - The user changes the priority of a task, or asks for it to repeat (repeat).
    - A GAIA task's working notes change: pass the whole new notes (get_task shows them).
    - A GAIA task waits on someone outside (a reply, an approval elsewhere): set flags; an
      unblock subscription clears them when the event arrives.

    Never repeat a task id in user-visible text.
    """

COMPLETE_TASK = """
    Mark a task done, with one or two sentences on what was achieved.

    When to use:
    - The goal of a GAIA task is clearly met (the fix is live, the reply arrived and is
      handled, the user confirmed it): close it in the same run, without waiting for the
      user to report it.
    - The user says one of their to-dos is done.

    A repeating task stays open unless stop_repeat is set: one finished run never ends a
    standing schedule. Never repeat a task id in user-visible text.
    """

LIST_EVENT_FIELDS = """
    Show exactly what an app event delivers, before subscribing a task to it.

    Returns the event's matchable fields with types, descriptions and example values, the
    fields that are deliberately not matchable and why, the scope a per-resource event needs,
    and the operators each type accepts. Call it whenever you are about to subscribe a task
    to an event you have not used in this conversation: conditions must name real fields.
    """

SUBSCRIBE_TASK = """
    Make one of GAIA's tasks react when an app event arrives: a reply to an email you sent,
    a calendar event about to start, an issue changing, a row landing in a sheet.

    action decides what the event does. "execute" (the default) runs the task with the
    event in its brief; events inside its cooldown ride the next run together. "notify"
    only tells the user the event landed. "complete" closes the task, for an event that
    itself means it is done (the invoice is marked paid). "unblock" clears the task's
    waiting-on-a-reply or blocked flag, and tells the user when there is none. Only
    execute takes runs_only_when. The task keeps its next check and its schedule: whichever
    comes first wakes it, and closing the task stops it listening.

    Write conditions against real payload fields (list_event_fields shows them). Obvious
    mistakes (a camelCased field, an operator the field's type cannot take, a number sent as
    text) are repaired and reported; anything ambiguous is refused with the fields that exist.
    Per-resource events (github, slack, sheets, notion, linear, asana) need a scope naming the
    resource, e.g. scope={'repos': ['owner/name']}, or they never fire.
    """

UNSUBSCRIBE_TASK = """
    Stop one of GAIA's tasks listening to one app event it subscribed to.

    Use when what it waited for no longer matters but the task stays open. Completing a task
    stops it listening on its own, so do not call this first.
    """

LIST_TASKS = """
    List the user's tasks, GAIA's and their own to-dos, with today's counts on top.

    When to use:
    - The user asks what is on their list, what is due today or this week, what is overdue,
      what they finished, or what GAIA is working on: pick the view.
    - A view narrowed by exact words the user gave ("overdue bills"): add query.

    Each line shows whose it is, when it is due or repeats, its checklist and, for GAIA's,
    what it waits on. query keeps only tasks whose title or details contain those exact
    words; to find a task by what it is about, use search_tasks. Never repeat a task id in
    user-visible text.
    """

SEARCH_TASKS = """
    Find tasks by meaning: "the dentist thing" finds "Book a check-up for the tooth ache".
    Searches titles, details and GAIA's own notes, of open and finished tasks.

    When to use:
    - The user names a task loosely and you need its id for another task tool.
    - Before creating a task: one may already cover it; update that instead of a twin.
    - Before starting work: what earlier tasks already learned about this (people, threads,
      what worked), shown under each match.

    Results are nearest first and always some, so judge from each line whether it is
    really the task meant. Never repeat a task id in user-visible text.
    """

GET_TASK = """
    Show one task in full: its details, checklist items with their ids, the app events it
    listens for, and GAIA's notes, observations and log on it.

    Use before changing a checklist item (it gives the item ids), when the user asks about
    one task, or to read what earlier runs of a GAIA task wrote down.
    """

EDIT_CHECKLIST = """
    Change one item on a task's checklist: add one, rename it, tick it, untick it or remove it.

    The checklist is the small steps inside one task ("milk", "bread" under "Groceries").
    Work GAIA does on its own is a subtask (create_task with parent_id), not a checklist item.
    Every change but add names the item by the id get_task shows.
    """

REOPEN_TASK = """
    Put a done task back on the list, when the user says it is not finished after all.
    """

COMPLETE_TASKS = """
    Tick off several of the user's to-dos at once ("I did all of those").

    For one task, or for GAIA's own work, use complete_task with what was achieved.
    """

DELETE_TASKS = """
    Delete tasks for good, with every subtask under them. Only when the user asks to delete
    or remove them; a finished task is completed, not deleted.
    """
