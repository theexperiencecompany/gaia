---
name: calendar-create-event
description: Create calendar events intelligently - check availability, handle attendees, manage recurrence, timezone-aware scheduling with confirmation workflow.
target: calendar_agent
---

# Calendar Create Event

## When to Use
- User asks to "create an event" or "schedule a meeting"
- User asks to "add to calendar" or "set up a call"
- User wants to "book time" or "schedule something"
- User asks to make an event recurring

## Tools

### Discovery
- **GOOGLECALENDAR_CUSTOM_LIST_CALENDARS** — List all calendars
- **GOOGLECALENDAR_FIND_FREE_SLOTS** — Find available time slots
- **GOOGLECALENDAR_FREE_BUSY_QUERY** — Check busy/free status
- **GOOGLECALENDAR_CUSTOM_FETCH_EVENTS** — List events in time range
- **GOOGLECALENDAR_CUSTOM_FIND_EVENT** — Search events by keyword

### Creation & Modification
- **GOOGLECALENDAR_CUSTOM_CREATE_EVENT** — Create new event
  - confirm_immediately: False (default, sends to frontend for review)
- **GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE** — Add recurrence to existing event
  - frequency: DAILY, WEEKLY, MONTHLY, YEARLY
  - by_day: ["MO", "WE", "FR"] etc.
  - count / until: Limit occurrences
- **GOOGLECALENDAR_CUSTOM_PATCH_EVENT** — Modify event
- **GOOGLECALENDAR_CUSTOM_DELETE_EVENT** — Delete (REQUIRES CONSENT)

## Workflow

### Step 1: Identify the Right Calendar

```
GOOGLECALENDAR_CUSTOM_LIST_CALENDARS()
```

- User may have multiple calendars (Work, Personal, Shared)
- If ambiguous, ask: "Which calendar? You have Work and Personal."
- Default to primary calendar if only one exists

### Step 2: Check Availability (CRITICAL for meetings)

When scheduling with attendees or specific times:

```
GOOGLECALENDAR_FIND_FREE_SLOTS(
    calendar_id="primary",
    time_min="2026-03-01T09:00:00",
    time_max="2026-03-01T17:00:00"
)
```

- Show available slots to user
- If attendee calendars are accessible, check their availability too
- Suggest the first available slot that works
- If all-day event, skip availability check

### Step 3: Handle Timezone

**All times in user's local timezone.** The backend handles conversion.

- Use ISO format: `"2026-03-01T10:00:00"`
- Do NOT include timezone offset in datetime strings
- Respect the user's stated time literally (if they say "3pm", use 15:00)

### Step 4: Create the Event

```
GOOGLECALENDAR_CUSTOM_CREATE_EVENT(
    calendar_id="primary",
    title="Team Standup",
    start_time="2026-03-01T09:00:00",
    end_time="2026-03-01T09:30:00",
    description="Daily sync",
    attendees=["alice@company.com", "bob@company.com"],
    location="Zoom",
    confirm_immediately=False
)
```

**Confirmation workflow:**
- Default: `confirm_immediately=False` → Event sent to frontend for user review
- Only use `confirm_immediately=True` when user explicitly says "just create it" or when confirming a previously drafted event

### Step 5: Add Recurrence (2-step process)

Recurrence CANNOT be set during creation. Always create first, then add:

```
GOOGLECALENDAR_CUSTOM_ADD_RECURRENCE(
    event_id="created_event_id",
    calendar_id="primary",
    frequency="WEEKLY",
    by_day=["MO", "WE", "FR"],
    count=10
)
```

**Common patterns:**
- Daily standup: `frequency="WEEKLY", by_day=["MO","TU","WE","TH","FR"]`
- Weekly 1:1: `frequency="WEEKLY"`
- Monthly review: `frequency="MONTHLY"`
- Until date: `until="2026-06-30T00:00:00"`
- N occurrences: `count=10`

### Step 6: Confirm to User

Report:
- Event title and time
- Calendar it was added to
- Attendees (if any)
- Recurrence pattern (if set)
- "Check your calendar to confirm the details."

## Error Recovery

If creation fails:
1. **Calendar not found** → LIST_CALENDARS → verify correct calendar_id → retry
2. **Time conflict** → FIND_FREE_SLOTS → suggest alternative time → retry
3. **Permission error** → Inform user, suggest checking calendar sharing settings

## Important Rules
1. **Check availability first** — Especially for meetings with attendees
2. **Local timezone always** — Don't convert to UTC, backend handles it
3. **Confirm before finalizing** — Use confirm_immediately=False by default
4. **Recurrence is 2-step** — Create event first, then add recurrence
5. **Delete requires consent** — Never delete events without asking
