/**
 * Shared dummy data for landing page demo components
 */

import { DEMO_INTEGRATIONS } from "./integrations-demo/integrationsDemoConstants";

export interface DummyIntegration {
  id: string;
  name: string;
  status?: string;
}

export const dummyIntegrations: DummyIntegration[] = DEMO_INTEGRATIONS.map(
  ({ id, name }) => ({ id, name }),
);

// ─── Dummy tool registry (matches complete backend tool registry) ───────────

export interface DummyTool {
  name: string;
  category: string;
  required_integration: string | null;
}

export const dummyTools: {
  tools: DummyTool[];
  total_count: number;
  categories: string[];
} = {
  tools: [
    // Search tools (core)
    { name: "web_search_tool", category: "search", required_integration: null },
    { name: "fetch_webpages", category: "search", required_integration: null },
    // Documents tools (core)
    { name: "query_file", category: "documents", required_integration: null },
    {
      name: "generate_document",
      category: "documents",
      required_integration: null,
    },
    // Notifications tools
    {
      name: "get_notifications",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "search_notifications",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "get_notification_count",
      category: "notifications",
      required_integration: null,
    },
    {
      name: "mark_notifications_read",
      category: "notifications",
      required_integration: null,
    },
    // Productivity tools (todos + reminders)
    {
      name: "create_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_todo",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "search_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "semantic_search_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_todo_statistics",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_today_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_upcoming_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "create_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_projects",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_project",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_todos_by_label",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_all_labels",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_complete_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_move_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "bulk_delete_todos",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "add_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_subtask",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "create_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "list_user_reminders_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "get_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "delete_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "update_reminder_tool",
      category: "productivity",
      required_integration: null,
    },
    {
      name: "search_reminders_tool",
      category: "productivity",
      required_integration: null,
    },
    // Goal tracking tools
    {
      name: "create_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "list_goals",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "get_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "delete_goal",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "generate_roadmap",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "update_goal_node",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "search_goals",
      category: "goal_tracking",
      required_integration: null,
    },
    {
      name: "get_goal_statistics",
      category: "goal_tracking",
      required_integration: null,
    },
    // Support tools
    {
      name: "create_support_ticket",
      category: "support",
      required_integration: null,
    },
    // Memory tools
    { name: "add_memory", category: "memory", required_integration: null },
    { name: "search_memory", category: "memory", required_integration: null },
    // Development tools
    {
      name: "execute_code",
      category: "development",
      required_integration: null,
    },
    {
      name: "create_flowchart",
      category: "development",
      required_integration: null,
    },
    // Creative tools
    {
      name: "generate_image",
      category: "creative",
      required_integration: null,
    },
    // Weather tools
    { name: "get_weather", category: "weather", required_integration: null },
    // Calendar tools (requires integration)
    {
      name: "fetch_calendar_list",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "create_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "edit_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "fetch_calendar_events",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "search_calendar_events",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "view_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    {
      name: "delete_calendar_event",
      category: "googlecalendar",
      required_integration: "googlecalendar",
    },
    // Google Docs tools (requires integration)
    {
      name: "create_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "list_google_docs_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "get_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "update_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "format_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "share_google_doc_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    {
      name: "search_google_docs_tool",
      category: "googledocs",
      required_integration: "googledocs",
    },
    // Gmail tools (requires integration)
    {
      name: "gmail_search_emails",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_get_profile",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_create_email_draft",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_send_email",
      category: "gmail",
      required_integration: "gmail",
    },
    {
      name: "gmail_fetch_emails",
      category: "gmail",
      required_integration: "gmail",
    },
    // Notion tools (requires integration)
    {
      name: "notion_create_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_get_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_find_page",
      category: "notion",
      required_integration: "notion",
    },
    {
      name: "notion_update_page",
      category: "notion",
      required_integration: "notion",
    },
    // Twitter tools (requires integration)
    {
      name: "twitter_post_tweet",
      category: "twitter",
      required_integration: "twitter",
    },
    {
      name: "twitter_get_user_tweets",
      category: "twitter",
      required_integration: "twitter",
    },
    {
      name: "twitter_search_tweets",
      category: "twitter",
      required_integration: "twitter",
    },
    // LinkedIn tools (requires integration)
    {
      name: "linkedin_post_content",
      category: "linkedin",
      required_integration: "linkedin",
    },
    {
      name: "linkedin_get_profile",
      category: "linkedin",
      required_integration: "linkedin",
    },
    // Google Sheets tools (requires integration)
    {
      name: "google_sheets_create_spreadsheet",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
    {
      name: "google_sheets_get_values",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
    {
      name: "google_sheets_update_values",
      category: "googlesheets",
      required_integration: "googlesheets",
    },
  ],
  total_count: 109,
  categories: [
    "calendar",
    "creative",
    "development",
    "documents",
    "gmail",
    "goal_tracking",
    "googledocs",
    "googlesheets",
    "linkedin",
    "memory",
    "notifications",
    "notion",
    "productivity",
    "search",
    "support",
    "twitter",
    "weather",
  ],
};
