import type { ActivityToolCall } from "./activity-format.types";

/**
 * Human titles for the tools users actually see while they run
 * ("Checking email…"), matching decisions §2. Unmapped tools fall back to
 * their formatted name.
 */
const TOOL_TITLES: Record<string, string> = {
  web_search: "Searching the web",
  web_fetch: "Reading a page",
  email_search: "Checking email",
  email_fetch: "Checking email",
  read_email: "Reading email",
  send_email: "Sending email",
  reply_email: "Replying to email",
  calendar_list_events: "Checking calendar",
  calendar_create_event: "Creating event",
  calendar_delete_event: "Deleting event",
  calendar_edit_event: "Editing event",
  weather_search: "Checking weather",
  memory_create: "Storing memory",
  memory_search: "Searching memories",
  memory_list: "Retrieving memories",
  todo_create: "Adding todos",
  todo_list: "Checking todos",
  workflow_create: "Setting up workflow",
};

function formatToolName(toolName: string): string {
  return toolName
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\s+tool$/i, "")
    .trim();
}

/** Title a tool row: mobile copy, else the backend label, and the raw tool name only as a last resort. */
export function humanToolTitle(call: ActivityToolCall): string {
  const toolName = call.tool_name;
  if (!toolName) return "Thinking";
  const key = toolName.toLowerCase().replace(/[\s-]+/g, "_");
  return TOOL_TITLES[key] ?? call.message ?? formatToolName(toolName);
}
