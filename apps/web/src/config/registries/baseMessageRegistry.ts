/**
 * Base Message Registry
 * Defines the core message data schema shared by all messages.
 * Extends the tools message schema to produce the full message shape.
 */

import type { SelectedCalendarEventData } from "@/stores/composerStore.types";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { ImageData, MemoryData } from "@/types/features/toolDataTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { AttachedFileData } from "@/types/shared/fileTypes";

import { TOOLS_MESSAGE_SCHEMA } from "./toolRegistry";

/**
 * One emoji reaction attached to a message for render. Built client-side by
 * foldReactionAcks from a comms REACT ack; `ackId` dedups re-syncs.
 */
export interface MessageReaction {
  emoji: string;
  ackId: string;
}

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
  fileData: undefined as AttachedFileData[] | undefined,
  selectedTool: undefined as string | null | undefined,
  toolCategory: undefined as string | null | undefined,
  selectedWorkflow: undefined as WorkflowData | null | undefined,
  selectedCalendarEvent: undefined as
    | SelectedCalendarEventData
    | null
    | undefined,
  isConvoSystemGenerated: undefined as boolean | undefined,
  follow_up_actions: undefined as string[] | undefined,
  // Set by the backend when a turn died with no response text — drives the
  // quiet failed-response bubble on reload instead of an empty bubble.
  error: undefined as string | null | undefined,
  // Core non-tool fields
  image_data: undefined as ImageData | null | undefined,
  memory_data: undefined as MemoryData | null | undefined,
  todo_progress: undefined as TodoProgressData | null | undefined,
  replyToMessage: undefined as
    | { id: string; content: string; role: "user" | "assistant" }
    | null
    | undefined,
  // Backend message kind ("text" | "emoji_ack"). An emoji_ack is a comms
  // REACT answer rendered as a reaction badge on its target, never a bubble.
  kind: undefined as string | undefined,
  // GAIA id of the message an emoji_ack reacts to (server's reacts_to_message_id).
  reacts_to_message_id: undefined as string | null | undefined,
  // Reactions folded onto this message for render (built client-side by
  // foldReactionAcks, never sent by the server).
  reactions: undefined as MessageReaction[] | undefined,
  // Tool fields (spread from tool registry)
  ...TOOLS_MESSAGE_SCHEMA,
};

export type BaseMessageData = typeof BASE_MESSAGE_SCHEMA;
export type BaseMessageKey = keyof typeof BASE_MESSAGE_SCHEMA;
export const BASE_MESSAGE_KEYS = Object.keys(
  BASE_MESSAGE_SCHEMA,
) as BaseMessageKey[];
