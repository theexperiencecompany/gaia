// Base message types to eliminate redundancy across chat bubble and conversation types

import React, { Dispatch } from "react";

import { BaseMessageData } from "@/config/registries/baseMessageRegistry";
import { SystemPurpose } from "@/features/chat/api/chatApi";

import {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
} from "./calendarTypes";
import {
  ContactData,
  EmailComposeData,
  EmailSentData,
  EmailThreadData,
  PeopleSearchData,
} from "./mailTypes";
import { DeepResearchResults, SearchResults } from "./searchTypes";
import { TodoToolData } from "./todoToolTypes";
import {
  CodeData,
  DocumentData,
  GoalDataMessageType,
  GoogleDocsData,
  ImageData,
  MemoryData,
} from "./toolDataTypes";
import { WeatherData } from "./weatherTypes";

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
}

// Message type for conversations (combines user and bot data)
export interface ConversationMessage extends Partial<BaseMessageData> {
  type: "user" | "bot";
  response: string; // The main content field for conversations
  loading?: boolean;
  disclaimer?: string;
}

// Re-export all tool data types for convenience
export type {
  CalendarDeleteOptions,
  CalendarEditOptions,
  CalendarOptions,
  CodeData,
  ContactData,
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
  TodoToolData,
  WeatherData,
};
