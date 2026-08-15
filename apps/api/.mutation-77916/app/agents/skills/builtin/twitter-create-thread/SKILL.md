---
name: twitter-create-thread
description: Create Twitter/X threads with research-backed storytelling - research the topic, structure narrative, draft for review, then post.
target: twitter_agent
---

# Twitter Create Thread

## When to Use
- User asks to "create a thread" or "tweet a thread"
- User wants to explain a topic in multiple tweets
- User asks to "make a thread about..."
- User wants to share a detailed take on something

## Tools

### Research
- **TWITTER_RECENT_SEARCH** — Search recent tweets on the topic
- **TWITTER_USER_LOOKUP_BY_USERNAME** — Look up relevant accounts

### Creation
- **TWITTER_CUSTOM_CREATE_THREAD** — Post entire thread at once
  - tweets: Array of tweet text strings
  - Returns: Thread URL

### Scheduling
- **TWITTER_CUSTOM_SCHEDULE_TWEET** — Schedule for later (single tweets only)

## Workflow

### Step 1: Research the Topic

Before writing, understand the current discourse:

```
TWITTER_RECENT_SEARCH(query="<topic keywords>", max_results=10)
```

Study the results to learn:
- What angles are already covered (avoid rehashing)
- What terminology and hashtags are trending
- What engagement patterns work (questions, hot takes, data)
- Any misconceptions you can address

### Step 2: Structure the Thread

A great thread follows storytelling structure:

**Tweet 1 — The Hook (MOST IMPORTANT)**
- Bold claim, surprising fact, or compelling question
- This is what appears in timeline — it must stop the scroll
- Include "Thread:" so people know more is coming

**Tweets 2-3 — Context & Setup**
- Why this matters
- Background the reader needs

**Tweets 4-6 — Key Points**
- One clear idea per tweet
- Use data, examples, or analogies
- Each tweet should make sense on its own

**Tweet 7 — Examples or Evidence**
- Concrete proof or real-world application
- Screenshots, links, or references if relevant

**Final Tweet — Conclusion + CTA**
- Summarize the takeaway
- End with a question, call to action, or invitation to engage
- "What do you think?" or "Follow for more on X"

### Step 3: Writing Best Practices

- **280 chars per tweet** — Leave room, don't max out every tweet
- **Line breaks** — Use them for readability within tweets
- **One idea per tweet** — Don't cram multiple points
- **Conversational tone** — Write like you're explaining to a smart friend
- **No walls of text** — Short sentences, clear language
- **4-8 tweets total** — Sweet spot for engagement; longer threads lose readers
- **Emojis sparingly** — 1-2 per tweet max, only if they add meaning

### Step 4: Draft and Confirm

**ALWAYS present the full thread to the user before posting:**

```
Thread draft (6 tweets):

1/ [Hook tweet]

2/ [Context]

3/ [Key point 1]

4/ [Key point 2]

5/ [Evidence/example]

6/ [Conclusion + CTA]

Ready to post? Any tweets you'd like to edit?
```

Wait for explicit approval. Allow per-tweet edits.

### Step 5: Post the Thread

After approval:
```
TWITTER_CUSTOM_CREATE_THREAD(tweets=[
    "Tweet 1 text",
    "Tweet 2 text",
    ...
])
```

Report back with:
- Thread URL
- Total tweet count
- "Your thread is live! Here's the link."

## Common Issues

### Thread Too Long
- Suggest condensing to 6-8 tweets
- Combine related points
- Cut less essential tweets

### Topic Too Narrow
- "This might work better as a single tweet. Want me to craft one instead?"

### User Wants to Schedule
- CUSTOM_SCHEDULE_TWEET handles single tweets, not threads
- Inform user: "Thread scheduling isn't available yet — I can post it now or save the draft for you to post later."

## Important Rules
1. **Research first** — Understand what's already being said
2. **Hook is everything** — First tweet determines if people read the rest
3. **Draft before posting** — Always show the full thread for review
4. **One idea per tweet** — Keep each tweet focused and standalone
5. **4-8 tweets sweet spot** — Respect the reader's time
