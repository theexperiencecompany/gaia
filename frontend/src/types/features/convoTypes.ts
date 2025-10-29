// Define the structure for each message in the conversation
// This type represents an individual message, including details about whether it's from the user or bot,

import {
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
import { CalendarEventDateTime } from "./calendarTypes";
import {
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

// Define the structure for a single conversation
// This type represents an individual conversation, with a description and an array of messages.
export type ConversationType = {
  description: string; // A description or title of the conversation
  messages: MessageType[]; // An array of MessageType, representing the messages exchanged in the conversation
};
