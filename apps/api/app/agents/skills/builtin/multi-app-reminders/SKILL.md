---
name: multi-app-reminders
description: Create reminders across Slack, Todoist, and Google Calendar.
target: any
---

# Reminders: Multi-App Sync

## When to Activate
User says "Remind me to [Task] at [Time]", "Set a reminder on Slack and Todoist", or "Make sure I don't forget to [Task]".

## Step 1: Parsing the Request

**Extract:**
- Task/Topic
- Time/Date
- Preferred platforms (defaults to all if not specified)

## Step 2: Create Slack Reminder

**Set a personal reminder:**
```
SLACK_CREATE_REMINDER(
  text="[Task]",
  time="[Natural Language Time]"
)
```

## Step 3: Create Todoist Task

**Set a task with a reminder:**
```
TODOIST_CREATE_TASK(
  content="[Task]",
  due_string="[Time]",
  priority=3
)
```

## Step 4: Create Calendar Event (Optional)

**Add a 'Reminder' event:**
```
GOOGLECALENDAR_CUSTOM_CREATE_EVENT(
  calendar_id="primary",
  summary="REMINDER: [Task]",
  start_time="[ISO Time]",
  end_time="[ISO Time + 15m]"
)
```

## Step 5: Final Confirmation
"Done! I've set reminders for '[Task]' at [Time] on:
- Slack
- Todoist
- Google Calendar"

## Tools Used
- **Slack**: `SLACK_CREATE_REMINDER`
- **Todoist**: `TODOIST_CREATE_TASK`
- **Google Calendar**: `GOOGLECALENDAR_CUSTOM_CREATE_EVENT`

## Anti-Patterns
- Only setting it on one platform when the user asked for "reminders" (plural)
- Using messy time formatting (standardize to natural language or ISO)
- Not confirming the specific time to the user
