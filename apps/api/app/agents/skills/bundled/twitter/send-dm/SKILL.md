---
name: send-dm
description: Send direct messages on X (Twitter) - compose and send DMs to users, handle multi-part messages for longer content
target: twitter
auto_invoke: true
---

# X (Twitter) Direct Message Guide

Use this skill when sending direct messages on X/Twitter.

## Sending a DM

1. **Find the recipient**: Use `TWITTER_GET_USER_BY_USERNAME` to resolve the username to a user ID if you only have a handle.

2. **Compose the message**:
   - DMs can be up to 10,000 characters
   - For longer messages, consider using a thread or linking to external content
   - Keep messages conversational and natural

3. **Send**: Use `TWITTER_SEND_DM` with:
   - `user_id`: The recipient's Twitter user ID (not username)
   - `text`: Your message content

## Best Practices

- **Personalize**: Use the recipient's name and reference shared context
- **Be concise**: DMs are meant to be quick communications
- **Include context**: If related to a previous conversation or tweet, reference it
- **Call to action**: Make it clear what you want the recipient to do

## Multi-Part Messages

For messages over 10,000 characters:
1. Split into logical parts
2. Send sequentially
3. Optionally indicate "Part 1/2" in the first message

## Error Handling

If DM fails:
- Check if user allows DMs from non-followers
- Verify user ID is correct
- Handle rate limits - wait and retry

## Example Scenarios

### Simple DM
```
Hey! Just wanted to follow up on our conversation about the API. 
Here's the endpoint I mentioned: https://docs.example.com/api
```

### Multi-Part Long Message
```
Part 1/2: Here's the full project update...

Part 2/2: ...continuing from above. Let me know if you have questions!
```
