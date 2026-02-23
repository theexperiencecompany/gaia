"""Slack subgraph tools configuration.

This module exports the curated list of Slack tools, excluding deprecated ones.
"""

# ============================================================================
# CORE MESSAGING TOOLS
# ============================================================================
MESSAGING_TOOLS = [
    "SLACK_SEND_MESSAGE",
    "SLACK_SEARCH_MESSAGES",
    "SLACK_SEARCH_ALL",
    "SLACK_FETCH_CONVERSATION_HISTORY",
    "SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION",
    "SLACK_SCHEDULE_MESSAGE",
    "SLACK_LIST_SCHEDULED_MESSAGES",
    "SLACK_DELETE_A_SCHEDULED_MESSAGE_IN_A_CHAT",
    "SLACK_UPDATES_A_SLACK_MESSAGE",
    "SLACK_DELETES_A_MESSAGE_FROM_A_CHAT",
    "SLACK_SEND_EPHEMERAL_MESSAGE",
    "SLACK_RETRIEVE_MESSAGE_PERMALINK_URL",
]

# ============================================================================
# CHANNEL DISCOVERY & MANAGEMENT TOOLS
# ============================================================================
CHANNEL_DISCOVERY_TOOLS = [
    "SLACK_FIND_CHANNELS",
    "SLACK_LIST_ALL_CHANNELS",
    "SLACK_LIST_CONVERSATIONS",
    "SLACK_RETRIEVE_CONVERSATION_INFORMATION",
    "SLACK_RETRIEVE_CONVERSATION_MEMBERS_LIST",
    "SLACK_GET_CHANNEL_CONVERSATION_PREFERENCES",
]

CHANNEL_MANAGEMENT_TOOLS = [
    "SLACK_CREATE_CHANNEL",
    "SLACK_CREATE_CHANNEL_BASED_CONVERSATION",
    "SLACK_ARCHIVE_A_SLACK_CONVERSATION",
    "SLACK_UNARCHIVE_CHANNEL",
    "SLACK_INVITE_USERS_TO_A_SLACK_CHANNEL",
    "SLACK_REMOVE_A_USER_FROM_A_CONVERSATION",
    "SLACK_JOIN_AN_EXISTING_CONVERSATION",
    "SLACK_LEAVE_A_CONVERSATION",
    "SLACK_SET_A_CONVERSATION_S_PURPOSE",
    "SLACK_SET_THE_TOPIC_OF_A_CONVERSATION",
    "SLACK_RENAME_A_CONVERSATION",
    "SLACK_CONVERT_PUBLIC_CHANNEL_TO_PRIVATE",
]

# ============================================================================
# USER DISCOVERY & PROFILE TOOLS
# ============================================================================
USER_DISCOVERY_TOOLS = [
    "SLACK_FIND_USERS",
    "SLACK_FIND_USER_BY_EMAIL_ADDRESS",
    "SLACK_LIST_ALL_USERS",
    "SLACK_RETRIEVE_DETAILED_USER_INFORMATION",
    "SLACK_RETRIEVE_USER_PROFILE_INFORMATION",
    "SLACK_GET_USER_PRESENCE_INFO",
    "SLACK_TEST_AUTH",
    "SLACK_REMOVE_USER_FROM_WORKSPACE",
]

# ============================================================================
# DIRECT MESSAGE TOOLS
# ============================================================================
DM_TOOLS = [
    "SLACK_OPEN_DM",
    "SLACK_CLOSE_DM_OR_MULTI_PERSON_DM",
]

# ============================================================================
# REACTION TOOLS
# ============================================================================
REACTION_TOOLS = [
    "SLACK_ADD_REACTION_TO_AN_ITEM",
    "SLACK_REMOVE_REACTION_FROM_ITEM",
    "SLACK_FETCH_ITEM_REACTIONS",
    "SLACK_LIST_USER_REACTIONS",
]

# ============================================================================
# FILE TOOLS
# ============================================================================
FILE_TOOLS = [
    "SLACK_UPLOAD_OR_CREATE_A_FILE_IN_SLACK",
    "SLACK_LIST_FILES_WITH_FILTERS_IN_SLACK",
    "SLACK_RETRIEVE_DETAILED_INFORMATION_ABOUT_A_FILE",
    "SLACK_DELETE_A_FILE_BY_ID",
    "SLACK_ENABLE_PUBLIC_SHARING_OF_A_FILE",
    "SLACK_REVOKE_PUBLIC_SHARING_ACCESS_FOR_A_FILE",
]

