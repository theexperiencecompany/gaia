import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";

import { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useCalendarEventSelectionStore } from "@/stores/calendarEventSelectionStore";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
import { MessageType } from "@/types/features/convoTypes";
import { WorkflowData } from "@/types/features/workflowTypes";
import fetchDate from "@/utils/date/dateUtils";

type SendMessageOverrides = {
  files?: MessageType["fileData"];
  selectedTool?: string | null;
  selectedToolCategory?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
};

export const useSendMessage = () => {
  const fetchChatStream = useChatStream();

  const createOptimisticUserMessage = (
    optimisticId: string,
    conversationId: string,
    content: string,
    userMessage: MessageType,
    createdAt: Date,
  ): IMessage => {
    return {
      id: optimisticId,
      conversationId,
      content,
      role: "user",
      status: "sending",
      createdAt,
      updatedAt: createdAt,
      messageId: optimisticId,
      fileIds: userMessage.fileIds,
      fileData: userMessage.fileData,
      toolName: userMessage.selectedTool ?? null,
      toolCategory: userMessage.toolCategory ?? null,
      workflowId: userMessage.selectedWorkflow?.id ?? null,
      optimistic: true,
      metadata: {
        originalMessage: userMessage,
      },
    };
  };

  return useCallback(
    async (
      content: string,
      conversationId?: string | null,
      overrides?: SendMessageOverrides,
    ) => {
      const trimmedContent = content.trim();
      if (!trimmedContent) {
        return;
      }

      const composerState = useComposerStore.getState();
      const workflowState = useWorkflowSelectionStore.getState();
      const calendarEventState = useCalendarEventSelectionStore.getState();

      const files = overrides?.files ?? composerState.uploadedFileData;
      const normalizedFiles = (files ??
        []) as typeof composerState.uploadedFileData;
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

      const isoTimestamp = fetchDate();
      const createdAt = new Date(isoTimestamp);
      const optimisticId = uuidv4();

      const userMessage: MessageType = {
        type: "user",
        response: trimmedContent,
        date: isoTimestamp,
        message_id: optimisticId, // Temporary ID for optimistic UI
        fileIds: normalizedFiles.map((file) => file.fileId),
        fileData: normalizedFiles,
        selectedTool: selectedTool ?? undefined,
        toolCategory: selectedToolCategory ?? undefined,
        selectedWorkflow: selectedWorkflow ?? undefined,
        selectedCalendarEvent: selectedCalendarEvent ?? undefined,
      };

      // For new conversations: Store optimistic message in Zustand only (not IndexedDB)
      // This prevents IndexedDB pollution if message isn't properly cleared
      // Once conversation_id is received, this will be moved to IndexedDB with real ID
      if (!conversationId) {
        // Add optimistic message to Zustand for immediate UI display
        useChatStore.getState().addOptimisticMessage({
          id: optimisticId,
          content: trimmedContent,
          role: "user",
          createdAt,
          fileIds: normalizedFiles.map((file) => file.fileId),
          fileData: normalizedFiles,
          toolName: selectedTool,
          toolCategory: selectedToolCategory,
          workflowId: selectedWorkflow?.id ?? null,
          metadata: { originalMessage: userMessage },
        });

        // Stream will handle persisting to IndexedDB once conversation_id arrives
        await fetchChatStream(
          trimmedContent,
          [userMessage],
          normalizedFiles,
          selectedTool,
          selectedToolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
          optimisticId, // Pass optimistic ID for replacement
        );
        return;
      }

      // For existing conversations: Persist optimistic message to IndexedDB immediately
      // This is safe because we already have a valid conversation ID
      try {
        await db.putMessage(
          createOptimisticUserMessage(
            optimisticId,
            conversationId,
            trimmedContent,
            userMessage,
            createdAt,
          ),
        );
      } catch (error) {
        console.error("Failed to persist optimistic message:", error);
      }

      const streamingUserMessage: MessageType = {
        ...userMessage,
        loading: false,
      };

      try {
        await fetchChatStream(
          trimmedContent,
          [streamingUserMessage],
          normalizedFiles,
          selectedTool,
          selectedToolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
          optimisticId,
        );
      } catch (error) {
        console.error("[useSendMessage] Stream failed:", error);
      }
    },
    [fetchChatStream, createOptimisticUserMessage],
  );
};
