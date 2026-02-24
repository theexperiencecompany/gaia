// Define the structure for each message in the conversation
// This type represents an individual message, including details about whether it's from the user or bot,

import type {
  CalendarOptions,
  ConversationMessage,
  DeepResearchResults,
  DocumentData,
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
  DeepResearchResults,
  DocumentData,
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

// Define the structure for a single conversation
// This type represents an individual conversation, with a description and an array of messages.
type ConversationType = {
  description: string; // A description or title of the conversation
  messages: MessageType[]; // An array of MessageType, representing the messages exchanged in the conversation
};
