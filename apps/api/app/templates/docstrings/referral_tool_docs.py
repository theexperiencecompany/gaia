"""Docstrings for the referral LangChain tools: sharing GAIA with friends."""

GET_REFERRAL_LINK = """
Get the user's personal invite link, the gift their friends get, and a ready-to-share message.

Friends who join through the link get GAIA at an intro price; the user gets a
free month every time one of them pays. Only users with an active subscription
have a link; the tool says so when this one does not.

USE THIS WHEN THE USER ASKS:
• "Give me my invite link" / "How do I share GAIA?"
• "I want to invite a friend" (and they did not give an email address)
• "What do my friends get?"

Hand over the share message exactly as returned: it carries the live price and
the link, and the user can paste or forward it anywhere.

DO NOT:
• Bring this up unprompted, or pitch sharing inside an unrelated reply
• Quote a price you did not read from this tool's output
• Say "referral", "reward" or "conversion" to the user; say friends, gift, free month

Returns:
    The link, the friend's gift in money, and the message to share
"""

GET_REFERRAL_STATUS = """
Read how the user's sharing is going: free months earned, friends who joined, next bill.

Returns the free months earned (already applied to the billing date, or saved
while the user has no active subscription), every friend who joined through
their link and whether that friend has paid yet, and the user's next billing
date after any free months.

USE THIS WHEN THE USER ASKS:
• "How many free months do I have?" / "Did anyone use my link?"
• "When is my next bill?" after mentioning friends or free months

Never state a count or a date you did not read here.

Returns:
    Free months, friends with their status, and the next billing date
"""

SUGGEST_INVITEES = """
Suggest people the user might invite: the ones they meet and email most.

Ranked from the last 90 days of the user's connected Google Calendar and Gmail,
with the reason for each ("met 6 times", "emailed 9 times"). Nothing about
these contacts is stored. People already invited, people who opted out, and
existing GAIA users are left out. Empty when neither Google account is
connected; offer to connect one only if the user wants suggestions.

USE THIS ONLY WHEN THE USER ASKS who to invite. Never volunteer it.

Returns:
    Up to 20 people, each with name, email and why they are suggested
"""

SEND_REFERRAL_INVITE = """
Email an invite to friends the user named, with their gift and the user's link.

It goes from the user's Gmail when it is connected, else from GAIA under the
user's name with replies going to them. Each address is judged on its own: a
friend this user already invited, a friend who opted out of invites, or the
user's own address is skipped and reported. The user approves the send first.

On a chat platform (WhatsApp, Telegram, iMessage, Slack, Discord) nothing is
emailed: the tool returns a message the user can forward to their friend
themselves. Relay that message exactly as returned.

USE THIS WHEN the user asks to invite specific people by email address. If they
named someone without an address, ask for it, or find it with the user's own
tools when they asked you to; never guess an address.

Args:
    emails: the friends' email addresses, as the user gave or confirmed them
    friend_name: the friend's first name, used in the forwardable message on a chat platform

Returns:
    One line per address saying whether it was sent, or the message to forward
"""
