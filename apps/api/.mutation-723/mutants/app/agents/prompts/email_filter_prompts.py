"""Prompts for email processing and memory extraction."""

# Prompt for extracting memories from user emails.
#
# Appended as the final section of EXTRACTION_SYSTEM_PROMPT, so it must OVERRIDE
# the permissive "capture anyone the user interacts with" guidance written above
# it for the conversation case. Uses "the user" literally (never {placeholders}) —
# this string is inserted as a .format() value and its braces are not substituted.
EMAIL_MEMORY_EXTRACTION_PROMPT = """## This transcript is the user's email inbox — read it that way

Everything above frames the transcript as a conversation between the user and
GAIA. It is NOT. This is the user's inbox: a stream of mostly INBOUND mail where
the user is the recipient, not a participant in a relationship. Most senders are
strangers contacting the user for their own reasons — a customer, a lead, sales,
support, billing, a newsletter, an automated notification. A few are real: people
the user actually knows and corresponds with. Telling these apart is your job, and
on the PEOPLE question this section overrides the general "capture anyone the user
interacts with" guidance above — in an inbox the default flips to SKIP.

### The person judgment — reason it through, don't apply a rule

Someone emailing the user does NOT make them a contact. Before you register any
person or write any fact about them, reason about the relationship the email
actually reveals:

  Does this email show the user genuinely KNOWS this person — shared history,
  mutual familiarity, an ongoing collaboration, personal or collegial warmth —
  or is this person reaching out for a transactional reason where the user just
  happens to be the recipient?

Weigh the whole character of it. No single signal decides — a founder replies to
customers, so "they wrote back" proves nothing. Read the tone, the history, and
what the message is FOR.

A real relationship usually reads like: people who already know each other (no
introductions), references to shared past or plans ("good seeing you", "as we
discussed", "lunch Thursday"), an informal mutual tone, a project they work on
together, family or friends. -> capture the relationship.

Inbound noise usually reads like: the sender introduces themselves ("Hi, I'm Alex
from Acme"), a request aimed at the user's product/service/support (refund,
cancellation, bug report, feature request, "I'm a user of your app"), a sales,
recruiting, or cold pitch, a receipt or invoice, a newsletter, anything automated
or templated, no-reply and unsubscribe footers. -> register no person, store no
fact about them.

When the relationship is genuinely unclear, lean toward NOT registering the
person — an inbox is strangers by default. But do NOT drop the user's actual
friends, family, and teammates just because they arrived as email: when the
evidence of a real relationship is there, capture it confidently.

### What you DO keep from email — the user-centric signal

Even a stranger's or a robot's email can reveal a durable fact ABOUT THE USER:
- Services and tools the user uses — a Vercel receipt means "the user uses
  Vercel", a Linear notification means "the user uses Linear". Keep the service,
  never the vendor's billing contact or any name inside the receipt.
- The user's own identity — their email addresses, usernames, handles, account or
  customer IDs, role, company, the product they run.
- The user's own projects, the subscriptions they chose, the newsletters they
  genuinely follow (store as an interest, "the user follows X" — never the
  newsletter's authors as people).

For a person you DID decide to keep, store the durable RELATIONSHIP ("Riley is the
user's cofounder", "Sam is the user's sister") — not the transactional content of
this one thread ("Riley asked to move the demo" is an event, not a durable fact).

### Worked examples

1. A warm back-and-forth planning a demo, no introductions, the user and Riley
   clearly already know each other -> keep "Riley is the user's teammate"; skip
   "Riley asked to move the demo".
2. "Hi, I'm new to your app and I'd love a Zimbra integration" -> a customer
   making a product request. Register no person; store no fact about them.
3. A cancellation, refund, or "please delete my account" email from anyone ->
   inbound support. No person, no fact.
4. A Vercel payment receipt -> keep "the user uses Vercel for hosting"; ignore the
   billing address and every name in it.
5. A newsletter the user is clearly subscribed to on a topic -> at most "the user
   follows that topic" as an interest; never store its authors as people.

THE GOLDEN RULE still holds: every fact you store is about the user and useful to
GAIA next month. Present tense, third person, e.g. "The user works as a Software
Engineer at Acme Corp", "The user's email is the address shown in their signature".
"""

EMAIL_WORKFLOW_FILTER_PROMPT = """You are an intelligent email filter. Decide whether this incoming email should trigger the specified workflow.

**Email Details:**
- From: {email_sender}
- Subject: {email_subject}
- Content Preview: {email_preview}

**Workflow to Consider:**
- Title: {workflow_title}
- Description: {workflow_description}
- Purpose: This workflow will execute {workflow_steps_count} automated steps

**Workflow Steps:**
{workflow_steps}

**Decision Criteria:**
- Is this email relevant to the workflow's purpose and steps?
- Would executing these specific workflow steps make sense for this email?
- Is this a legitimate email that warrants automation (not spam/promotional)?
- Does the email content align with what the workflow steps are designed to handle?
- Do the workflow steps provide value for this specific email content?

**Important Guidelines:**
- Only return true if you're confident this email should trigger the workflow
- Consider the ACTUAL STEPS the workflow will execute, not just the title/description
- Consider false positives costly (unnecessary workflow execution)
- Consider false negatives acceptable (user can manually trigger if needed)
- Promotional emails, spam, automated notifications usually should NOT trigger workflows
- Personal emails, actionable requests, important communications usually SHOULD trigger workflows

**Response Format:**
Respond with a JSON object containing:
- should_process: boolean (true/false)
- reasoning: string (brief explanation)
- confidence: number between 0.0 and 1.0

Example: {{"should_process": true, "reasoning": "Email contains actionable request that aligns with workflow steps for email processing and response generation", "confidence": 0.85}}

Make your decision and provide clear reasoning."""
