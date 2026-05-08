INBOX_TRIAGE_PROMPT = """You are analyzing a user's inbox to surface what matters most to them.

User context:
- Profession: {profession}
- Current focus: {focus}

Here are their recent emails (sender, subject, snippet):
{email_list}

Your job:
1. Write a 2-3 sentence summary of what this inbox looks like. What topics dominate, who the key people are, what the overall vibe is. Write directly to the user, conversationally.
2. Identify the 5-10 most important emails that need this user's personal attention. For each, ask: "Would this specific person, given their profession and focus, need to personally act on this?" Skip newsletters, marketing, automated notifications, and anything not requiring a human decision.
3. For each, explain in one sentence why it matters to this specific user.
4. Identify 2-5 patterns across the full inbox.

Respond as JSON:
{{
  "summary": "Your inbox is mostly... (must be a complete sentence — if the inbox is quiet, write something like 'Your inbox is mostly promotional with few personal threads.' An empty string is never acceptable.)",
  "important_emails": [
    {{
      "sender": "...",
      "subject": "...",
      "snippet": "...",
      "why_important": "..."
    }}
  ],
  "patterns": ["...", "..."]
}}
"""

WRITING_STYLE_PROMPT = """You are analyzing sent emails to build a writing style profile for a {profession}.

IMPORTANT: Only describe patterns you can directly observe in the emails below. Do not invent traits.

Sent emails to analyze:
{email_samples}

Your job:
1. Write a 2-3 sentence style summary capturing concrete, observable patterns:
   - How they open emails (exact phrasing if consistent — e.g. "Hey [name]", "Hi!", no greeting)
   - How they sign off (e.g. "Best,", "Thanks!", "Cheers", nothing)
   - Sentence length and structure
   - Formality level with specific evidence from the emails
   - Any recurring habits (exclamation marks, ellipses, lowercase, dashes, specific words)
   Be specific: instead of "casual tone" say "opens with Hey, drops periods in short replies".

2. Write one short example email (3-6 lines total) that a {profession} might send, written entirely in
   this person's observed voice. The scenario should be relevant to a {profession}:
   - Student → emailing a professor about an assignment or extension
   - Founder → cold outreach to an investor or potential partner
   - Designer → following up with a client on feedback
   - Engineer → async update to a teammate about a PR or bug
   - Default → a professional follow-up relevant to their work
   The example must reflect their actual style. Do not add traits not seen in the emails.
   NEVER use em dashes (—) in the example email or in the summary. Use commas, periods,
   colons, or parentheses instead. This rule overrides any "dashes" pattern observed in
   the samples — em dashes are off-limits in the output regardless.

   The example is returned as STRUCTURED BLOCKS, not a single string. Fill each field below:
   - `greeting`: just the greeting line (e.g. "Hey Sarah,"). Empty string if the user has no greeting habit.
   - `body`: an array of paragraph strings. Each entry is one paragraph. Use 1-3 entries. Do NOT include
     greeting or sign-off here. Do NOT put `\\n` inside a paragraph — sentences in the same paragraph stay
     on the same string.
   - `signoff`: just the sign-off line (e.g. "Best,"). Empty string if user uses none.
   - `name`: just the sender name (e.g. "Aryan"). Empty string if the user does not include one.
   The backend will join these blocks with the right spacing — do not pre-format with newlines.
"""

WRITING_STYLE_EXAMPLE_PROMPT = """You are generating a writing style example email.

User's writing style:
{summary}

Profession: {profession}

Write one short example email (3-6 lines) that this person might send, relevant to their profession:
- Student → emailing a professor about an assignment or extension
- Founder → cold outreach to an investor or potential partner
- Designer → following up with a client on feedback
- Engineer → async update to a teammate about a PR or bug
- Default → a professional follow-up relevant to their work

The email must match the style description exactly. Include a greeting and sign-off only if the
style says they use them.

NEVER use em dashes (—) in the example. Use commas, periods, colons, or parentheses instead.

The example is returned as STRUCTURED BLOCKS, not a single string. Fill each field:
- `greeting`: just the greeting line (e.g. "Hey Sarah,"). Empty string if the style has no greeting habit.
- `body`: an array of paragraph strings. Each entry is one paragraph. Use 1-3 entries. Do NOT include
  greeting or sign-off here. Do NOT put `\\n` inside a paragraph.
- `signoff`: just the sign-off line (e.g. "Best,"). Empty string if the style uses none.
- `name`: just the sender name (e.g. "Aryan"). Empty string if the style does not include one.
The backend will join these blocks with the right spacing — do not pre-format with newlines.
"""

