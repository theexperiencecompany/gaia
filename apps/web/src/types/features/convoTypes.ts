// Define the structure for each message in the conversation
// This type represents an individual message, including details about whether it's from the user or bot,

import type {
  CalendarOptions,
  ConversationMessage,
  DeepResearchResults,
  EmailComposeData,
  ImageData,
  SearchResults,
  WeatherData,
} from "./baseMessageTypes";
import type {
  EnhancedWebResult,
  ImageResult,
  NewsResult,
  WebResult,
} from "./searchTypes";

// Re-export types for external consumption
export type {
  CalendarOptions,
  ConversationMessage,
  DeepResearchResults,
  EmailComposeData,
  EnhancedWebResult,
  ImageData,
  ImageResult,
  NewsResult,
  SearchResults,
  WeatherData,
  WebResult,
};

// Message type using the base conversation message structure
export type MessageType = ConversationMessage;
