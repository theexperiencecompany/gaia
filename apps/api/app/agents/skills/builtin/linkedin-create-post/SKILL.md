---
name: linkedin-create-post
description: Create and manage LinkedIn posts with a professional standard - draft-first posting, post as me or company, and high-quality engagement workflows.
target: linkedin_agent
---

# LinkedIn: Create Posts (and Engage Safely)

## When to Activate

- User asks to create a LinkedIn post (text, image, document, link/article)
- User asks to polish/draft a LinkedIn post in a professional tone
- User asks to post as themselves vs as a company page
- User asks to react/comment on a LinkedIn post, or review comments

## Tools

### Author and org context

- **LINKEDIN_GET_MY_INFO** - get authenticated user identity and profile context
- **LINKEDIN_GET_COMPANY_INFO** - get organization context when posting/engaging as a company

### Posting

- **LINKEDIN_CUSTOM_CREATE_POST** - preferred post creation tool in this system

### Engagement and management

- **LINKEDIN_CUSTOM_GET_POST_COMMENTS** - fetch comments for a post
- **LINKEDIN_CUSTOM_REACT_TO_POST** - add a reaction to a post
- **LINKEDIN_CUSTOM_ADD_COMMENT** - add a comment to a post
- **LINKEDIN_CUSTOM_GET_POST_REACTIONS** - fetch reactions for a post
- **LINKEDIN_CUSTOM_DELETE_REACTION** - remove a reaction (requires explicit user confirmation)

Prefer the LINKEDIN_CUSTOM_* tools listed above (they are the supported set in this repo).
If a capability is not available via custom tools, use composio toolkit tools (discover via retrieve_tools),
then still follow the same draft-first + confirmation rules.

Common composio LINKEDIN tools you may see:
- LINKEDIN_CREATE_LINKED_IN_POST
- LINKEDIN_CREATE_COMMENT_ON_POST
- LINKEDIN_GET_POST_CONTENT
- LINKEDIN_LIST_REACTIONS
- LINKEDIN_DELETE_POST / LINKEDIN_DELETE_LINKED_IN_POST

Composio tools often require explicit author URNs:
- For posting as a person: author="urn:li:person:<person_id>" (get person_id via LINKEDIN_GET_MY_INFO)
- For posting as an org: author="urn:li:organization:<org_id>" (get org_id via LINKEDIN_GET_COMPANY_INFO)

## Professional Standard (Non-Negotiable)

- Maintain a professional, business-appropriate tone.
- Avoid slang, profanity, and overly casual language.
- Do not fabricate achievements, metrics, titles, affiliations, or outcomes.
- Prefer clarity over cleverness; use short paragraphs and readable formatting.
- Avoid emojis unless the user explicitly uses them or requests them.

## Draft-First Rule (Critical)

For creating posts:

1. Draft the post copy first and show it to the user.
2. Ask for explicit confirmation to post (e.g., "Post it", "Yes, publish", "Go ahead").
3. Only then call the chosen post-creation tool (prefer LINKEDIN_CUSTOM_CREATE_POST; LINKEDIN_CREATE_LINKED_IN_POST is also acceptable).

Do not publish on the user's behalf without explicit confirmation.

If you need to use composio tools for post creation, you may use:
- LINKEDIN_CREATE_LINKED_IN_POST

Even then: keep the same draft-first + explicit confirmation rule.
If supported/desired, you may create a platform draft with lifecycleState="DRAFT".

## Step 1: Determine Author and Goal

Collect (or infer from context) the minimum:

- Objective: announce / educate / hiring / launch / learnings / personal update
- Audience: customers / peers / recruiters / founders / internal team
- Voice: confident / humble / informative / celebratory
- Call-to-action: comment / DM / link click / hiring applications
- Post as: me vs company page

If author context matters, call:

- LINKEDIN_GET_MY_INFO
- If posting as a company, LINKEDIN_GET_COMPANY_INFO

## Step 2: Choose Post Type and Required Inputs

Prefer **LINKEDIN_CUSTOM_CREATE_POST**. You may also use **LINKEDIN_CREATE_LINKED_IN_POST**.

- Text-only: commentary only
- Image post: commentary + image_url (or image_urls for carousel; supported, max 20)
- Document post: commentary + document_url + document_title
- Link/article post: commentary + article_url

The tool should handle media uploads.

## Step 3: Draft the Post Copy

Recommended structure:

1. Hook (1-2 lines)
2. Value (2-5 short paragraphs or bullets)
3. Credible details (only true, verifiable)
4. CTA (one clear action)

Formatting rules:

- Use whitespace; avoid dense blocks.
- Use bullets sparingly (3-7 max).
- Use 0-3 hashtags unless the user asks for more.

## Step 4: Create the Post

Examples (shape; adjust to actual tool schema):

```python
# Text-only
LINKEDIN_CUSTOM_CREATE_POST(commentary="...", visibility="PUBLIC")

# Image
LINKEDIN_CUSTOM_CREATE_POST(commentary="...", image_url="https://...", visibility="PUBLIC")

# Document
LINKEDIN_CUSTOM_CREATE_POST(
  commentary="...",
  document_url="https://...",
  document_title="...",
  visibility="PUBLIC",
)

# Link/article
LINKEDIN_CUSTOM_CREATE_POST(commentary="...", article_url="https://...", visibility="PUBLIC")

# Post as an organization
LINKEDIN_CUSTOM_CREATE_POST(
  commentary="...",
  organization_id="urn:li:organization:12345",
  visibility="PUBLIC",
)
```

Return the post URL and the returned post URN.
Note: the tool returns `post_id` as the post URN; use it as `post_urn` for comments/reactions.

## Engagement Guidance

### Reactions

Choose a reaction that matches intent:

- LIKE: general appreciation
- CELEBRATE: milestones, launches, promotions
- SUPPORT: challenges, resilience, teamwork
- LOVE: inspiring/human stories (keep professional)
- INSIGHTFUL: analysis, thought leadership
- FUNNY: light professional humor only

Tool input uses these values:
LIKE, CELEBRATE, SUPPORT, LOVE, INSIGHTFUL, FUNNY

### Comments (Quality Rule)

Never post generic comments like "Great post".

Good comments must:

- Reference something specific from the post
- Add perspective, a helpful detail, or a thoughtful question
- Stay concise and professional

## Destructive Actions (Safety)

- Removing reactions requires explicit user confirmation.
- If you discover a post deletion tool via retrieve_tools, treat deletion as irreversible and require explicit user confirmation.

## Context-First Rule

If a post URN/ID is already in context, use it directly for comments/reactions.
Do not search unnecessarily.

## Error Handling

If an action fails:

1. Verify assumptions (correct post URN, correct author/org identity)
2. Retry once with corrected inputs
3. If still failing, report clearly what cannot be done and why

## Completion Standard

Task is complete only when:

- The LinkedIn action succeeded, OR
- Explicit user confirmation is awaited (destructive actions), OR
- The action is not possible with available tools.

Always report:

- What action was taken
- Which tool was used
- Any follow-up needed
