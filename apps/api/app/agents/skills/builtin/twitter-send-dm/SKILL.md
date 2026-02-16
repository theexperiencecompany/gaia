---
name: twitter-send-dm
description: Send Twitter/X DMs - find user, verify identity, then send message.
subagent_id: twitter
---

# Twitter Send DM

## When to Use
- User asks to "send a DM"
- User asks to "message someone on Twitter"
- User asks to "send a direct message"
- User wants to reach out to someone on X/Twitter

## Tools

### Finding Users

#### TWITTER_GET_RECENT_DM_EVENTS
Get recent DM conversations.

**Best for:** Finding people you've messaged before
- Shows recent conversations
- Good starting point if they've DMed before

#### TWITTER_CUSTOM_SEARCH_USERS
Search for users by name or username.

**Parameters:**
- query: Search term (name or username)
- max_results: Number of results (default: 10)

**Best for:** Finding new users to DM

#### SEARCH_MEMORY
Search user's stored memories.

**Best for:** Finding handles mentioned in past conversations
- Check if handle was mentioned before

#### TWITTER_USER_LOOKUP_BY_ID
Look up user by ID or username.

**Best for:** Verifying user identity
- Get profile details
- Confirm correct person

### Sending Messages

#### TWITTER_SEND_A_NEW_MESSAGE_TO_A_USER
Send DM to username.

**Required parameters:**
- username: Twitter handle (without @)
- message: The message text

#### TWITTER_SEND_A_NEW_MESSAGE_TO_A_DM_CONVERSATION
Send in existing conversation.

**Required parameters:**
- dm_conversation_id: Existing conversation ID
- message: The message text

## IMPORTANT: Finding Users is the Hardest Part

Twitter handles are tricky. Users often have:
- Different display names vs handles
- Similar names
- Common names (many "John Smiths")

### Recommended Search Order

1. **TWITTER_GET_RECENT_DM_EVENTS**
   - Check if they've messaged before
   - Easiest - you already have conversation

2. **TWITTER_CUSTOM_SEARCH_USERS**
   - Search by name or handle
   - Returns multiple matches

3. **SEARCH_MEMORY**
   - Check stored memories
   - User may have mentioned handle before

4. **TWITTER_USER_LOOKUP_BY_ID**
   - If user gave you an ID
   - Verify found user

### Handling No Results

If search returns nothing:
- Ask user for more info
- Request exact Twitter handle
- Ask for @username

## Workflow

### Step 1: Find the User

Try in this order:
1. Check recent DMs
2. Search by name
3. Check memory
4. Ask user for handle

### Step 2: Verify Identity

**ALWAYS verify before sending!**

Show user the profile and ask:
```
Is this the right person?
@johnsmith - John Smith
Bio: Software Engineer at Company
Followers: 1.2K
```

Wait for confirmation before proceeding.

### Step 3: Send the DM

Only after user confirms:
- Use TWITTER_SEND_A_NEW_MESSAGE_TO_A_USER
- Include username and message

### Step 4: Confirm Success

Let user know:
- "DM sent to @username"
- Show message content
- Mention if they have DMs disabled (will fail)

## Common Issues

### User Not Found
- Ask for exact handle
- "I couldn't find that person. Do you have their @username?"

### DM Failed
- User may have DMs disabled
- User may not follow you
- Check error message
- Inform user

### Multiple Matches
- Show all matches
- Ask which one
- Verify with profile

## Important Rules
1. **ALWAYS verify** - Show profile, get confirmation
2. **Check permissions** - Some users block DMs
3. **Handle failures** - Explain what went wrong
4. **Ask for help** - If can't find, ask user
5. **Be patient** - Finding right user takes time

## Tips
- Ask for @username when possible
- Search by handle works better than name
- Recent DMs is easiest path
- Always confirm before sending
