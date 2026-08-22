// Base message types to eliminate redundancy across chat bubble and conversation types

import type React from "react";
import type { Dispatch } from "react";

import type { BaseMessageData } from "@/config/registries/baseMessageRegistry";
import type { SystemPurpose } from "@/features/chat/api/chatApi";

import type { CalendarOptions } from "./calendarTypes";
import type { EmailComposeData } from "./mailTypes";
import type { DeepResearchResults, SearchResults } from "./searchTypes";
import type { ImageData } from "./toolDataTypes";
import type { WeatherData } from "./weatherTypes";

// Type for image data used in UI callbacks
export interface SetImageDataType {
  src: string; // corresponds to url in ImageData
  prompt: string;
  improvedPrompt: string; // corresponds to improved_prompt in ImageData
}

// User-specific message data
export interface UserMessageData extends BaseMessageData {
  text?: string;
  file?: File | null | string;
  filename?: string;

  // True while the message is held in the send queue (greyed-out bubble).
  queued?: boolean;

  // The send never reached the backend (dropped connection, reload mid-flight).
  // Drives a persistent "Not delivered" label + retry on the user bubble.
  failed?: boolean;

  // True while the message is still streaming in — the voice transcript grows
  // word-by-word as the user speaks. Drives the user bubble's blur-in animation.
  loading?: boolean;

  // Retry callbacks
  onRetry?: () => void;
  isRetrying?: boolean;
}

// Bot-specific message data with UI callbacks
export interface BotMessageData extends BaseMessageData {
  text: string;
  loading?: boolean;
  disclaimer?: string;
  filename?: string;
  systemPurpose?: SystemPurpose;
  isLastMessage?: boolean;

  // UI callback functions
  setOpenImage: React.Dispatch<React.SetStateAction<boolean>>;
  setImageData: Dispatch<React.SetStateAction<SetImageDataType>>;
  onOpenMemoryModal?: () => void;

  // Retry callbacks
  onRetry?: () => void;
  isRetrying?: boolean;

  animateParts?: boolean;
}

// Message type for conversations (combines user and bot data)
export interface ConversationMessage extends Partial<BaseMessageData> {
  type: "user" | "bot";
  response: string; // The main content field for conversations
  loading?: boolean;
  queued?: boolean; // Held in the send queue (greyed-out user bubble)
  failed?: boolean; // Send never reached the backend
  disclaimer?: string;
}

// Re-export all tool data types for convenience
export type {
  CalendarOptions,
  DeepResearchResults,
  EmailComposeData,
  ImageData,
  SearchResults,
  WeatherData,
};
