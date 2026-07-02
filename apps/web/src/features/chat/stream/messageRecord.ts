import type { TurnAccumulator } from "@shared/chat";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import type { IMessage } from "@/lib/db/chatDb";
import type { MessageType } from "@/types/features/convoTypes";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type { ImageData, MemoryData } from "@/types/features/toolDataTypes";
import type { SendArgs, TurnOptions } from "./types";

/**
 * Turn metadata fixed at send time. Combined with the live accumulator this is
 * everything needed to build the message record — the ONE place the assistant
 * message shape is assembled, for live flushes, close persistence, and aborts.
 */
export interface TurnMessageMeta {
  conversationId: string;
  botMessageId: string;
  createdAt: Date;
  options: TurnOptions;
}

export const buildTurnMessageRecord = (
  meta: TurnMessageMeta,
  acc: TurnAccumulator,
  status: IMessage["status"],
): IMessage => ({
  id: meta.botMessageId,
  conversationId: meta.conversationId,
  content: acc.responseText,
  role: "assistant",
  status,
  createdAt: meta.createdAt,
  updatedAt: new Date(),
  messageId: meta.botMessageId,
  fileIds: meta.options.fileData.map((file) => file.fileId),
  fileData: meta.options.fileData,
  toolName: meta.options.selectedTool,
  toolCategory: meta.options.toolCategory,
  workflowId: meta.options.selectedWorkflow?.id ?? null,
  selectedWorkflow: meta.options.selectedWorkflow,
  selectedCalendarEvent: meta.options.selectedCalendarEvent,
  tool_data: acc.toolData.length > 0 ? (acc.toolData as ToolDataEntry[]) : null,
  follow_up_actions: acc.followUpActions,
  image_data: (acc.imageData as ImageData | null) ?? null,
  memory_data: (acc.extras.memory_data as MemoryData | undefined) ?? null,
  todo_progress: (acc.todoProgress as TodoProgressData | null) ?? null,
  pinned: false,
  isConvoSystemGenerated: false,
  replyToMessageId: meta.options.replyToMessage?.id ?? null,
  replyToMessageData: meta.options.replyToMessage,
});

/**
 * Rebuild the send payload from a persisted queued record — the inverse of
 * `buildUserMessageRecord`, used to restore a conversation's send queue after
 * a reload. The record id is reused as the turn id, so a send that actually
 * left before the reload is rejected as a duplicate instead of delivered
 * twice.
 */
export const buildSendArgsFromRecord = (record: IMessage): SendArgs => ({
  inputText: record.content,
  userMessage: {
    type: "user",
    response: record.content,
    date: record.createdAt.toISOString(),
    message_id: record.id,
    fileIds: record.fileIds,
    fileData: record.fileData,
    selectedTool: record.toolName ?? undefined,
    toolCategory: record.toolCategory ?? undefined,
    selectedWorkflow: record.selectedWorkflow ?? undefined,
    selectedCalendarEvent: record.selectedCalendarEvent ?? undefined,
    replyToMessage: record.replyToMessageData ?? undefined,
  },
  options: {
    fileData: record.fileData ?? [],
    selectedTool: record.toolName ?? null,
    toolCategory: record.toolCategory ?? null,
    selectedWorkflow: record.selectedWorkflow ?? null,
    selectedCalendarEvent: record.selectedCalendarEvent ?? null,
    optimisticUserId: record.id,
    replyToMessage: record.replyToMessageData ?? null,
    conversationId: record.conversationId,
    isOnboardingDemo: false,
  },
});

/** Build the persisted record for the turn's user message. */
export const buildUserMessageRecord = (
  userMessageId: string,
  conversationId: string,
  userMessage: MessageType,
  createdAt: Date,
): IMessage => ({
  id: userMessageId,
  conversationId,
  content: userMessage.response,
  role: "user",
  status: "sent",
  createdAt,
  updatedAt: new Date(),
  messageId: userMessageId,
  fileIds: userMessage.fileIds,
  fileData: userMessage.fileData,
  toolName: userMessage.selectedTool ?? null,
  toolCategory: userMessage.toolCategory ?? null,
  workflowId: userMessage.selectedWorkflow?.id ?? null,
  selectedWorkflow: userMessage.selectedWorkflow ?? null,
  selectedCalendarEvent: userMessage.selectedCalendarEvent ?? null,
  replyToMessageId: userMessage.replyToMessage?.id ?? null,
  replyToMessageData: userMessage.replyToMessage ?? null,
  pinned: false,
  isConvoSystemGenerated: false,
});