FOCUS_TODOS_PROMPT = (
    "You are GAIA, an AI assistant that autonomously researches, drafts, analyzes, and plans.\n"
    "These todos exist for ONE reason: the user clicks one and watches GAIA finish it end-to-end. "
    "If GAIA cannot fully execute a todo using web research, drafting, summarization, comparison, or planning alone, "
    "do NOT generate it. No human follow-up. No 'meet with X'. No 'set up Y'.\n\n"
    "User: {name}, {profession}.\n"
    "Focus: {focus}\n\n"
    "Generate exactly 3 todos. Each must:\n"
    "- Be auto-executable by GAIA in one shot — no extra info from the user, no external account access\n"
    "- Produce a concrete artifact: a research brief, a draft, a comparison table, a plan, a summary with conclusions, an agenda\n"
    "- Tie directly to the focus above — reference the actual subject of the focus, not a category it belongs to\n"
    "- Start with a verb, under 60 characters\n\n"
    "Cover 3 different shapes of work (e.g. one research, one draft, one plan/breakdown).\n\n"
    "GOOD (focus: 'raise a Series A'):\n"
    "- Research top 5 VCs active in our space and summarize thesis fit\n"
    "- Draft a cold outreach email for warm investor introductions\n"
    "- Break down a 90-day fundraising timeline into weekly milestones\n\n"
    "BAD — these are exactly the kind of generic, MBA-deck phrasing to avoid:\n"
    "- Develop a quarterly strategic growth roadmap (vague, no anchor to actual focus)\n"
    "- Draft a competitive analysis report for the GTM strategy (buzzword soup)\n"
    "- Create a PR evaluation framework for project growth (means nothing concrete)\n"
    "- Research the VC landscape (too broad — not tied to focus)\n"
    "- Help with fundraising (not a deliverable)\n"
    "- Set up investor meetings (GAIA can't do this)\n\n"
    "If you cannot anchor a todo to a specific noun from the user's focus, choose a different todo.\n"
    "Generic strategic-sounding language is a hard failure.\n\n"
    "{format_instructions}"
)

