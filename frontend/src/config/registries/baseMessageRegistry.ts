/**
 * Base Message Registry
 * Defines the core message data schema shared by all messages.
 * Extends the tools message schema to produce the full message shape.
 */

import { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import { WorkflowData } from "@/types/features/workflowTypes";
import { FileData } from "@/types/shared/fileTypes";

import { TOOLS_MESSAGE_SCHEMA } from "./toolRegistry";

type ImageData = import("@/types/features/toolDataTypes").ImageData;

type MemoryData = import("@/types/features/toolDataTypes").MemoryData;

/**
 * BASE_MESSAGE_SCHEMA
 * Each property uses a typed placeholder to:
 *  - drive TypeScript inference for BaseMessageData
 *  - represent optional/nullable fields at runtime
 *  - keep key lists and types in sync from a single definition
 */
export const BASE_MESSAGE_SCHEMA = {
  message_id: "" as string, // required
  date: undefined as string | undefined,
  pinned: undefined as boolean | undefined,
  fileIds: undefined as string[] | undefined,
  fileData: undefined as FileData[] | undefined,
  selectedTool: undefined as string | null | undefined,
  toolCategory: undefined as string | null | undefined,
  selectedWorkflow: undefined as WorkflowData | null | undefined,
  selectedCalendarEvent: undefined as
    | SelectedCalendarEventData
    | null
    | undefined,
  isConvoSystemGenerated: undefined as boolean | undefined,
  follow_up_actions: undefined as string[] | undefined,
  // Core non-tool fields
  image_data: undefined as ImageData | null | undefined,
  memory_data: undefined as MemoryData | null | undefined,
  // Tool fields (spread from tool registry)
  ...TOOLS_MESSAGE_SCHEMA,
};

export type BaseMessageData = typeof BASE_MESSAGE_SCHEMA;
export type BaseMessageKey = keyof typeof BASE_MESSAGE_SCHEMA;
export const BASE_MESSAGE_KEYS = Object.keys(
  BASE_MESSAGE_SCHEMA,
) as BaseMessageKey[];
