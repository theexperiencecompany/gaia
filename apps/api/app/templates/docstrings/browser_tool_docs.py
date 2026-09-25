"""Docstrings for the browser-automation tools."""

BROWSER_TASK = """
Autonomously operate a real web browser to complete a task the user asked for
that cannot be done through an API or integration, e.g. booking, filling a
multi-step web form, gathering data from a site behind interactions, or
completing a checkout flow.

Use this ONLY when the task genuinely requires driving a website (clicking,
typing, navigating). Prefer web_search / fetch_webpages for reading, and prefer
a dedicated integration (Gmail, Calendar, etc.) when one exists.

The browser runs on isolated, self-hosted infrastructure. The user sees every
step live (goal + screenshot).

This tool STARTS the run and returns immediately. It does NOT return a result.
The run continues in the background even after your turn ends. When you need the
outcome in this turn, call wait_for_browser_task() and report what IT returns;
if you finish the turn without joining, the result is delivered to the user as a
follow-up message and you must not claim an outcome you never saw.

This tool CAN handle logins and CAPTCHAs: it hands the step to the user, it does
not fail. When it reaches a login/password, a one-time code / 2FA, a payment
confirmation, an irreversible action, or a CAPTCHA/verification wall, it pauses
and gives the user a link to a LIVE view of the browser where they take control
and complete that one step themselves; the task then continues automatically
toward the goal. So:
  * Pass the user's FULL goal, including "log in", "sign in to my account", or
    "check my inbox". Do NOT downgrade it to "just open the login page" or stop
    early because a login is involved. Let the handoff happen.
  * NEVER ask the user to send a password, OTP, or card number in chat; the live
    handoff is exactly how they provide those, directly in the browser. When the
    user has ALREADY given credentials in the conversation, pass them in `secrets`
    and write <secret>name</secret> in the task where each is used; the run then
    signs in itself, and the values never reach any model.
  * Do NOT tell the user you "can't hold the browser open" or "have no live
    handoff". You do; the live-view link is delivered automatically at the
    handoff step.
For Gmail/Google specifically, prefer the Gmail integration (OAuth): Google
blocks automated logins, so the browser is the wrong tool for reading mail.

Each call is a fresh browser: nothing typed, selected or navigated in an
earlier call is still there. A second call to "fix one field" or "also read X"
starts over from a blank page, so a task must carry everything you need from
that page in one go.

Args:
    task (str): A clear, self-contained description of what to accomplish in the
        browser, including the target site and any specifics the user gave
        (dates, names, quantities, preferences). Keep it to the GOAL in one or two
        sentences; do not write step-by-step instructions, and do not invent
        requirements the user did not ask for (saving files, reporting byte sizes,
        etc.). Screenshots are shown to the user automatically. Never write a secret's
        value in the task: put it in `secrets` and write <secret>name</secret>.
        The browser sees ONLY this text: not the conversation, not your memory. Put
        in every value the page will ask for that you know (names, email, address,
        dates, quantities, the exact item), and if a value it cannot do without is
        unknown, ask the user before starting; the browser never invents one.
        Describe a control the way the user did (its position, the words they used);
        never invent a label for it, a wrong label sends the browser to the wrong
        control and it skips the step.
    start_url (str, optional): A URL to open first, if the user named a site.
    secrets (dict, optional): Credentials the user gave for this task, by a short
        name ({"password": "..."}); the task refers to each as <secret>name</secret>.

Returns:
    str: Confirmation that the run has STARTED, with its job id. Never a result.
"""

WAIT_FOR_BROWSER_TASK = """
Wait for this conversation's background browser task and return its outcome.

Call this after browser_task when you need the run's answer in this turn. It
returns the run's own guidance text: what it accomplished, that the user stopped
it, or why it could not be finished. Report that and stop; never re-run the
browser on the strength of it.

Returns immediately when no browser task is running in this conversation. If the
run outlasts the wait, it says so: the result is then delivered to the user as a
follow-up message, so do not claim an outcome and do not start the task again.

It can also come back saying the browser is STUCK and asking you for one
instruction, with the page it is on. That is not a result: answer it with
guide_browser_task(...) and then call this again.

Args:
    timeout (int, optional): Maximum seconds to wait. Default 600.

Returns:
    str: The run's outcome guidance, a request for one instruction, or a note
        that it is still running.
"""

GUIDE_BROWSER_TASK = """
Answer a stuck browser task with ONE concrete instruction, so it can continue.

Call this only when wait_for_browser_task() came back saying the browser is
stuck and asked for guidance, then call wait_for_browser_task() again.

Give one next step the browser operator can carry out on the page it described:
what to click, what to type, where to navigate, or the fact it is missing. Not a
plan, not several steps. Draw only on the user's request, this conversation and
your memory; never invent a value, an address, a date or an account detail, and
never pass a password, a one-time code or a card number (the run hands those to
the user itself through a live view).

Prefer a different route over repeating what already failed: the request lists
what the run just tried and whether the page moved at all. If there is no honest
way forward, say so with give_up=True rather than sending a guess.

Args:
    instruction (str): The single concrete next step. Required unless giving up.
    give_up (bool, optional): True when the task cannot honestly be done.
    reason (str, optional): Why it cannot be done. Only with give_up.

Returns:
    str: Confirmation that the instruction reached the run, or that nothing was
        waiting for one.
"""
