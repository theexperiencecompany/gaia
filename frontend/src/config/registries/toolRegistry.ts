import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  EmailThreadData,
  GoalDataMessageType,
  GoogleDocsData,
  SearchResults,
  TodoToolData,
  WeatherData,
} from "@/types";
import type {
  CalendarFetchData,
  CalendarListFetchData,
} from "@/types/features/calendarTypes";
import type {
  IntegrationConnectionData,
} from "@/types/features/integrationTypes";
import type {
  ContactData,
  EmailFetchData,
  EmailSentData,
  PeopleSearchData,
} from "@/types/features/mailTypes";
import type { NotificationRecord } from "@/types/features/notificationTypes";
import type { RedditData } from "@/types/features/redditTypes";
import type { SupportTicketData } from "@/types/features/supportTypes";

// Tool Registry
// Single source of truth for tool names and their data payload types.
// When you add a tool here, all downstream types (ToolName, ToolDataMap),
// message schemas, and UI renderers can infer the correct types automatically.
//
// Why `null as unknown as T`?
// - We want a value-level object (used at runtime for deriving keys) that also
//   carries precise compile-time types for each key.
// - Using `null` keeps runtime cost at zero; these values are never read.
// - Casting `null as unknown as T` tells TypeScript: “treat this value as T”
//   without needing to construct a real instance of T. The first cast to
//   `unknown` is required to legally cast from `null` to any specific type.
// - Result: strong static typing with no runtime overhead and a single place to
//   author tool types.
//
// Single source of truth
// - `TOOL_REGISTRY` defines all tool keys and their payload shapes.
// - `ToolName` is derived from its keys.
// - `ToolDataMap` maps each key to its payload type.
// - `TOOLS_MESSAGE_SCHEMA` (below) composes tool data into message schemas.
// - UI components (like renderers) can key off `ToolName` and get the exact
//   payload type for each tool.
//
// How to add a new tool
// 1) Add a new key here with its payload type using `null as unknown as YourType`.
// 2) If you have a renderer, register it in your renderer map keyed by the new tool name.
// 3) If you stream or store this tool’s data in messages, no extra typing is required;
//    the message schema derives from this registry.
// 4) Optionally, add tests and docs/examples demonstrating the new tool.
export const TOOL_REGISTRY = {
  search_results: null as unknown as SearchResults,
  deep_research_results: null as unknown as DeepResearchResults,
  weather_data: null as unknown as WeatherData,
  email_thread_data: null as unknown as EmailThreadData,
  email_fetch_data: null as unknown as EmailFetchData[],
  email_compose_data: null as unknown as EmailComposeData[],
  email_sent_data: null as unknown as EmailSentData[],
  contacts_data: null as unknown as ContactData[],
  people_search_data: null as unknown as PeopleSearchData[],
  calendar_options: null as unknown as CalendarOptions[],
  calendar_delete_options: null as unknown as CalendarDeleteOptions[],
  calendar_edit_options: null as unknown as CalendarEditOptions[],
  calendar_fetch_data: null as unknown as CalendarFetchData[],
  calendar_list_fetch_data: null as unknown as CalendarListFetchData[],
  support_ticket_data: null as unknown as SupportTicketData[],
  reddit_data: null as unknown as RedditData,
  document_data: null as unknown as DocumentData,
  google_docs_data: null as unknown as GoogleDocsData,
  code_data: null as unknown as CodeData,
  todo_data: null as unknown as TodoToolData,
  goal_data: null as unknown as GoalDataMessageType,
  notification_data: null as unknown as { notifications: NotificationRecord[] },
  integration_connection_required: null as unknown as IntegrationConnectionData,
  integration_list_data: null as unknown as Record<string, never>,
} as const;

export type ToolName = keyof typeof TOOL_REGISTRY;
export type ToolDataMap = { [K in ToolName]: (typeof TOOL_REGISTRY)[K] };

// Tools Message Schema
// Derived from TOOL_REGISTRY. Represents the tool-specific portion
// of a message. Used by the base message registry.
export interface ToolDataEntry {
  tool_name: ToolName;
  tool_category: string;
  data: ToolDataMap[ToolName];
  timestamp: string | null;
}

// Optional wrapper for tool data in messages
type ToolsMessageSchema = {
  tool_data?: ToolDataEntry[] | null;
};

export const TOOLS_MESSAGE_SCHEMA: ToolsMessageSchema = {};
export type ToolsMessageKey = keyof ToolsMessageSchema;
export type ToolsMessageData = ToolsMessageSchema;
export const TOOLS_MESSAGE_KEYS = Object.keys(
  TOOLS_MESSAGE_SCHEMA,
) as ToolsMessageKey[];

// Tools that should merge multiple calls into one component
// Add any tool name here - its data will be accumulated into an array
export const GROUPED_TOOLS = new Set<ToolName>([
  "reddit_data",
  // "email_fetch_data",
  // "test_data",
  // Add any tool you want to group here
]);
