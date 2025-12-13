"""
Calendar-related prompt templates for the chat agent.
"""

CALENDAR_LIST_PROMPT = """
You have retrieved the user's calendar list.

IMPORTANT INSTRUCTIONS:
- This calendar data is for YOUR internal use only - NEVER show raw JSON to the user
- Use this information to intelligently select the appropriate calendar for events
- Default to the primary calendar (where primary=true) for general events
- Match calendars based on context (e.g., select "Work" calendar for work meetings)
- Only ask the user which calendar to use in extreme cases where you cannot determine the appropriate calendar

When creating calendar events:
1. Silently select the most appropriate calendar based on the event context
2. Use the calendar_id when calling calendar_event
3. Simply tell the user "I'll add this to your calendar" without technical details

Example contextual matching:
- "Schedule a team meeting" → Use "Work" calendar if available
- "Doctor appointment" → Use "Personal" or primary calendar
- "Birthday party" → Use "Personal" or primary calendar
- General events without clear context → Use primary calendar

Here is the calendar list:

{calendars}

"""

CALENDAR_PROMPT = """
Use this template to explain calendar events to the user. The user has requested to create a calendar event, and the event details have been processed.

Remember:
- The event is NOT yet added to the calendar.
- The user must confirm the event details by clicking a confirmation button in the interface.
- The event details will be displayed as an interactive card that the user can review before confirming.

Your response should:
1. Clearly state that you've prepared the calendar event based on their request
2. Mention that they need to review and confirm the details
3. Tell them to click the confirmation button that appears in the interface if they want to add this event
4. Be concise and friendly

DO NOT:
- Suggest that the event has been added already
- Ask for additional details about the event
- Include technical details about the API or process
- Present the event details as your own text - they will be displayed separately

Example response:
"I've prepared a calendar event based on your request. Please review the details that appear in the calendar card and click the confirmation button if you'd like to add this to your calendar."
"""

CALENDAR_DELETE_PROMPT = """
Use this template to explain calendar event deletion to the user. The user has requested to delete a calendar event, and you've found the matching event.

Remember:
- The event is NOT yet deleted from the calendar.
- The user must confirm the deletion by clicking a confirmation button in the interface.
- The event details will be displayed as an interactive card that the user can review before confirming deletion.

Your response should:
1. Clearly state that you've found the event they want to delete
2. Mention that they need to review and confirm the deletion
3. Tell them to click the confirmation button that appears in the interface if they want to delete this event
4. Be concise and friendly

DO NOT:
- Suggest that the event has been deleted already
- Ask for additional details about the event
- Include technical details about the API or process
- Present the event details as your own text - they will be displayed separately

Example response:
"I found the event you want to delete. Please review the details that appear in the confirmation card and click the delete button if you'd like to remove this from your calendar."
"""

CALENDAR_EDIT_PROMPT = """
Use this template to explain calendar event editing to the user. The user has requested to edit a calendar event, and you've found the matching event with their requested changes.

Remember:
- The event is NOT yet updated in the calendar.
- The user must confirm the changes by clicking a confirmation button in the interface.
- The event details (original and updated) will be displayed as an interactive card that the user can review before confirming.

Your response should:
1. Clearly state that you've found the event they want to edit and prepared the changes
2. Mention that they need to review and confirm the updates
3. Tell them to click the confirmation button that appears in the interface if they want to save these changes
4. Be concise and friendly

DO NOT:
- Suggest that the event has been updated already
- Ask for additional details about the event
- Include technical details about the API or process
- Present the event details as your own text - they will be displayed separately

Example response:
"I found the event you want to edit and prepared your requested changes. Please review the updated details that appear in the confirmation card and click the update button if you'd like to save these changes to your calendar."
"""
