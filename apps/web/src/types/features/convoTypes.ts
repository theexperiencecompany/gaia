// Tool payload types the chat's cards render, re-exported for their consumers.

import type {
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
