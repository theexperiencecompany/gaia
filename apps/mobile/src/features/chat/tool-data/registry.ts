export type ToolName =
  | "email_compose_data"
  | "email_sent_data"
  | "email_fetch_data"
  | "email_thread_data"
  | "weather_data"
  | "calendar_options"
  | "calendar_delete_options"
  | "calendar_edit_options"
  | "calendar_fetch_data"
  | "calendar_list_fetch_data"
  | "search_results"
  | "deep_research_results"
  | "contacts_data"
  | "people_search_data"
  | "support_ticket_data"
  | "notification_data"
  | "document_data"
  | "google_docs_data"
  | "code_data"
  | "todo_data"
  | "goal_data"
  | "integration_connection_required"
  | "integration_list_data"
  | "connection_status_data"
  | "reddit_data"
  | "tool_calls_data"
  | "twitter_search_data"
  | "twitter_user_data"
  | "workflow_draft"
  | "workflow_created"
  | "mcp_app"
  | "rate_limit_data"
  | "artifact_data"
  | "memory_data"
  | "todo_progress"
  | "chart_data";

export interface EmailComposeData {
  to: string[];
  subject: string;
  body: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
}

export interface EmailSentData {
  to: string[];
  subject: string;
  message_id?: string;
  sent_at?: string;
}

export interface WeatherData {
  location: string;
  temperature?: number;
  condition?: string;
  humidity?: number;
  wind_speed?: number;
}

export type GenericToolData = Record<string, unknown>;

export interface ToolDataMap {
  email_compose_data: EmailComposeData[];
  email_sent_data: EmailSentData[];
  email_fetch_data: GenericToolData[];
  email_thread_data: GenericToolData;
  weather_data: WeatherData;
  calendar_options: GenericToolData[];
  calendar_delete_options: GenericToolData[];
  calendar_edit_options: GenericToolData[];
  calendar_fetch_data: GenericToolData[];
  calendar_list_fetch_data: GenericToolData[];
  search_results: GenericToolData;
  deep_research_results: GenericToolData;
  contacts_data: GenericToolData[];
  people_search_data: GenericToolData[];
  support_ticket_data: GenericToolData[];
  notification_data: GenericToolData;
  document_data: GenericToolData;
  google_docs_data: GenericToolData;
  code_data: GenericToolData;
  todo_data: GenericToolData;
  goal_data: GenericToolData;
  integration_connection_required: GenericToolData;
  integration_list_data: GenericToolData;
  connection_status_data: GenericToolData;
  reddit_data: GenericToolData;
  tool_calls_data: GenericToolData[];
  twitter_search_data: GenericToolData;
  twitter_user_data: GenericToolData[];
  workflow_draft: GenericToolData;
  workflow_created: GenericToolData;
  mcp_app: GenericToolData;
  rate_limit_data: GenericToolData;
  artifact_data: GenericToolData[];
  memory_data: GenericToolData;
  todo_progress: GenericToolData;
  chart_data: GenericToolData[];
}

export interface ToolDataEntry {
  tool_name: string;
  tool_category?: string;
  data: ToolDataMap[ToolName] | unknown;
  timestamp?: string | null;
}

export function isKnownTool(name: string): name is ToolName {
  const knownTools: Set<string> = new Set([
    "email_compose_data",
    "email_sent_data",
    "email_fetch_data",
    "email_thread_data",
    "weather_data",
    "calendar_options",
    "calendar_delete_options",
    "calendar_edit_options",
    "calendar_fetch_data",
    "calendar_list_fetch_data",
    "search_results",
    "deep_research_results",
    "contacts_data",
    "people_search_data",
    "support_ticket_data",
    "notification_data",
    "document_data",
    "google_docs_data",
    "code_data",
    "todo_data",
    "goal_data",
    "integration_connection_required",
    "integration_list_data",
    "connection_status_data",
    "reddit_data",
    "tool_calls_data",
    "twitter_search_data",
    "twitter_user_data",
    "workflow_draft",
    "workflow_created",
    "mcp_app",
    "rate_limit_data",
    "artifact_data",
    "memory_data",
    "todo_progress",
    "chart_data",
  ]);
  return knownTools.has(name);
}

export function getToolData<K extends ToolName>(
  entry: ToolDataEntry,
  toolName: K,
): ToolDataMap[K] | undefined {
  if (entry.tool_name === toolName) {
    return entry.data as ToolDataMap[K];
  }
  return undefined;
}