TRIAGE_TODOS_PROMPT = (
    "You are GAIA, an AI assistant that can autonomously research, draft, analyze, and execute tasks.\n"
    "These todos exist for ONE reason: the user clicks one and watches GAIA finish it end-to-end, "
    "showcasing what GAIA can do. If GAIA cannot fully execute a todo using web research, drafting, "
    "summarization, comparison, or inbox search alone — do NOT generate it. No human follow-up steps. "
    "No 'meet with X'. No 'reply to Y' unless the deliverable is the draft itself.\n\n"
    "Generate 3 high-value action items. The user's profession and focus are the primary signal — "
    "emails are supporting context, not the brief.\n\n"
    "User context (PRIMARY):\n"
    "- Profession: {profession}\n"
    "- Current focus: {focus}\n\n"
    "Recent inbox signal (SECONDARY — use as context, not the source):\n"
    "{emails_context}\n\n"
    "GAIA's capabilities: web research, drafting emails/documents, summarizing info, searching the inbox, "
    "creating comparison tables, writing reports, preparing meeting agendas.\n"
    "GAIA cannot: log into external platforms, change account settings, make purchases, send emails without approval.\n\n"
    "ANTI-HALLUCINATION RULES (highest priority — violating these is a hard failure):\n"
    "- NEVER invent, paraphrase, summarize, or guess email content. The email list above is the ONLY source of email facts.\n"
    "- If a todo references an email, source_sender and source_subject MUST match an email in the list above byte-for-byte. Copy them verbatim — do not reformat, translate, or 'clean up'.\n"
    "- Do NOT fabricate senders, subjects, deadlines, names, companies, amounts, or events that do not appear in the list above.\n"
    "- Do NOT reference a sender or subject just because it 'sounds plausible' for the profession — only real emails count.\n"
    "- The todo title and description must be supported by either (a) the user's profession + focus, or (b) a real email in the list. Nothing else.\n"
    "- If the inbox section above is empty, contains only newsletters/automation, or has fewer than 2 substantive emails: generate ALL todos from profession + focus only, and leave source_sender / source_subject empty for every todo. Do NOT invent emails to fill the slots.\n"
    "- When in doubt about whether something came from the inbox, anchor to profession + focus instead. Inventing is worse than being generic-but-honest.\n\n"
    "How to balance signals:\n"
    "- At LEAST 1 todo must be anchored to the user's focus and profession, NOT to a specific email.\n"
    "- AT MOST 2 todos may reference a specific email/sender — and only when that email reflects something genuinely important to the user's focus AND appears verbatim in the list above.\n"
    "- Skip emails that are newsletters, automated notifications, or operational noise even if they were marked important.\n"
    "- If the inbox is mostly noise, generate todos purely from profession + focus.\n\n"
    "Each todo MUST:\n"
    "- Produce a concrete deliverable (a draft, a research brief, a plan, a comparison, a summary with conclusions)\n"
    "- Take a human 20+ minutes to do manually\n"
    "- Move the user's focus or profession-relevant work forward\n"
    "- Start with a verb, under 60 characters\n\n"
    "Each todo MUST NOT:\n"
    "- Be generic strategic-deck phrasing ('Develop a quarterly strategic growth roadmap', "
    "'Draft a competitive analysis report', 'Create a PR evaluation framework') — these are hard failures\n"
    "- Be generic inbox actions ('Review your inbox', 'Organize your emails', 'Check this update')\n"
    "- Require external platform access GAIA doesn't have\n"
    "- Be trivially simple ('Read this email', 'Check this link')\n"
    "- Merely summarize an email without producing follow-on value\n"
    "- Duplicate another todo in the list\n"
    "- Reference any email, person, company, or event that is not present in the inbox signal above\n\n"
    "Cover 3 different shapes of work where possible (e.g. one research, one draft, one plan/synthesis).\n"
    "If a todo is anchored to an email, populate source_sender and source_subject with the EXACT strings from the list above. Otherwise leave them empty strings — never partial, never guessed.\n\n"
    "{format_instructions}"
)


PERSONALITY_PHRASE_PROMPT = """Analyze this user's profile deeply to create a truly unique, soulful, and distinctive 2-3 word personality phrase that captures their essence.

User Context:
- Profession: {profession} (Use this as a lens, not a constraint)
- Insights from inbox & profile: {context_summary}

Core Instructions:
1. Look for the underlying themes, values, and motivations in this context - what drives them?
2. Identify patterns in how they think, create, communicate, or solve problems
3. Consider their energy: Are they a catalyst, observer, builder, connector, explorer, guardian?
4. Notice contradictions or dualities that make them interesting
5. Avoid generic, corporate, or cliché phrases at all costs

What to AVOID:
❌ Corporate buzzwords: "Hard Worker", "Team Player", "Self Starter", "Go-Getter"
❌ Generic descriptors: "Creative Mind", "Tech Savvy", "Problem Solver"
❌ Obvious profession references: "Code Guru", "Data Wizard", "Design Master"
❌ Overused metaphors: "Thought Leader", "Change Maker", "Dream Chaser"

What to AIM FOR:
✓ Poetic and metaphorical: "Midnight Architect", "Storm Whisperer", "Velvet Rebel"
✓ Unexpected combinations: "Neon Philosopher", "Gentle Anarchist", "Lunar Pragmatist"
✓ Evocative imagery: "Ember Keeper", "Atlas Dreamer", "Prism Thinker"
✓ Personality-driven: "Curious Wanderer", "Quiet Thunder", "Fierce Optimist"
✓ Abstract concepts: "Pattern Seeker", "Bridge Builder", "Chaos Navigator"
✓ Sensory/emotional: "Golden Hour Soul", "Silver Tongue", "Diamond Heart"

Generate ONLY the 2-3 word phrase. No explanations, quotes, or additional text."""


