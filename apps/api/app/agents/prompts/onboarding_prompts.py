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
  "summary": "Your inbox is mostly... (must be a complete sentence; if the inbox is quiet, write something like 'Your inbox is mostly promotional with few personal threads.' An empty string is never acceptable.)",
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
   - How they open emails (exact phrasing if consistent, e.g. "Hey [name]", "Hi!", no greeting)
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
   NEVER use em dashes in the example email or in the summary. Use commas, periods,
   colons, or parentheses instead. This rule overrides any "dashes" pattern observed in
   the samples: em dashes are off-limits in the output regardless.

   The example is returned as STRUCTURED BLOCKS, not a single string. Fill each field below:
   - `greeting`: just the greeting line (e.g. "Hey Sarah,"). Empty string if the user has no greeting habit.
   - `body`: an array of paragraph strings. Each entry is one paragraph. Use 1-3 entries. Do NOT include
     greeting or sign-off here. Do NOT put `\\n` inside a paragraph; sentences in the same paragraph stay
     on the same string.
   - `signoff`: just the sign-off line (e.g. "Best,"). Empty string if user uses none.
   - `name`: just the sender name (e.g. "Sam"). Empty string if the user does not include one.
   The backend will join these blocks with the right spacing; do not pre-format with newlines.
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

NEVER use em dashes in the example. Use commas, periods, colons, or parentheses instead.

The example is returned as STRUCTURED BLOCKS, not a single string. Fill each field:
- `greeting`: just the greeting line (e.g. "Hey Sarah,"). Empty string if the style has no greeting habit.
- `body`: an array of paragraph strings. Each entry is one paragraph. Use 1-3 entries. Do NOT include
  greeting or sign-off here. Do NOT put `\\n` inside a paragraph.
- `signoff`: just the sign-off line (e.g. "Best,"). Empty string if the style uses none.
- `name`: just the sender name (e.g. "Sam"). Empty string if the style does not include one.
The backend will join these blocks with the right spacing; do not pre-format with newlines.
"""

HOLO_CARD_PROMPT = """Generate this user's holo card content: a unique 2-3 word personality phrase AND a 2-3 sentence bio. Both fields are returned in a single structured response.

User Context:
- Name: {name}
- Profession: {profession} (use as a lens, not a constraint)
- Inferred from inbox & profile: {context_summary}

═══════════════════════════════════════════════════════════
## Personality phrase (2-3 words)
═══════════════════════════════════════════════════════════

Capture the user's essence. Look for underlying themes, values, motivations. Identify patterns in how they think, create, communicate, or solve problems. Consider their energy: catalyst, observer, builder, connector, explorer, guardian. Notice contradictions or dualities that make them interesting.

AVOID:
- Corporate buzzwords: "Hard Worker", "Team Player", "Self Starter", "Go-Getter"
- Generic descriptors: "Creative Mind", "Tech Savvy", "Problem Solver"
- Obvious profession refs: "Code Guru", "Data Wizard", "Design Master"
- Overused metaphors: "Thought Leader", "Change Maker", "Dream Chaser"

AIM FOR:
- Poetic and metaphorical: "Midnight Architect", "Storm Whisperer", "Velvet Rebel"
- Unexpected combinations: "Neon Philosopher", "Gentle Anarchist", "Lunar Pragmatist"
- Evocative imagery: "Ember Keeper", "Atlas Dreamer", "Prism Thinker"
- Personality-driven: "Curious Wanderer", "Quiet Thunder", "Fierce Optimist"
- Abstract concepts: "Pattern Seeker", "Bridge Builder", "Chaos Navigator"
- Sensory/emotional: "Golden Hour Soul", "Silver Tongue", "Diamond Heart"

═══════════════════════════════════════════════════════════
## User bio (2-3 sentences)
═══════════════════════════════════════════════════════════

Sassy best friend who sees through them. Third person. Make them think "wow, how does GAIA know me so well?". Call out patterns and quirks, not job titles.

NEVER use em dashes or en dashes anywhere in the bio. Use commas, periods, colons, or parentheses instead. Em dashes are a tell that the text is AI-generated and are strictly off-limits regardless of how natural they would feel.

GOOD EXAMPLES:
- "Alex writes code like poetry, elegant, intentional, and probably refactored three times. The type to have 47 browser tabs open about some niche framework at 2am, while maintaining a pristine todo list. Chaotic method that somehow always delivers."
- "Sarah notices the 2-pixel misalignment haunting everyone else's dreams. Unreasonable Figma hours, strong kerning opinions, will die on the hill of good UX. The design world doesn't deserve her, but we're grateful anyway."

BAD EXAMPLES (do not write like this):
- "Alex is a passionate software engineer who loves coding and problem-solving."
- "Sarah is a designer who creates beautiful experiences and cares about her craft."

The phrase and bio should feel like they belong to the same person: coherent register, no contradictions."""

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
