---
name: meeting-scheduler-smart
description: Find common free time, suggest slots, and schedule meetings with multiple participants.
target: any
---

# Calendar: Smart Scheduler

## When to Activate
User says "Schedule a 30m meeting with [A] and [B] sometime this week", "Find a time for us to chat about [Topic]", or "When are [A] and [B] both free?".

## Step 1: Identify Participants & IDs

**Resolve emails/IDs:**
- Use `SLACK_FIND_USERS` or `GMAIL_GET_CONTACTS` to find participant emails.

## Step 2: Check Availability

**Query calendars:**
```
GOOGLECALENDAR_FREE_BUSY_QUERY(
  time_min="today 09:00",
  time_max="friday 17:00",
  items=[{"id": "email1@text.com"}, {"id": "email2@text.com"}]
)
```

## Step 3: Identify Free Slots

**Analyze gaps:**
- Match the requested duration (e.g., 30 mins).
- Filter out non-working hours.
- Suggest 2-3 specific options: "How about Tuesday at 2pm or Wednesday at 10am?"

## Step 4: Create the Event

**Once user picks a slot:**
```
GOOGLECALENDAR_CUSTOM_CREATE_EVENT(
  calendar_id="primary",
  summary="[Topic]",
  start_time="...",
  end_time="...",
  attendees=["email1", "email2"]
)
```

**Add Meet Link:**
- Call `GOOGLEMEET_CREATE_SPACE` and add the URI to the event description or location.

## Step 5: Notify Participants

**Send Slack confirmation:**
"Scheduled the meeting for [Time]. Invites have been sent to [Emails]."

## Tools Used
- **Google Calendar**: `GOOGLECALENDAR_FREE_BUSY_QUERY`, `GOOGLECALENDAR_CUSTOM_CREATE_EVENT`, `GOOGLECALENDAR_FIND_FREE_SLOTS`
- **Google Meet**: `GOOGLEMEET_CREATE_SPACE`
- **Slack**: `SLACK_FIND_USERS`, `SLACK_SEND_MESSAGE`

## Anti-Patterns
- Picking a time without checking all participants
- Overlooking time zones (always verify user's current timezone)
- Not providing a few options for the user to choose from
