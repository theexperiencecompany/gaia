// Platform-agnostic chat types shared between web and mobile.
// Only pure data types live here — no DOM, no React Native, no React imports.

// ---------------------------------------------------------------------------
// Core message types
// ---------------------------------------------------------------------------

import type {
  CalendarEventDisplay,
  CalendarListCard,
  ContactCard,
  EmailListItem,
  EmailThreadCard,
  EmailThreadItem,
  GoogleCalendarEventDateTime,
  McpAppData,
  SearchResultItem,
  TodoProgressCard,
  TodoProgressItem,
  TodoProgressSnapshot,
  ToolCardEnvelope,
  ToolProgress,
  WorkflowCreatedData,
  WorkflowDraftData,
} from "../api/generated";
import type { ArtifactCardData } from "../artifacts/types";

export type {
  RecurrenceData,
  RecurrenceRule,
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

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface WeatherData {
  coord?: { lon: number; lat: number };
  weather?: Array<{
    id: number;
    main: string;
    description: string;
    icon: string;
  }>;
  base?: string;
  main?: {
    temp: number;
    feels_like: number;
    temp_min: number;
    temp_max: number;
    pressure: number;
    humidity: number;
    sea_level?: number;
    grnd_level?: number;
  };
  visibility?: number;
  wind?: {
    speed: number;
    deg: number;
    gust?: number;
  };
  clouds?: { all: number };
  dt?: number;
  sys?: {
    country: string;
    sunrise: number;
    sunset: number;
  };
  timezone?: number;
  id?: number;
  name?: string;
  cod?: number;
  location?: {
    city: string;
    country: string | null;
    region: string | null;
  };
  forecast?: Array<{
    date: string;
    timestamp: number;
    temp_min: number;
    temp_max: number;
    humidity: number;
    weather: {
      main: string;
      description: string;
      icon: string;
    };
  }>;
  // Flat fallback fields (used in older/simplified tool output)
  temperature?: number;
  condition?: string;
  humidity?: number;
  wind_speed?: number;
  unit?: string;
}

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

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface EmailComposeData {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
  /** Display-only: the backend streams each file's name and mimetype, never its s3key. */
  attachments?: Array<{ name: string; mimetype: string }>;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface EmailSentData {
  to?: string[];
  subject?: string;
  body?: string;
  message_id?: string;
  message?: string;
  timestamp?: string;
  sent_at?: string;
  recipients?: string[];
}

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

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RedditPostData {
  id?: string;
  title?: string;
  author?: string;
  subreddit?: string;
  score?: number;
  upvote_ratio?: number;
  num_comments?: number;
  created_utc?: number;
  selftext?: string;
  url?: string;
  permalink?: string;
  is_self?: boolean;
  link_flair_text?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RedditCommentData {
  id?: string;
  author?: string;
  body?: string;
  score?: number;
  created_utc?: number;
  permalink?: string;
  is_submitter?: boolean;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RedditSearchData {
  id?: string;
  title?: string;
  author?: string;
  subreddit?: string;
  score?: number;
  num_comments?: number;
  created_utc?: number;
  permalink?: string;
  url?: string;
  selftext?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RedditPostCreatedData {
  id?: string;
  url?: string;
  message?: string;
  permalink?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RedditCommentCreatedData {
  id?: string;
  message?: string;
  permalink?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export type RedditData =
  | { type: "search"; posts: RedditSearchData[] }
  | { type: "post"; post: RedditPostData }
  | { type: "comments"; comments: RedditCommentData[] }
  | { type: "post_created"; data: RedditPostCreatedData }
  | { type: "comment_created"; data: RedditCommentCreatedData };

// ---------------------------------------------------------------------------
// Twitter / X
// ---------------------------------------------------------------------------

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface TwitterUserData {
  id: string;
  username: string;
  name: string;
  description?: string;
  profile_image_url?: string;
  verified?: boolean;
  public_metrics?: {
    followers_count?: number;
    following_count?: number;
    tweet_count?: number;
    listed_count?: number;
  };
  created_at?: string;
  location?: string;
  url?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface TwitterTweetData {
  id: string;
  text: string;
  created_at?: string;
  author: TwitterUserData;
  public_metrics?: {
    retweet_count?: number;
    reply_count?: number;
    like_count?: number;
    quote_count?: number;
    bookmark_count?: number;
    impression_count?: number;
  };
  conversation_id?: string;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface TwitterSearchData {
  tweets: TwitterTweetData[];
  result_count: number;
  next_token?: string;
}

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

export type TodoPriority = "high" | "medium" | "low" | "none";

export type TodoAction =
  | "list"
  | "create"
  | "update"
  | "delete"
  | "search"
  | "stats";

export interface TodoSubtask {
  id: string;
  title: string;
  completed: boolean;
}

export interface TodoProject {
  id: string;
  name: string;
  description?: string;
  color?: string;
  is_default?: boolean;
  todo_count?: number;
  completion_percentage?: number;
}

export interface TodoItem {
  id: string;
  title: string;
  description?: string;
  completed: boolean;
  priority: TodoPriority;
  labels: string[];
  due_date?: string;
  due_date_timezone?: string;
  project_id?: string;
  project?: TodoProject;
  subtasks: TodoSubtask[];
  created_at?: string;
  updated_at?: string;
}

export interface TodoToolStats {
  total: number;
  completed: number;
  pending: number;
  overdue: number;
  today: number;
  upcoming: number;
}

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface TodoToolData {
  todos?: TodoItem[];
  projects?: TodoProject[];
  stats?: TodoToolStats;
  action?: TodoAction;
  message?: string;
}

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

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface ArtifactData {
  path: string;
  filename: string;
  content_type: string;
  size_bytes: number;
}

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

// apps/mobile still reads this hand copy; the web reads the generated type.
export interface RateLimitData {
  feature: string;
  plan_required?: string;
  reset_time?: string;
  /** The user's actual plan (e.g. "free", "pro"). Lets a card suppress the
   *  upgrade pitch for a user already on the top tier. */
  current_plan?: string;
  /** Backend-provided explanation; overrides the card's generic copy (used
   *  when a feature is capped rather than plan-gated, e.g. the memory cap). */
  message?: string;
}

// ---------------------------------------------------------------------------
// MCP App
// ---------------------------------------------------------------------------

export type MCPAppData = McpAppData;

// ---------------------------------------------------------------------------
// Tool calls data (progress entries)
// ---------------------------------------------------------------------------

/** One tool call of a run: the progress line the server states for it, plus the call itself. */
export interface ToolCallEntry
  extends Pick<ToolProgress, "tool_name" | "tool_category" | "message"> {
  show_category?: boolean;
  tool_call_id?: string;
  inputs?: Record<string, unknown>;
  output?: string;
  /** Set when the server cut output: how many characters the tool returned. */
  output_original_length?: number;
  icon_url?: string;
  integration_name?: string;
  // When set, this entry is the model's thinking for the step (not a tool call).
  // It rides the same ordered tool_calls stream so it interleaves between steps.
  reasoning?: string;
}

// tool_name marker for a thinking/reasoning step (a ToolCallEntry with `reasoning`).
export const REASONING_TOOL_NAME = "reasoning";

// tool_name marker for a subagent group entry in tool_data.
export const SUBAGENT_GROUP_TOOL_NAME = "subagent_group";

// The browser tool and the category its own actions carry. Mirrors
// the browser_task tool and BROWSER_TOOL_CATEGORY in app/constants/browser.py — the
// call and the "Browser" group it opens are matched by these on the client.
export const BROWSER_TASK_TOOL_NAME = "browser_task";
export const BROWSER_TOOL_CATEGORY = "browser";

/** A subagent's row as the client folds it from its start, tool calls and end frames. */
export interface SubagentGroupData {
  subagent_id: string;
  subagent_name: string;
  agent_type: "handoff" | "spawned";
  started_at: string;
  /** Accumulated tool calls from this subagent, in order of emission */
  tool_calls: ToolCallEntry[];
  duration_ms: number | null;
  token_count: number | null;
  completed_at: string | null;
  /** Integration icon URL forwarded from the backend */
  icon_url: string | null;
  /** Integration category ID used for icon lookup (e.g. "gmail", "googlecalendar") */
  tool_category: string | null;
  /** Spawned subagents launched from within this subagent (nested in the UI) */
  nested_subagents: SubagentGroupData[];
}

// ---------------------------------------------------------------------------
// Tool registry — canonical ToolName and ToolDataMap
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

export type GenericToolData = Record<string, unknown>;

export interface ToolDataMap {
  email_compose_data: EmailComposeData[];
  email_sent_data: EmailSentData[];
  email_fetch_data: EmailFetchData[];
  email_thread_data: EmailThreadData;
  weather_data: WeatherData;
  calendar_delete_options: CalendarDeleteOptions[];
  calendar_edit_options: CalendarEditOptions[];
  calendar_fetch_data: CalendarFetchData[];
  calendar_list_fetch_data: CalendarListFetchData[];
  search_results: SearchResults;
  deep_research_results: DeepResearchResults;
  contacts_data: ContactData[];
  people_search_data: PeopleSearchData[];
  support_ticket_data: GenericToolData[];
  notification_data: GenericToolData;
  send_notification_data: GenericToolData;
  google_docs_data: GoogleDocsData;
  code_data: CodeData;
  todo_data: TodoToolData;
  integration_connection_required: GenericToolData;
  integration_list_data: GenericToolData;
  connection_status_data: GenericToolData;
  reddit_data: RedditData;
  tool_calls_data: ToolCallEntry[];
  twitter_search_data: TwitterSearchData;
  twitter_user_data: TwitterUserData[];
  workflow_draft: WorkflowDraftData;
  workflow_created: WorkflowCreatedData;
  mcp_app: MCPAppData;
  rate_limit_data: RateLimitData;
  artifact_data: ArtifactData[];
  artifact_done: ArtifactCardData;
  memory_data: SharedMemoryData;
  todo_progress: TodoProgressData;
  chart_data: GenericToolData[];
}

export function isKnownTool(name: string): name is ToolName {
  const knownTools = new Set<string>([
    "email_compose_data",
    "email_sent_data",
    "email_fetch_data",
    "email_thread_data",
    "weather_data",
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
    "send_notification_data",
    "google_docs_data",
    "code_data",
    "todo_data",
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
    "artifact_done",
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
