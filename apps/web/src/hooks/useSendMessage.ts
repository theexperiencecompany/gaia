import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";

import type { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import { turnManager } from "@/features/chat/stream/turnManager";
import type { TurnOptions } from "@/features/chat/stream/types";
import {
  ANALYTICS_EVENTS,
  setUserProperties,
  trackEvent,
} from "@/lib/analytics";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useCalendarEventSelectionStore } from "@/stores/calendarEventSelectionStore";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import {
  type ReplyToMessageData,
  useReplyToMessageStore,
} from "@/stores/replyToMessageStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
import type { MessageType } from "@/types/features/convoTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";
import fetchDate from "@/utils/date/dateUtils";

type SendMessageOverrides = {
  files?: MessageType["fileData"];
  selectedTool?: string | null;
  selectedToolCategory?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
  replyToMessage?: ReplyToMessageData | null;
  /** Explicit conversation ID to use. Pass null to force a new conversation.
   *  When omitted, falls back to the active conversation ID from the store. */
  conversationId?: string | null;
};

interface ResolvedSendContext {
  content: string;
  files: FileData[];
  selectedTool: string | null;
  selectedToolCategory: string | null;
  selectedWorkflow: WorkflowData | null;
  selectedCalendarEvent: SelectedCalendarEventData | null;
  replyToMessage: ReplyToMessageData | null;
  conversationId: string | null;
}

/** Merge explicit overrides with the current composer/selection store state. */
const resolveSendContext = (
  content: string,
  overrides?: SendMessageOverrides,
): ResolvedSendContext | null => {
  const composerState = useComposerStore.getState();
  const workflowState = useWorkflowSelectionStore.getState();
  const calendarEventState = useCalendarEventSelectionStore.getState();
  const replyState = useReplyToMessageStore.getState();

  const files = (overrides?.files ??
    composerState.uploadedFileData ??
    []) as FileData[];
  const selectedTool =
    overrides?.selectedTool ?? composerState.selectedTool ?? null;
  const selectedToolCategory =
    overrides?.selectedToolCategory ??
    composerState.selectedToolCategory ??
    null;
  const selectedWorkflow =
    overrides?.selectedWorkflow ?? workflowState.selectedWorkflow ?? null;
  const selectedCalendarEvent =
    overrides?.selectedCalendarEvent ??
    calendarEventState.selectedCalendarEvent ??
    null;
  const replyToMessage =
    overrides?.replyToMessage ?? replyState.replyToMessage ?? null;

  const trimmedContent = content.trim();
  const hasValidContent =
    trimmedContent ||
    selectedTool ||
    selectedWorkflow ||
    selectedCalendarEvent ||
    files.length > 0;
  if (!hasValidContent) return null;

  // Use explicit override when provided (e.g. auto-send from workflow sidebar
  // where the store may still hold a stale ID). `overrides.conversationId`
  // being present (even as null) takes precedence.
  const rawConversationId =
    overrides !== undefined && "conversationId" in overrides
      ? (overrides.conversationId ?? null)
      : useChatStore.getState().activeConversationId;

  return {
    content: trimmedContent,
    files,
    selectedTool,
    selectedToolCategory,
    selectedWorkflow,
    selectedCalendarEvent,
    replyToMessage,
    // "new" is a routing sentinel for "create a conversation".
    conversationId: rawConversationId === "new" ? null : rawConversationId,
  };
};

const trackFirstMessageMilestone = () => {
  try {
    const stored = localStorage.getItem("gaia_first_message_sent");
    if (!stored) {
      trackEvent(ANALYTICS_EVENTS.CHAT_FIRST_MESSAGE_SENT, {
        milestone: "first_message",
      });
      setUserProperties({ first_message_sent: true });
      localStorage.setItem("gaia_first_message_sent", "true");
    }
  } catch {
    // localStorage unavailable — skip the milestone.
  }
};

/** Surface the user's message immediately: Zustand-only for new conversations
 *  (no conversation id yet), IndexedDB-backed for existing ones. */
const placeOptimisticMessage = async (
  ctx: ResolvedSendContext,
  optimisticId: string,
  createdAt: Date,
  willQueue: boolean,
): Promise<void> => {
  if (!ctx.conversationId) {
    useChatStore.getState().setOptimisticMessage({
      id: optimisticId,
      conversationId: null,
      content: ctx.content,
      role: "user",
      createdAt,
      fileIds: ctx.files.map((file) => file.fileId),
      fileData: ctx.files,
      toolName: ctx.selectedTool,
      toolCategory: ctx.selectedToolCategory,
      workflowId: ctx.selectedWorkflow?.id ?? null,
      selectedWorkflow: ctx.selectedWorkflow,
      selectedCalendarEvent: ctx.selectedCalendarEvent,
      replyToMessage: ctx.replyToMessage,
    });
    return;
  }

  const optimisticMessage: IMessage = {
    id: optimisticId,
    conversationId: ctx.conversationId,
    content: ctx.content,
    role: "user",
    status: willQueue ? "queued" : "sending",
    createdAt,
    updatedAt: createdAt,
    messageId: optimisticId,
    fileIds: ctx.files.map((file) => file.fileId),
    fileData: ctx.files,
    toolName: ctx.selectedTool,
    toolCategory: ctx.selectedToolCategory,
    workflowId: ctx.selectedWorkflow?.id ?? null,
    selectedWorkflow: ctx.selectedWorkflow,
    selectedCalendarEvent: ctx.selectedCalendarEvent,
    replyToMessageId: ctx.replyToMessage?.id ?? null,
    replyToMessageData: ctx.replyToMessage,
    optimistic: true,
  };
  try {
    await db.putMessage(optimisticMessage);
  } catch (error) {
    console.error(
      "[useSendMessage] Failed to persist optimistic message:",
      error,
    );
  }
};

export const useSendMessage = () => {
  return useCallback(
    async (content: string, overrides?: SendMessageOverrides) => {
      const ctx = resolveSendContext(content, overrides);
      if (!ctx) return;

      trackFirstMessageMilestone();

      const isoTimestamp = fetchDate();
      const createdAt = new Date(isoTimestamp);
      const optimisticId = uuidv4();

      const userMessage: MessageType = {
        type: "user",
        response: ctx.content,
        date: isoTimestamp,
        message_id: optimisticId, // Temporary ID for optimistic UI
        fileIds: ctx.files.map((file) => file.fileId),
        fileData: ctx.files,
        selectedTool: ctx.selectedTool ?? undefined,
        toolCategory: ctx.selectedToolCategory ?? undefined,
        selectedWorkflow: ctx.selectedWorkflow ?? undefined,
        selectedCalendarEvent: ctx.selectedCalendarEvent ?? undefined,
        replyToMessage: ctx.replyToMessage ?? undefined,
      };

      // A send landing while this conversation's turn is open gets queued by
      // the turn manager — its optimistic bubble renders greyed-out until
      // dispatch flips it to "sending".
      const willQueue = turnManager.isTurnActive(ctx.conversationId);
      await placeOptimisticMessage(ctx, optimisticId, createdAt, willQueue);

      const options: TurnOptions = {
        fileData: ctx.files,
        selectedTool: ctx.selectedTool,
        toolCategory: ctx.selectedToolCategory,
        selectedWorkflow: ctx.selectedWorkflow,
        selectedCalendarEvent: ctx.selectedCalendarEvent,
        optimisticUserId: optimisticId,
        replyToMessage: ctx.replyToMessage,
        conversationId: ctx.conversationId,
        isOnboardingDemo: false,
      };

      turnManager.send({ inputText: ctx.content, userMessage, options });
    },
    [],
  );
};
