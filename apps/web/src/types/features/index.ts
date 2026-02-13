// Central export file for all feature types

// Base message types - the core types that eliminate redundancy
// All tool-specific types
export type {
  BotMessageData,
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  ContactData,
  ConversationMessage,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  EmailSentData,
  EmailThreadData,
  GoalDataMessageType,
  GoogleDocsData,
  ImageData,
  MemoryData,
  PeopleSearchData,
  SearchResults,
  SetImageDataType,
  TodoToolData,
  UserMessageData,
  WeatherData,
} from "./baseMessageTypes";
// Legacy types that now extend base types (for backwards compatibility)
export type {
  ChatBubbleBotProps,
  ChatBubbleUserProps,
} from "./chatBubbleTypes";
export type { ConversationType } from "./convoTypes";

// Other feature types
export type * from "./goalTypes";
export type * from "./noteTypes";
export type * from "./notificationTypes";
export type * from "./pinTypes";
export type * from "./todoProgressTypes";
export type * from "./todoTypes";
export type * from "./toolDataTypes";