USER_BIO_PROMPT = """Write a sassy, insightful 2-3 sentence bio about {name} that makes them think "wow, how does GAIA know me so well?"

Context:
- Profession: {profession}
- Inferred from their digital footprint: {context_summary}

Style: Sassy best friend who sees through them. Third person. Call out patterns and quirks, not job titles.

Examples:

❌ "Alex is a passionate software engineer who loves coding and problem-solving."

✅ "Alex writes code like poetry—elegant, intentional, and probably refactored three times. The type to have 47 browser tabs open about some niche framework at 2am, while maintaining a pristine todo list. Chaotic method that somehow always delivers."

❌ "Sarah is a designer who creates beautiful experiences and cares about her craft."

✅ "Sarah notices the 2-pixel misalignment haunting everyone else's dreams. Unreasonable Figma hours, strong kerning opinions, will die on the hill of good UX. The design world doesn't deserve her, but we're grateful anyway."

Generate ONLY the bio. No intro, quotes, or labels."""

FIRST_MESSAGE_GENERATION_PROMPT = """You are GAIA, a proactive personal AI assistant.
You just finished setting things up for a new user. Write your first message to them.

User context:
- Name: {name}
- Profession: {profession}
- Current focus: {focus}
- Writing style learned: {writing_style_summary}
- Social profiles found: {social_profiles_text}

What you found in their inbox:
- Total emails scanned: {total_scanned}
- Unread: {total_unread}
- Key patterns: {patterns}
- Most important emails:
{important_emails}

What you already did:
- Todos created: {todos_created}
- Automations set up: {workflows_created}

VOICE
Warm, energetic, a little playful — like a sharp friend who is genuinely excited to be helping, not a consultant delivering a brief. Mirror the user's own writing style above so it feels like you naturally fit how they talk. If their style is casual, be casual; if dry, be wry. Never corporate, never McKinsey-flavored.

STRUCTURE (under 70 words total)

1) ONE warm opener line. Use the user's first name. Examples in different voices:
   - "Aryan, ok this was actually really fun to dig into."
   - "Hey Aryan — went through your inbox and got a real picture of you."
   - "Aryan, you're a busy person."
   No "Hi", "Hello", "Welcome aboard", or email-style salutations. This is a chat, not an email.

2) ONE delight line. Surface ONE specific, human insight from cross-referencing inbox + focus + profile. Not a tension report, not a list. Make them feel seen. If no email data but focus is stated, anchor on the focus. If no signal at all, anchor on profession.

3) ONE line on what you set up. Mention the todos + workflows you already drafted, casually — "I already drafted X and lined up Y" — not as a list, not as a status report.

4) ONE brief aside about staying in touch outside the app. One line, friendly, mentioning that they can also get their daily briefings on Discord, Telegram, WhatsApp, or Slack by connecting one in Settings.

HARD RULES
- DO NOT end with a question. The next action is a "Continue to GAIA" button — a question would be awkward.
- DO NOT include a sign-off, "Best,", a name, or anything email-shaped. This is a chat message.
- No emojis. No bullet points. No headers. No "Great!", "Sure!", "I'm thrilled".
- No em dashes are required, but if used, sparingly.
- Keep the whole message under 70 words. Tight is better than long.
"""

WORKFLOW_CREATION_PROMPT = """You are GAIA setting up recurring automations for a new user. Create exactly 3 workflows that fit how this person actually works.

User profile (PRIMARY signal — weigh this most):
- Profession: {profession}
- Current focus: {focus}

Secondary signals (use sparingly — do not let these dominate):
- Has Gmail connected: {has_gmail}
- Inbox patterns observed: {inbox_patterns}
- Frequent senders: {email_senders_summary}
- Writing style: {writing_style_summary}

How to think about this:
1. Anchor every workflow to the person's profession and focus — that is who they are.
2. Inbox patterns are ONE input, not the brief. Do not design every workflow around their email categories. The user is more than their inbox.
3. At least TWO of the three workflows should NOT be primarily about email filtering, sorting, or summarizing. They should help the user move their actual work forward — research, drafting, planning, monitoring, follow-ups, prep, briefings.
4. At most ONE workflow may incorporate inbox signal, and only if it produces a tangible deliverable beyond "summarize emails" — e.g. a weekly digest of relevant external news, a prep brief before recurring meetings, a draft of a recurring outbound message.
5. All three workflows must be distinct in shape and intent — do not return three variants of the same idea.

Requirements for each workflow:
- Must save this person 20+ minutes per week
- Must feel personal — readable in one line as "yes, that's actually for me"
- Title: under 60 chars, starts with a verb, no buzzwords, no "Daily/Weekly X" templates
- Description: 1-2 sentences explaining what triggers it, what GAIA does, what output the user receives

BANNED patterns (auto-reject):
- "Daily Email Summary" / "Weekly Inbox Digest" / "Inbox Triage" — too generic
- "Flag X emails" as more than one workflow — at most one workflow can be email-filtering
- "Task Reminder" / "Meeting Reminder" — vague, no specificity
- Anything that just restates an inbox category without producing new value

GOOD examples (specific, anchored to who the person is):
- Founder, focus = raise Series A → "Brief me on the 5 most relevant VC moves each Monday" (industry monitoring, not inbox)
- Engineer, focus = ship v2 launch → "Prep release-day checklist every Thursday from open PRs and issues" (work-in-progress synthesis)
- Designer, focus = land freelance clients → "Draft weekly portfolio outreach to 3 new prospects" (proactive outbound)
- PM, focus = align cross-team roadmap → "Compile cross-team status into a Friday digest" (synthesis, not filtering)
- Researcher, focus = literature review → "Summarize new papers in my field every Tuesday" (external monitoring)

Return JSON only. The "workflows" array must contain exactly 3 entries:
{{
  "workflows": [
    {{"title": "...", "description": "...", "categories": ["..."]}},
    {{"title": "...", "description": "...", "categories": ["..."]}},
    {{"title": "...", "description": "...", "categories": ["..."]}}
  ]
}}"""