# ============================================================================
# PINS & STARS TOOLS
# ============================================================================
PINS_STARS_TOOLS = [
    "SLACK_PINS_AN_ITEM_TO_A_CHANNEL",
    "SLACK_UNPIN_ITEM_FROM_CHANNEL",
    "SLACK_LISTS_PINNED_ITEMS_IN_A_CHANNEL",
    "SLACK_ADD_A_STAR_TO_AN_ITEM",
    "SLACK_REMOVE_A_STAR_FROM_AN_ITEM",
    "SLACK_LIST_STARRED_ITEMS",
]

# ============================================================================
# REMINDER TOOLS
# ============================================================================
REMINDER_TOOLS = [
    "SLACK_CREATE_A_REMINDER",
    "SLACK_LIST_REMINDERS",
    "SLACK_GET_REMINDER_INFORMATION",
    "SLACK_DELETE_A_SLACK_REMINDER",
]

# ============================================================================
# STATUS & PRESENCE TOOLS
# ============================================================================
STATUS_PRESENCE_TOOLS = [
    "SLACK_SET_STATUS",
    "SLACK_CLEAR_STATUS",
    "SLACK_SET_DND_DURATION",
    "SLACK_END_SNOOZE",
    "SLACK_END_USER_DO_NOT_DISTURB_SESSION",
    "SLACK_RETRIEVE_CURRENT_USER_DND_STATUS",
    "SLACK_GET_TEAM_DND_STATUS",
    "SLACK_MANUALLY_SET_USER_PRESENCE",
    "SLACK_USERS_SET_ACTIVE",
]

# ============================================================================
# USER GROUP TOOLS
# ============================================================================
USER_GROUP_TOOLS = [
    "SLACK_CREATE_A_SLACK_USER_GROUP",
    "SLACK_UPDATE_AN_EXISTING_SLACK_USER_GROUP",
    "SLACK_DISABLE_AN_EXISTING_SLACK_USER_GROUP",
    "SLACK_ENABLE_A_SPECIFIED_USER_GROUP",
    "SLACK_UPDATE_USER_GROUP_MEMBERS",
    "SLACK_LIST_USER_GROUPS_FOR_TEAM_WITH_OPTIONS",
    "SLACK_LIST_ALL_USERS_IN_A_USER_GROUP",
]

# ============================================================================
# CANVAS TOOLS
# ============================================================================
CANVAS_TOOLS = [
    "SLACK_CREATE_CANVAS",
    "SLACK_EDIT_CANVAS",
    "SLACK_GET_CANVAS",
    "SLACK_DELETE_CANVAS",
    "SLACK_LIST_CANVASES",
    "SLACK_LOOKUP_CANVAS_SECTIONS",
]

# ============================================================================
# WORKSPACE & TEAM INFO TOOLS
# ============================================================================
WORKSPACE_TOOLS = [
    "SLACK_FETCH_TEAM_INFO",
    "SLACK_FETCH_BOT_USER_INFORMATION",
    "SLACK_RETRIEVE_TEAM_PROFILE_DETAILS",
    "SLACK_SET_SLACK_USER_PROFILE_INFORMATION",
    "SLACK_SET_PROFILE_PHOTO",
    "SLACK_DELETE_USER_PROFILE_PHOTO",
    "SLACK_LIST_AUTH_TEAMS",
]

# ============================================================================
# REMOTE FILE TOOLS
# ============================================================================
REMOTE_FILE_TOOLS = [
    "SLACK_ADD_A_REMOTE_FILE_FROM_A_SERVICE",
    "SLACK_GET_REMOTE_FILE",
    "SLACK_LIST_REMOTE_FILES",
    "SLACK_REMOVE_A_REMOTE_FILE",
    "SLACK_UPDATES_AN_EXISTING_REMOTE_FILE",
    "SLACK_SHARE_REMOTE_FILE_IN_CHANNELS",
]

# ============================================================================
# EMOJI TOOLS
# ============================================================================
EMOJI_TOOLS = [
    "SLACK_ADD_EMOJI",
    "SLACK_ADD_AN_EMOJI_ALIAS_IN_SLACK",
    "SLACK_RENAME_AN_EMOJI",
    "SLACK_LIST_TEAM_CUSTOM_EMOJIS",
]

# ============================================================================
# COMBINED SLACK TOOLS (excludes all deprecated tools)
# ============================================================================
SLACK_TOOLS = (
    MESSAGING_TOOLS
    + CHANNEL_DISCOVERY_TOOLS
    + CHANNEL_MANAGEMENT_TOOLS
    + USER_DISCOVERY_TOOLS
    + DM_TOOLS
    + REACTION_TOOLS
    + FILE_TOOLS
    + PINS_STARS_TOOLS
    + REMINDER_TOOLS
    + STATUS_PRESENCE_TOOLS
    + USER_GROUP_TOOLS
    + CANVAS_TOOLS
    + WORKSPACE_TOOLS
    + REMOTE_FILE_TOOLS
    + EMOJI_TOOLS
)
