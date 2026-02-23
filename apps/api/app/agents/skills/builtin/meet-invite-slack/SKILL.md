---
name: meet-invite-slack
description: Instantly create a Google Meet space and share the link with a teammate on Slack.
target: executor
---

# Meet: Quick Invite via Slack

## When to Activate
User says "Set up a meeting with [Name] now", "Send a meet link to [Name]", or "Create a room and invite [Name]".

## Step 1: Create the Meet Space

**Generate an instant meeting room:**
```
GOOGLEMEET_CREATE_SPACE() → returns space_id and config
```

**Extract the meeting URI:**
- The response contains a conferencing link (usually under `config` or `uri`).

## Step 2: Find the Recipient on Slack

**Search for the user:**
```
SLACK_FIND_USERS(query="[Name]") → returns list of users with IDs
```

**Select the best match:**
- Look for display names or real names that match.
- If multiple semi-matches exist, ask: "I found [John A] and [John B]. Which one should I invite?"

## Step 3: Send the Invitation

**Post the link in a DM:**
```
SLACK_SEND_MESSAGE(
  channel="[User ID]",
  text="Hey! Let's hop on a quick call about [Topic]. Here's the link: [Meet Link]"
)
```

## Step 4: Confirm to User
"Created a Google Meet and sent the link to [Name] on Slack."

## Tools Used
- **Google Meet**: `GOOGLEMEET_CREATE_SPACE`
- **Slack**: `SLACK_FIND_USERS`, `SLACK_SEND_MESSAGE`, `SLACK_OPEN_DM`

## Anti-Patterns
- Creating the meeting but forgetting to send the link
- Sending the link without any context (always include the [Topic])
- Picking a Slack user blindly if names are ambiguous
