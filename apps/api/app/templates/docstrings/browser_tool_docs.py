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

In a live conversation this tool STARTS the run and returns at once, without a
result: the run goes on in the background, and its result arrives in your inbox
as a <browser_result> message when it ends (waking you if you have finished).
Never claim an outcome before that message. In a workflow or scheduled run it
instead returns only once the run has ended, with its result. Call it once per
turn: never a second time to retry or to also check something else. Never claim
the browser is unavailable, busy or rate limited unless a browser tool result
said so.

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
    start_url (str, optional): The page to open first. Pass it whenever the task
        names a site or page: the run starts there, with the user's saved login for
        that site. Without it the run starts on a blank page.
    secrets (dict, optional): Credentials the user gave for this task, by a short
        name, each with the site it belongs to:
        {"password": {"value": "...", "site": "github.com"}}. A credential is typed
        only on its own site (and its subdomains), never elsewhere. The task refers
        to each as <secret>name</secret>.

Returns:
    str: Confirmation that the run has STARTED, with its job id; in a workflow or
        scheduled run, how the run ended.
"""
