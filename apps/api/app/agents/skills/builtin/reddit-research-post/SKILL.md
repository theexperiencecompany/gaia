---
name: reddit-research-post
description: Research subreddits and create posts — find the right subreddit, analyze trends, check rules and flairs, craft content, draft for review
target: reddit_agent
---

# Reddit: Research & Post

## When to Activate
User wants to post on Reddit for marketing, community engagement, research, or content sharing.

## Step 1: Research the Right Subreddit

**Find relevant subreddits:**
```
REDDIT_GET_SUBREDDITS_SEARCH(q="artificial intelligence", limit=10)
```

**Check subreddit rules (critical before posting):**
```
REDDIT_GET_SUBREDDIT_RULES(subreddit="MachineLearning")
```

**Analyze what works — read top posts:**
```
REDDIT_GET_R_TOP(subreddit="MachineLearning", t="month", limit=10)
REDDIT_RETRIEVE_REDDIT_POST(subreddit="startup", sort="hot", max_results=10)
```

### Using spawn_subagent for Multiple Subreddits

When researching multiple subreddits in parallel:

```
spawn_subagent(task="Research r/MachineLearning - top posts and rules", context="Focus on what content succeeds and community rules")
spawn_subagent(task="Research r/startup - top posts and rules", context="Focus on what content succeeds and community rules")
spawn_subagent(task="Research r/AI - top posts and rules", context="Focus on what content succeeds and community rules")
```

This enables parallel research across multiple subreddits.

**Think:**
- What post types succeed? (text, link, image)
- What's the community tone? (technical, casual, formal)
- What's the posting frequency?
- What gets upvoted vs downvoted?

## Step 2: Search Existing Content

Before posting, check if the topic was recently covered:
```
REDDIT_SEARCH_ACROSS_SUBREDDITS(
  search_query="title:AI productivity tools subreddit:startup",
  sort="new",
  limit=20
)
```

If similar recent post exists → warn user about potential duplicate.

## Step 3: Check Flairs

Many subreddits require flair:
```
REDDIT_GET_R_SUBREDDIT_LINK_FLAIR_V2(subreddit="startup")
```

Pick the most appropriate flair based on content.

## Step 4: Craft the Post

**Text post (self):**
```
Content structure:
  - Hook: Opening that grabs attention
  - Value: What the reader gains
  - Body: Details, evidence, experience
  - CTA: Question or call to discussion

Reddit markdown tips:
  - Use ## headers for sections
  - **Bold** key points
  - Use bullet lists
  - Keep paragraphs short (2-3 sentences)
  - TL;DR at the end for long posts
```

**Present draft to user before posting:**
```
Reddit Post Draft:

Subreddit: r/startup
Flair: "Discussion"
Title: "We cut our customer onboarding time by 60% — here's exactly how"

---
[Body preview]
---

Rules check: Self-promotion allowed (max 1 in 10 posts)
Similar posts: None in past 30 days

Should I post this?
```

## Step 5: Post & Monitor

```
REDDIT_CREATE_REDDIT_POST(
  subreddit="startup",
  title="We cut our customer onboarding time by 60% — here's exactly how",
  text="Full markdown body...",
  kind="self",
  flair_id="uuid-from-flair-list"  # Must be valid UUID from REDDIT_GET_R_SUBREDDIT_LINK_FLAIR_V2
)
```

For link posts:
```
REDDIT_CREATE_REDDIT_POST(
  subreddit="startup",
  title="Great article on scaling",
  url="https://example.com/article",
  kind="link"
)
```

## Step 6: Engage with Comments

If the user wants to respond to comments:
```
REDDIT_RETRIEVE_POST_COMMENTS(article="t3_...")
REDDIT_POST_REDDIT_COMMENT(thing_id="t1_...", text="Thanks for the feedback! ...")
```

## Marketing-Specific Guidance
- Never be overtly promotional (Reddit hates it)
- Lead with value, mention product naturally
- Use storytelling: "We had this problem → tried this → result"
- Engage genuinely in comments
- Check subreddit self-promotion rules
- Don't use clickbait titles
- Include concrete numbers/results
