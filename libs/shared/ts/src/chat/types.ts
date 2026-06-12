// Platform-agnostic chat types shared between web and mobile.
// Only pure data types live here — no DOM, no React Native, no React imports.

// ---------------------------------------------------------------------------
// Core message types
// ---------------------------------------------------------------------------

export interface ApiFileData {
  fileId: string;
  fileName?: string;
  fileSize?: number;
  contentType?: string;
  url?: string;
}

export interface ApiToolData {
  tool_name: string;
  data: Record<string, unknown>;
  timestamp?: string | null;
  tool_category?: string;
}

export interface ReplyToMessageData {
  id: string;
  content: string;
  role: "user" | "assistant";
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

export interface WebResult {
  title?: string;
  url?: string;
  content?: string;
  score?: number;
  raw_content?: string;
  favicon?: string;
  snippet?: string;
}

export interface NewsResult {
  title?: string;
  url?: string;
  content?: string;
  score?: number;
  raw_content?: string;
  favicon?: string;
  published_date?: string;
  source?: string;
}

export type ImageResult = string;

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

export interface EnhancedWebResult extends WebResult {
  full_content?: string;
  screenshot_url?: string;
}

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

export interface EmailComposeData {
  to: string[];
  subject: string;
  body: string;
  draft_id?: string;
  thread_id?: string;
  bcc?: string[];
  cc?: string[];
  is_html?: boolean;
}

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

export interface EmailFetchData {
  from: string;
  subject: string;
  time: string;
  thread_id?: string;
  id: string;
  from_name?: string;
  snippet?: string;
  date?: string;
  is_unread?: boolean;
}

export interface EmailThreadMessage {
  id?: string;
  from?: string;
  from_name?: string;
  subject?: string;
  time?: string;
  snippet?: string;
  body?: string;
  date?: string;
  content?: { text: string; html: string };
}

export interface EmailThreadData {
  thread_id?: string;
  subject?: string;
  messages?: EmailThreadMessage[];
  messages_count?: number;
}

export interface ContactData {
  name?: string;
  email?: string;
  phone?: string;
  resource_name?: string;
}

export interface PeopleSearchData {
  name?: string;
  email?: string;
  phone?: string;
  organization?: string;
  role?: string;
  resource_name?: string;
}

// ---------------------------------------------------------------------------
// Calendar
// ---------------------------------------------------------------------------

export interface RecurrenceRule {
  frequency: "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";
  interval?: number;
  count?: number;
  until?: string;
  by_day?: string[];
  by_month_day?: number[];
  by_month?: number[];
  exclude_dates?: string[];
  include_dates?: string[];
}

export interface RecurrenceData {
  rrule: RecurrenceRule;
}

export interface CalendarEventDateTime {
  date?: string;
  dateTime?: string;
  timeZone?: string;
}

export interface SameDayEvent {
  id: string;
  summary: string;
  start?: CalendarEventDateTime;
  end?: CalendarEventDateTime;
  description?: string;
  location?: string;
  attendees?: Array<{
    email: string;
    responseStatus?: string;
    organizer?: boolean;
  }>;
  recurrence?: string[];
  status?: string;
  calendarId?: string;
  calendarTitle?: string;
  background_color?: string;
}

export interface CalendarOptions {
  summary: string;
  description?: string;
  start?: string;
  end?: string;
  calendar_id?: string;
  calendar_name?: string;
  background_color?: string;
  is_all_day?: boolean;
  recurrence?: RecurrenceData;
  attendees?: string[];
  create_meeting_room?: boolean;
  same_day_events?: SameDayEvent[];
  // Additional fields from mobile usage
  title?: string;
  location?: string;
}

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

export interface CalendarFetchData {
  summary: string;
  start_time: string;
  end_time: string;
  calendar_name: string;
  background_color: string;
}

export interface CalendarListFetchData {
  name: string;
  id: string;
  description: string;
  backgroundColor?: string;
}

// ---------------------------------------------------------------------------
// Reddit
// ---------------------------------------------------------------------------

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

export interface RedditCommentData {
  id?: string;
  author?: string;
  body?: string;
  score?: number;
  created_utc?: number;
  permalink?: string;
  is_submitter?: boolean;
}

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

export interface RedditPostCreatedData {
  id?: string;
  url?: string;
  message?: string;
  permalink?: string;
}

export interface RedditCommentCreatedData {
  id?: string;
  message?: string;
  permalink?: string;
}

export type RedditData =
  | { type: "search"; posts: RedditSearchData[] }
  | { type: "post"; post: RedditPostData }
  | { type: "comments"; comments: RedditCommentData[] }
  | { type: "post_created"; data: RedditPostCreatedData }
  | { type: "comment_created"; data: RedditCommentCreatedData };

// ---------------------------------------------------------------------------
// Twitter / X
// ---------------------------------------------------------------------------

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

export interface TwitterSearchData {
  tweets: TwitterTweetData[];
  result_count: number;
  next_token?: string;
}

export interface TwitterTimelineData {
  tweets: TwitterTweetData[];
}

export type TwitterFollowersData = TwitterUserData[];

export interface TwitterPostCreatedData {
  id: string;
  text: string;
  url: string;
}

export interface TwitterPostPreviewData {
  text: string;
  quote_tweet_id?: string;
  reply_to_tweet_id?: string;
  media_ids?: string[];
  poll_options?: string[];
}

export type TwitterData =
  | { type: "search"; data: TwitterSearchData }
  | { type: "timeline"; data: TwitterTimelineData }
  | { type: "users"; data: TwitterUserData[] }
  | { type: "followers"; data: TwitterFollowersData }
  | { type: "following"; data: TwitterFollowersData }
  | { type: "post_created"; data: TwitterPostCreatedData }
  | { type: "post_preview"; data: TwitterPostPreviewData };

// ---------------------------------------------------------------------------
// Todos (agent task planning)
// ---------------------------------------------------------------------------

export type TodoProgressStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface TodoProgressItem {
  id: string;
  content: string;
  status: TodoProgressStatus;
}

export interface TodoProgressSnapshot {
  todos?: TodoProgressItem[];
  source?: string;
}

export type TodoProgressData = Record<string, TodoProgressSnapshot>;

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

export interface TodoToolData {
  todos?: TodoItem[];
  projects?: TodoProject[];
  stats?: TodoToolStats;
  action?: TodoAction;
  message?: string;
}

// ---------------------------------------------------------------------------
// Goals
// ---------------------------------------------------------------------------

export interface GoalRoadmapNode {
  id: string;
  data: {
    id?: string;
    title?: string;
    label?: string;
    isComplete?: boolean;
    type?: string;
    subtask_id?: string;
  };
}

export interface GoalRoadmap {
  nodes?: GoalRoadmapNode[];
  edges?: Array<{
    id: string;
    source: string;
    target: string;
  }>;
}

export interface GoalItem {
  id: string;
  title: string;
  description?: string;
  progress?: number;
  roadmap?: GoalRoadmap;
  created_at?: string;
  todo_project_id?: string;
  todo_id?: string;
}

export interface GoalStats {
  total_goals: number;
  goals_with_roadmaps: number;
  total_tasks: number;
  completed_tasks: number;
  overall_completion_rate: number;
  active_goals: Array<{
    id: string;
    title: string;
    progress: number;
  }>;
  active_goals_count: number;
}

export interface GoalDataMessageType {
  goals?: GoalItem[];
  action?: string;
  message?: string;
  goal_id?: string;
  deleted_goal_id?: string;
  stats?: GoalStats;
  error?: string;
}

// ---------------------------------------------------------------------------
// Documents & Code
// ---------------------------------------------------------------------------

export interface CodeOutput {
  stdout?: string;
  stderr?: string;
  results?: string[];
  error?: string | null;
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
  language?: string;
  code?: string;
  output?: CodeOutput | null;
  charts?: CodeChartData[] | null;
  status?: "executing" | "completed" | "error";
  error?: string;
}

// ---------------------------------------------------------------------------
// Google Docs
// ---------------------------------------------------------------------------

export interface GoogleDocsDocument {
  id?: string;
  title?: string;
  url?: string;
  created_time?: string;
  modified_time?: string;
  type?: string;
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

export interface WorkflowDraftData {
  suggested_title: string;
  suggested_description: string;
  prompt: string;
  trigger_type: "manual" | "scheduled" | "integration";
  trigger_slug?: string | null;
  cron_expression?: string | null;
}

export interface WorkflowCreatedData {
  id: string;
  title: string;
  description: string;
  trigger_config: {
    type: "manual" | "scheduled" | "integration";
    cron_expression?: string | null;
    trigger_name?: string | null;
    enabled?: boolean;
  };
  activated: boolean;
}

// ---------------------------------------------------------------------------
// Artifacts
// ---------------------------------------------------------------------------

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

export interface RateLimitData {
  feature: string;
  plan_required?: string;
  reset_time?: string;
}

// ---------------------------------------------------------------------------
// MCP App
// ---------------------------------------------------------------------------

export interface MCPAppData {
  tool_call_id: string;
  tool_name: string;
  server_url: string;
  resource_uri: string;
  html_content: string;
  csp?: {
    connectDomains?: string[];
    resourceDomains?: string[];
  };
  permissions?: string[];
  tool_result?: unknown;
  tool_arguments?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Tool calls data (progress entries)
// ---------------------------------------------------------------------------

export interface ToolCallEntry {
  tool_name: string;
  tool_category: string;
  message: string;
  show_category?: boolean;
  tool_call_id?: string;
  inputs?: Record<string, unknown>;
  output?: string;
  icon_url?: string;
  integration_name?: string;
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
  | "send_notification_data"
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

export type GenericToolData = Record<string, unknown>;

export interface ToolDataMap {
  email_compose_data: EmailComposeData[];
  email_sent_data: EmailSentData[];
  email_fetch_data: EmailFetchData[];
  email_thread_data: EmailThreadData;
  weather_data: WeatherData;
  calendar_options: CalendarOptions[];
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
  goal_data: GoalDataMessageType;
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
  memory_data: SharedMemoryData;
  todo_progress: TodoProgressData;
  chart_data: GenericToolData[];
}

export interface ToolDataEntry {
  tool_name: ToolName | string;
  tool_category?: string;
  data: ToolDataMap[ToolName] | unknown;
  timestamp?: string | null;
}

export function isKnownTool(name: string): name is ToolName {
  const knownTools = new Set<string>([
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
    "send_notification_data",
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
