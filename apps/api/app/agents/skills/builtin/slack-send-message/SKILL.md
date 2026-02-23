---
name: slack-send-message
description: Send Slack messages intelligently - discover channels/users, understand conversation context, craft contextual messages, handle DMs and threads.
target: slack_agent
---

# Slack Send Message

## When to Use
- User asks to "send a message" or "post in channel"
- User asks to "DM someone" or "message someone"
- User asks to "reply to" a message or thread
- User wants to "post in #channel"

## Tools

### Discovery
- **SLACK_FIND_CHANNELS** — Search channels by name
- **SLACK_LIST_ALL_CHANNELS** — List all channels
- **SLACK_FIND_USERS** — Search users by name
- **SLACK_FIND_USER_BY_EMAIL_ADDRESS** — Find user by email
- **SLACK_OPEN_DM** — Open/get DM channel with a user

### Context
- **SLACK_FETCH_CONVERSATION_HISTORY** — Get recent channel messages
- **SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION** — Get thread replies
- **SLACK_SEARCH_MESSAGES** — Search messages with query modifiers

### Messaging
- **SLACK_SEND_MESSAGE** — Send message to channel/DM
  - channel: Channel or DM ID
  - text: Message content
  - thread_ts: Thread timestamp (for replies)
- **SLACK_ADD_REACTION_TO_AN_ITEM** — React with emoji

## Workflow

### Step 1: Discover the Target (NEVER assume IDs)

**For channels:**
```
SLACK_FIND_CHANNELS(query="engineering")
```

**For users:**
```
SLACK_FIND_USERS(search_query="Sarah")
```

If multiple matches, ask user to clarify.

### Step 2: Read Before Writing

Understand the conversation context before sending:

**For channel messages:**
```
SLACK_FETCH_CONVERSATION_HISTORY(channel=channel_id, limit=20)
```

**For thread replies:**
```
SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION(channel=channel_id, thread_ts=message_ts)
```

This helps you:
- Avoid repeating what was just discussed
- Reference recent messages naturally
- Match the channel's tone and formality

### Step 3: Craft Contextual Message

Based on what you've read:
- Reference relevant recent discussion
- Match the channel's communication style
- Keep messages concise but complete
- Use Slack formatting: *bold*, _italic_, `code`, ```code blocks```, >quotes

### Step 4: Send

**Channel message:**
```
SLACK_SEND_MESSAGE(channel=channel_id, text="Message here")
```

**Thread reply:**
```
SLACK_SEND_MESSAGE(channel=channel_id, text="Reply here", thread_ts=thread_ts)
```

**DM workflow:**
```
1. SLACK_FIND_USERS(search_query="Bob")
2. SLACK_OPEN_DM(users=user_id)
3. SLACK_SEND_MESSAGE(channel=dm_channel_id, text="Hey Bob...")
```

### Step 5: Quick Acknowledgments

When a reaction is more appropriate than a text reply:
```
SLACK_ADD_REACTION_TO_AN_ITEM(channel=channel_id, timestamp=message_ts, name="thumbsup")
```

Use reactions for: acknowledgments, approvals, celebrations (🎉), simple yes/no.

## Important Rules
1. **Never assume IDs** — Always discover channels and users first
2. **Read before writing** — Fetch recent context for better messages
3. **Thread replies stay in thread** — Use thread_ts for threaded conversations
4. **DMs need OPEN_DM first** — Can't send DM without opening the channel
5. **Reactions over text** — Use emoji reactions for simple acknowledgments
