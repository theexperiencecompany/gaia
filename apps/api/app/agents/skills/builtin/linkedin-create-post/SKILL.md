---
name: linkedin-create-post
description: Create and manage LinkedIn posts with a professional standard - post as me or company, and high-quality engagement workflows.
target: linkedin_agent
---

# LinkedIn: Create Posts (and Engage Safely)

## When to Activate

- User asks to create a LinkedIn post (text, image, document, link/article)
- User asks to polish/draft a LinkedIn post in a professional tone
- User asks to post as themselves vs as a company page
- User asks to react/comment on a LinkedIn post, or review comments

## Tools

### Primary custom tools

- **LINKEDIN_CUSTOM_CREATE_POST** - preferred post creation (text/image/carousel/document/article)
- **LINKEDIN_CUSTOM_ADD_COMMENT** - add comment to a post URN
- **LINKEDIN_CUSTOM_GET_POST_COMMENTS** - fetch comments for a post URN
- **LINKEDIN_CUSTOM_REACT_TO_POST** - react to a post URN
- **LINKEDIN_CUSTOM_GET_POST_REACTIONS** - fetch reactions for a post URN
- **LINKEDIN_CUSTOM_DELETE_REACTION** - remove your reaction from a post URN

### Context + identity tools

- **LINKEDIN_GET_MY_INFO** - authenticated person identity context
- **LINKEDIN_GET_COMPANY_INFO** - organization context for company posting
- **LINKEDIN_GET_POST_CONTENT** - read/verify post content before engagement

### Toolkit fallback tools

Use these when a custom tool does not fit the request:

- **LINKEDIN_CREATE_LINKED_IN_POST** - generic fallback post creation
- **LINKEDIN_CREATE_ARTICLE_OR_URL_SHARE** - fallback for URL/article share flows
- **LINKEDIN_CREATE_COMMENT_ON_POST** - fallback comment creation
- **LINKEDIN_LIST_REACTIONS** - fallback reactions listing
- **LINKEDIN_DELETE_POST** / **LINKEDIN_DELETE_LINKED_IN_POST** / **LINKEDIN_DELETE_UGC_POST** / **LINKEDIN_DELETE_UGC_POSTS** - deletion tools (explicit consent required)

Composio fallback tools may require explicit author URNs:
- Person author: `urn:li:person:<person_id>` (resolve via `LINKEDIN_GET_MY_INFO`)
- Organization author: `urn:li:organization:<org_id>` (resolve via `LINKEDIN_GET_COMPANY_INFO`)

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
3. Only then call the chosen post-creation tool.

Do not publish on the user's behalf without explicit confirmation.

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

Prefer **LINKEDIN_CUSTOM_CREATE_POST** for all post types.

- Text-only: commentary only
- Image post: commentary + image_url (or image_urls for carousel; supported, max 20)
- Document post: commentary + document_url + document_title
- Link/article post: commentary + article_url

Fallbacks when needed:
- **LINKEDIN_CREATE_ARTICLE_OR_URL_SHARE** for URL/article specific share flows
- **LINKEDIN_CREATE_LINKED_IN_POST** for generic toolkit creation flows

Custom post tool handles media uploads.

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

# Toolkit fallback for URL/article shares
LINKEDIN_CREATE_ARTICLE_OR_URL_SHARE(...)

# Toolkit fallback for generic post creation
LINKEDIN_CREATE_LINKED_IN_POST(...)
```

Return the post URL and the returned post URN.
Note: the tool returns `post_id` as the post URN; use it as `post_urn` for comments/reactions.

## Engagement Guidance

### Tool mapping

- Read post before engaging: `LINKEDIN_GET_POST_CONTENT`
- Fetch comments: `LINKEDIN_CUSTOM_GET_POST_COMMENTS`
- Add comment: `LINKEDIN_CUSTOM_ADD_COMMENT` (fallback: `LINKEDIN_CREATE_COMMENT_ON_POST`)
- Fetch reactions: `LINKEDIN_CUSTOM_GET_POST_REACTIONS` (fallback: `LINKEDIN_LIST_REACTIONS`)
- Add reaction: `LINKEDIN_CUSTOM_REACT_TO_POST`
- Remove reaction: `LINKEDIN_CUSTOM_DELETE_REACTION` (only after explicit user confirmation)

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
