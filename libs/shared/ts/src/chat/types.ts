// Platform-agnostic chat types shared between web and mobile.
// Only pure data types live here — no DOM, no React Native, no React imports.

// ---------------------------------------------------------------------------
// Core message types
// ---------------------------------------------------------------------------

import type {
  ArtifactDataCard,
  CalendarEventDisplay,
  CalendarListCard,
  ContactCard,
  EmailComposeCard,
  EmailListItem,
  EmailSentDataCard,
  EmailThreadCard,
  EmailThreadItem,
  GoogleCalendarEventDateTime,
  McpAppData,
  RateLimitCardData,
  RedditDataCard,
  SearchResultItem,
  SubagentGroupCardData,
  TodoCardData,
  TodoProgressCard,
  TodoProgressItem,
  TodoProgressSnapshot,
  ToolCallReasoningStep,
  ToolCallsDataEntryData,
  ToolCardEnvelope,
  TwitterSearchCard,
  TwitterSearchTweet,
  TwitterUserCard,
  WeatherReport,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "../api/generated";

export type {
  RecurrenceData,
  RecurrenceRule,
  RedditCardComment as RedditCommentData,
  RedditCardCommentCreated as RedditCommentCreatedData,
  RedditCardPost as RedditPostData,
  RedditCardPostCreated as RedditPostCreatedData,
  RedditCardSearchPost as RedditSearchData,
  ReplyToMessageData,
} from "../api/generated";

/** A card of any tool name, as apps/mobile builds and reads it; the web reads the generated per-tool ToolDataEntry. */
export type ToolDataEntry = ToolCardEnvelope;

export interface ApiFileData {
  fileId: string;
  fileName?: string;
  fileSize?: number;
  contentType?: string;
  url?: string;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  is_starred?: boolean;
  is_unread?: boolean;
}

export interface GroupedConversations {
  starred: Conversation[];
  today: Conversation[];
  yesterday: Conversation[];
  lastWeek: Conversation[];
  last30Days: Conversation[];
  older: Conversation[];
}

// ---------------------------------------------------------------------------
// Weather
// ---------------------------------------------------------------------------

export type WeatherData = WeatherReport;

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

/** A search_results web item: webpage_tool.py streams serialized SearchResultItem models. */
export type WebResult = SearchResultItem & {
  /** Legacy keys: only results stored before the search engine rewrite carry them. */
  raw_content?: string;
  snippet?: string;
};

export type NewsResult = SearchResultItem;

export type ImageResult = string;

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface SearchResults {
  web?: WebResult[];
  images?: ImageResult[];
  news?: NewsResult[];
  answer?: string;
  query?: string;
  response_time?: number;
  request_id?: string;
  // Streaming status fields
  status?: "running" | "complete" | "error";
  progress?: string;
}

export type EnhancedWebResult = WebResult & {
  full_content?: string;
  screenshot_url?: string;
};

export interface DeepResearchSource {
  url: string;
  title: string;
  snippet?: string;
}

export interface DeepResearchResults {
  original_search?: SearchResults;
  enhanced_results?: EnhancedWebResult[];
  screenshots_taken?: boolean;
  metadata?: {
    total_content_size?: number;
    elapsed_time?: number;
    query?: string;
  };
  // Streaming progress fields
  status?: "running" | "complete" | "error";
  progress?: string;
  subSteps?: string[];
  sources?: DeepResearchSource[];
  totalSources?: number;
}

// ---------------------------------------------------------------------------
// Email / Mail
// ---------------------------------------------------------------------------

export type EmailComposeData = EmailComposeCard;

/** One email_sent_data item: the composed email, or the draft-sent confirmation. */
export type EmailSentData = EmailSentDataCard["data"][number];

/** One fetched email; the optional keys only cards stored before the typed payload carry. */
export type EmailFetchData = EmailListItem & {
  from_name?: string;
  snippet?: string;
  date?: string;
  is_unread?: boolean;
};

export type EmailThreadMessage = EmailThreadItem;

export type EmailThreadData = EmailThreadCard;

export type ContactData = ContactCard;

/** One person found; organization and role only cards stored before the typed payload carry. */
export type PeopleSearchData = ContactCard & {
  organization?: string;
  role?: string;
};

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export type CalendarEventDateTime = GoogleCalendarEventDateTime;

export interface CalendarDeleteOptions {
  action: "delete";
  event_id: string;
  calendar_id: string;
  calendar_name?: string;
  background_color?: string;
  summary: string;
  description?: string;
  start?: CalendarEventDateTime;
  end?: CalendarEventDateTime;
  original_query: string;
  // Mobile-compatible optional versions
  title?: string;
}

export interface CalendarEditOptions {
  action: "edit";
  event_id: string;
  calendar_id: string;
  calendar_name?: string;
  background_color?: string;
  original_summary: string;
  original_description?: string;
  original_start?: CalendarEventDateTime;
  original_end?: CalendarEventDateTime;
  original_query: string;
  summary?: string;
  description?: string;
  start?: string;
  end?: string;
  is_all_day?: boolean;
  timezone?: string;
}

export type CalendarFetchData = CalendarEventDisplay;

export type CalendarListFetchData = CalendarListCard;

// ---------------------------------------------------------------------------
// Reddit
// ---------------------------------------------------------------------------

/** One reddit_data card: a search, a post, its comments, or a post or comment the user created. */
export type RedditData = RedditDataCard["data"];

// ---------------------------------------------------------------------------
// Twitter / X
// ---------------------------------------------------------------------------

export type TwitterUserData = TwitterUserCard;

export type TwitterTweetData = TwitterSearchTweet;

export type TwitterSearchData = TwitterSearchCard;

// ---------------------------------------------------------------------------
// Todos (agent task planning)
// ---------------------------------------------------------------------------

export type TodoProgressStatus = TodoProgressItem["status"];

export type { TodoProgressItem, TodoProgressSnapshot };

/** Accumulated todo_progress data on a message, keyed by source agent; each source replaces its own slice. */
export type TodoProgressData = TodoProgressCard["data"];

// ---------------------------------------------------------------------------
// Todo tool data (user's personal todos)
// ---------------------------------------------------------------------------

export type TodoToolData = TodoCardData;

// ---------------------------------------------------------------------------
// Documents & Code
// ---------------------------------------------------------------------------

export interface CodeOutput {
  stdout: string;
  stderr: string;
  results: string[];
  error: string | null;
}

export interface CodeChartData {
  id: string;
  url: string;
  text: string;
  type?: string;
  title?: string;
  description?: string;
  chart_data?: {
    type: string;
    title: string;
    x_label: string;
    y_label: string;
    x_unit?: string | null;
    y_unit?: string | null;
    elements: Array<{
      label: string;
      value: number;
      group: string;
    }>;
  };
}

export interface CodeData {
  language: string;
  code: string;
  output?: CodeOutput | null;
  charts?: CodeChartData[] | null;
  status?: "executing" | "completed" | "error";
  error?: string;
}

// ---------------------------------------------------------------------------
// Google Docs
// ---------------------------------------------------------------------------

export interface GoogleDocsDocument {
  id: string;
  title: string;
  url: string;
  created_time: string;
  modified_time: string;
  type: string;
}

export interface GoogleDocsData {
  document?: GoogleDocsDocument;
  query?: string | null;
  action?: string;
  message?: string;
  type?: string;
  // Legacy flat fields
  documentId?: string;
  title?: string;
  url?: string;
}

// ---------------------------------------------------------------------------
// Workflows
// ---------------------------------------------------------------------------

export type { WorkflowCreatedData, WorkflowDraftData };

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

/** One artifact_data event: a file the agent wrote, or one it removed. */
export type ArtifactData = ArtifactDataCard["data"];

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface SharedMemoryData {
  operation?: string;
  status?: string;
  results?: Array<{
    id: string;
    content: string;
    relevance_score?: number;
    metadata?: Record<string, unknown>;
  }>;
  memories?: Array<{
    id: string;
    content: string;
    metadata?: Record<string, unknown>;
    created_at?: string;
  }>;
  count?: number;
  content?: string;
  memory_id?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// Rate limit
// ---------------------------------------------------------------------------

export type RateLimitData = RateLimitCardData;

// ---------------------------------------------------------------------------
// MCP App
// ---------------------------------------------------------------------------

export type MCPAppData = McpAppData;

// ---------------------------------------------------------------------------
// Tool calls data (progress entries)
// ---------------------------------------------------------------------------

/** One tool_calls_data entry: a tool call with its progress line, or a thinking step between calls. */
export type ToolCallEntry = ToolCallsDataEntryData | ToolCallReasoningStep;

// tool_name marker for a thinking/reasoning step (a ToolCallEntry with `reasoning`).
export const REASONING_TOOL_NAME = "reasoning";

// tool_name marker for a subagent group entry in tool_data.
export const SUBAGENT_GROUP_TOOL_NAME = "subagent_group";

// The browser tool and the category its own actions carry. Mirrors
// the browser_task tool and BROWSER_TOOL_CATEGORY in app/constants/browser.py — the
// call and the "Browser" group it opens are matched by these on the client.
export const BROWSER_TASK_TOOL_NAME = "browser_task";
export const BROWSER_TOOL_CATEGORY = "browser";

export type SubagentGroupData = SubagentGroupCardData;

// ---------------------------------------------------------------------------
// Tool registry — canonical ToolName
// ---------------------------------------------------------------------------

export type ToolName =
  | "email_compose_data"
  | "email_sent_data"
  | "email_fetch_data"
  | "email_thread_data"
  | "weather_data"
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
  | "send_notification_data"
  | "google_docs_data"
  | "code_data"
  | "todo_data"
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
  | "artifact_done"
  | "memory_data"
  | "todo_progress"
  | "chart_data";
