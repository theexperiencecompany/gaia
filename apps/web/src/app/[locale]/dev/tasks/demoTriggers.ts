/**
 * The app events a task can start on: the API's workflow trigger schemas
 * (slug and app), named the way they read beside the app's logo.
 */
export interface DemoTrigger {
  slug: string;
  app: string;
  name: string;
}

export const APP_NAMES: Record<string, string> = {
  gmail: "Gmail",
  googlecalendar: "Google Calendar",
  github: "GitHub",
  linear: "Linear",
  slack: "Slack",
  notion: "Notion",
  googlesheets: "Google Sheets",
  googledocs: "Google Docs",
  todoist: "Todoist",
};

export const DEMO_TRIGGERS: DemoTrigger[] = [
  { slug: "gmail_new_message", app: "gmail", name: "New email" },
  { slug: "gmail_email_sent", app: "gmail", name: "Email sent" },
  { slug: "calendar_event_created", app: "googlecalendar", name: "New event" },
  {
    slug: "calendar_event_starting_soon",
    app: "googlecalendar",
    name: "Event starting soon",
  },
  { slug: "github_pr_event", app: "github", name: "Pull request updated" },
  { slug: "github_issue_added", app: "github", name: "New issue" },
  { slug: "github_commit_event", app: "github", name: "New commit" },
  { slug: "linear_issue_created", app: "linear", name: "New issue" },
  { slug: "linear_issue_updated", app: "linear", name: "Issue updated" },
  { slug: "linear_comment_added", app: "linear", name: "New comment" },
  { slug: "slack_new_message", app: "slack", name: "New message" },
  { slug: "notion_new_page_in_db", app: "notion", name: "New page" },
  { slug: "notion_page_updated", app: "notion", name: "Page updated" },
  { slug: "google_sheets_new_row", app: "googlesheets", name: "New row" },
  {
    slug: "google_docs_new_document",
    app: "googledocs",
    name: "New document",
  },
  { slug: "todoist_new_task_created", app: "todoist", name: "New task" },
];
