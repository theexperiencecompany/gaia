"""The prompt for the one call that judges a brief's group headings against the items under them."""

BRIEF_HEADING_PROMPT = """You check the headings of a brief. GAIA grouped the items it placed and wrote a
heading over each group. Judge whether every item under each heading satisfies it.

Each item shows what it is (its title), its state, and exactly one of:
- an action, what the user still has to do: approve, reply, review, retry, read, attend;
- an outcome, where it got to with nothing asked of the user: approved, landed, drafted,
  booked, sent, finished, started (still running), changed, failed.

Judge each heading only against what its items are and their actions and outcomes:
- A heading that says where items got to must be true of each one. "Landed overnight" or "Done"
  fits finished, sent or landed items, never one still waiting on the user's approval or reply,
  and never one only started. "Still running" fits started items only.
- A heading that says the user has something to do ("Waiting on you", "Needs your reply") fits
  only items with an action, and a specific ask ("Replies before Friday") only items that ask it.
  Every item with an action waits on the user, whatever its state: a failed run to retry does.
- A heading that names a subject ("Money", "Hiring") fits only items about that subject.
- A heading that says how the user can take the items ("Ready when you are", "Worth a look",
  "For later", "Ready to review") fits any item that can be taken that way.
Tone, register, wording and style never count, and neither does anything the group leaves out.
When the heading can be said truthfully of every item under it, it fits.

## The groups
{groups}

Answer one verdict per group, by its block number: fits, the ids of the items it is not true of
(empty when it fits), and why in a few words."""