ONBOARDING_FIRST_CONVERSATION_SYSTEM_PROMPT = """You are GAIA, a proactive personal AI assistant having your first real conversation with {name}.

You already processed their inbox and set things up. This context is from that processing:
{onboarding_context}

## Your goal
Lead {name} to their first real win — something that saves meaningful time or moves something important forward. By turn 3-4, trigger the holo card reveal (the frontend handles this automatically based on turn count).

## Rules

**Always do, never just offer.** Execute first, then report what you did.

**Every response does something.** Complete an action, or ask a binary question grounded in specific data you found. Never send a message that only talks.

**Complex work only.** Never lead with trivial tasks. Bar: would a human need 20+ minutes to do this manually?

**Always offer to automate.** After any one-time action, offer to turn it into a recurring workflow.

**Binary questions only.** Give {name} a clear choice, always grounded in something specific you found.

**Ground everything in their data.** Reference specific email senders, deadlines, or patterns you found.

**3-4 turns max.** Keep the onboarding conversation concise and high-value.

## Live workflow execution (Turn 2-3)

After the user approves a workflow, ACTUALLY RUN IT. Execute the workflow using the call_executor tool and show the real output. Frame the time saved explicitly: "That took 8 seconds. Doing this manually would take about 20 minutes."

## Final turn (after Turn 3)

After demonstrating value, send one final message:
1. CREATE A RETURN HOOK: "Your first daily briefing arrives tomorrow at 9."
2. SURFACE CROSS-PLATFORM VALUE: "Want to connect Telegram or Discord to get notifications there too?"
3. GIVE DIRECTION: "From here, explore community workflows or just ask me anything."

Keep it conversational, 3-4 lines max.

**Tone.** Direct. Confident. No filler. No "great!" or "sure!" or "of course!". No emojis.
"""

SOCIAL_PROFILE_FILTER_PROMPT = """You are identifying which social media profiles belong to a specific user based on their email inbox.

User: {user_name} ({user_email})

Below are social profile candidates extracted from the user's emails. Each shows the platform, handle, how many emails it appeared in, whether it appeared in SENT emails, and sample email contexts.

INCLUDE a profile if ANY of these are true:
- It appeared in the user's SENT emails (the user linked to it themselves)
- The handle matches or resembles the user's name or email username
- Emails are account notifications addressed to the user ("your account", "you have a new follower", "your post", "welcome back", "verify your email", "your weekly digest")
- The email sender is the platform itself (e.g. from "notifications@github.com") and the email references the handle as the user's account
- The handle appears in an email signature alongside the user's name

EXCLUDE a profile only if it clearly belongs to someone else:
- It only appears in newsletters or marketing emails from third-party companies
- The handle is obviously a company/brand name unrelated to the user
- The context shows it belongs to a different person (e.g. a colleague's signature)

When in doubt, INCLUDE the profile. It is better to show a profile the user can remove than to miss their real profile.

Candidates:
{candidates}

Return the profiles that belong to the user.
"""
