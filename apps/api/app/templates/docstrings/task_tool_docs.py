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

    Search existing tasks first (list_tasks) and update a match instead of creating a twin.
    Never repeat a task id in user-visible text.
    """

UPDATE_TASK = """
    Change a task: its title, details, date, what it waits on, its next check, or its notify setting.

    When to use:
    - A run of a GAIA task is still open after its work: set waiting_on and a new next_check.
    - You asked the user something: waiting_on "user" with question and if_no_reply.
    - The user changes one of their to-dos (rename it, move its date).

    The working notes are files: edit /workspace/gaia-tasks/<folder>/canvas.md with the file
    tools, not with this tool. Never repeat a task id in user-visible text.
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
