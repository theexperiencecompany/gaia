"""Docstrings for subscription/billing LangChain tools."""

GET_SUBSCRIPTION_DETAILS = """
Read the user's real subscription state from the billing system.

Returns their plan (Free or Pro), whether the subscription is active, what they
pay, the billing cycle, when it renews, whether it is set to cancel at the end of
the period, and their recent charges.

USE THIS WHEN THE USER ASKS:
• "Am I on Pro?" / "Am I a paid user?" / "What plan am I on?"
• "How much am I paying?" / "When does my subscription renew?"
• "Did my payment go through?" / "Show me my billing history"
• Anything where you would otherwise guess at their plan or price

NEVER state a plan, price, renewal date, or charge you did not read from this
tool. Guessing about someone's money is how you tell a paying customer they are
on the free plan.

A free user has no billing history: that is a normal result, not an error.

Returns:
    A readable summary of the plan, billing state, and recent charges
"""

CREATE_UPGRADE_LINK = """
Create a ready-to-pay checkout link that upgrades this user to GAIA Pro.

The link is personalised to the user, so their subscription is attributed to
their account the moment they pay. Give it to them directly: it works in chat,
on WhatsApp, Telegram, Slack and Discord, and does not require them to find the
web app and log in first.

USE THIS WHEN:
• The user asks to upgrade, subscribe, go Pro, or pay
• The user hit a usage limit and wants more capacity
• You are explaining that a feature needs Pro and they want it

BILLING CYCLE:
• "monthly" (default): billed every month
• "yearly": billed once a year, cheaper per month

Ask which they want only if they bring it up; otherwise send the monthly link and
mention yearly is cheaper if they prefer it.

DO NOT:
• Call this for a user who is already on Pro (the tool will tell you so); relay
  that instead of sending them a second checkout
• Invent a price. Read it from this tool's own output, which carries the live
  price and feature list; never quote a number you did not see
• Push the upgrade repeatedly. Offer it once, in context, and move on

Args:
    billing_cycle: "monthly" or "yearly"

Returns:
    The checkout link and what it costs, or a note that they are already on Pro
"""
