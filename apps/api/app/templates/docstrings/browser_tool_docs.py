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
step live (goal + screenshot). Before anything sensitive — submitting a payment,
entering credentials or a one-time code, or any irreversible action — the agent
pauses and waits for the user's explicit approval; it never enters card details
or passwords without confirmation.

Args:
    task (str): A clear, self-contained description of what to accomplish in the
        browser, including the target site and any specifics the user gave
        (dates, names, quantities, preferences). Do not include secrets.
    start_url (str, optional): A URL to open first, if the user named a site.

Returns:
    str: A summary of the outcome (what was accomplished or why it stopped).
"""
