// Central export file for all feature types

// Base message types - the core types that eliminate redundancy
// All tool-specific types
export type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  DeepResearchResults,
  DocumentData,
  EmailComposeData,
  EmailSentData,
  EmailThreadData,
  GoalDataMessageType,
  GoogleDocsData,
  ImageData,
  MemoryData,
  SearchResults,
  TodoToolData,
  WeatherData,
} from "./baseMessageTypes";

// Other feature types
export type * from "./goalTypes";
export type * from "./noteTypes";
export type * from "./notificationTypes";
export type * from "./pinTypes";
export type * from "./todoTypes";
export type * from "./toolDataTypes";
