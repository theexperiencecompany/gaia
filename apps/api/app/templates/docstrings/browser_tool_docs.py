"""Docstrings for the browser-automation tool."""

BROWSER_TASK = """
Autonomously operate a real web browser to complete a task the user asked for
that cannot be done through an API or integration — e.g. booking, filling a
multi-step web form, gathering data from a site behind interactions, or
completing a checkout flow.

Use this ONLY when the task genuinely requires driving a website (clicking,
typing, navigating). Prefer web_search / fetch_webpages for reading, and prefer
a dedicated integration (Gmail, Calendar, etc.) when one exists.

The browser runs on isolated, self-hosted infrastructure. The user sees every
step live (goal + screenshot).

This tool CAN handle logins and CAPTCHAs — it hands the step to the user, it does
not fail. When it reaches a login/password, a one-time code / 2FA, a payment
confirmation, an irreversible action, or a CAPTCHA/verification wall, it pauses
and gives the user a link to a LIVE view of the browser where they take control
and complete that one step themselves; the task then continues automatically
toward the goal. So:
  * Pass the user's FULL goal, including "log in", "sign in to my account", or
    "check my inbox" — do NOT downgrade it to "just open the login page" or stop
    early because a login is involved. Let the handoff happen.
  * NEVER ask the user to send a password, OTP, or card number in chat — the live
    handoff is exactly how they provide those, directly in the browser.
  * Do NOT tell the user you "can't hold the browser open" or "have no live
    handoff" — you do; the live-view link is delivered automatically at the
    handoff step.
For Gmail/Google specifically, prefer the Gmail integration (OAuth) — Google
blocks automated logins, so the browser is the wrong tool for reading mail.

Each call is a fresh browser: nothing typed, selected or navigated in an
earlier call is still there. A second call to "fix one field" or "also read X"
starts over from a blank page, so a task must carry everything you need from
that page in one go.

Args:
    task (str): A clear, self-contained description of what to accomplish in the
        browser, including the target site and any specifics the user gave
        (dates, names, quantities, preferences). Keep it to the GOAL in one or two
        sentences — do not write step-by-step instructions, and do not invent
        requirements the user did not ask for (saving files, reporting byte sizes,
        etc.). Screenshots are shown to the user automatically. Do not include secrets.
    start_url (str, optional): A URL to open first, if the user named a site.

Returns:
    str: A summary of the outcome (what was accomplished or why it stopped).
"""
