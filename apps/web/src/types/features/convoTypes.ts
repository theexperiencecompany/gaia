// Define the structure for each message in the conversation
// This type represents an individual message, including details about whether it's from the user or bot,

import type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  ConversationMessage,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  GoalDataMessageType,
  GoogleDocsData,
  ImageData,
  MemoryData,
  SearchResults,
  TodoToolData,
  WeatherData,
} from "./baseMessageTypes";
import type { CalendarEventDateTime } from "./calendarTypes";
import type {
  EnhancedWebResult,
  ImageResult,
  NewsResult,
  WebResult,
} from "./searchTypes";

// Re-export types for external consumption
export type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarEventDateTime,
  CalendarOptions,
  CodeData,
  ConversationMessage,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  EnhancedWebResult,
  GoalDataMessageType,
  GoogleDocsData,
  ImageData,
  ImageResult,
  MemoryData,
  NewsResult,
  SearchResults,
  TodoToolData,
  WeatherData,
  WebResult,
};

// Message type using the base conversation message structure
export type MessageType = ConversationMessage;
