"""Docstrings for support-related LangChain tools."""

CREATE_SUPPORT_TICKET = """
Create a support ticket draft for user review and submission.

This tool prepares support ticket data and streams it to the frontend for user review.
The user can edit the details and submit the ticket when ready via the UI.

SUPPORT REQUEST TYPES:
• SUPPORT - Technical issues, bugs, account problems, general help
• FEATURE - Feature requests, enhancement suggestions, new functionality

USAGE:
When users express need for help, have issues, want to report bugs, request features,
or need to contact support, use this tool to prepare a support ticket draft.

EXAMPLES:
• "I'm having trouble with my account" → type: "support"
• "Can you add a dark mode feature?" → type: "feature"
• "The app keeps crashing" → type: "support"
• "I'd like to request a new integration" → type: "feature"

PROCESS:
1. Determines the appropriate type based on user request
2. Prepares support ticket data with user information
3. Streams the data to frontend for user review and editing
4. User can modify details and submit via the UI
5. Final submission generates ticket ID and sends email notifications

USAGE RULES:
• Make sure to use plain text only, no markdown formatting
• NEVER call this tool multiple times in one request
• Draft your message and title comprehensively to include all necessary information
• One tool call should contain complete details for the entire support request

The user will see a review card where they can edit the ticket details before
submitting to the support team.

Args:
    type: "support" for technical issues/help, "feature" for enhancement requests
    title: Brief, descriptive title of the issue or request (1-200 characters)
    description: Detailed explanation of the issue, steps to reproduce, or feature details (10-5000 characters). Use plain text only, no markdown formatting.

Returns:
    String confirmation that the support ticket draft has been prepared for review
"""
