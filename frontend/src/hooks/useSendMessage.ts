import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";

import { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useCalendarEventSelectionStore } from "@/stores/calendarEventSelectionStore";
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

      debugger;

      // Create optimistic user message immediately for instant UI feedback
      // For new conversations: persist with temp conversation ID, will be updated when real conversation_id arrives
      // For existing conversations: persist now, replace ID later
      if (!conversationId) {
        // New conversation - persist optimistic message with temporary conversation ID
        const tempConversationId = `temp-${optimisticId}`;

        try {
          await db.putMessage(
            createOptimisticUserMessage(
              optimisticId,
              tempConversationId,
              trimmedContent,
              userMessage,
              createdAt,
            ),
          );
        } catch (error) {
          console.error(
            "Failed to persist optimistic message for new conversation:",
            error,
          );
        }

        // Backend will create conversation and send IDs
        // We'll update the message with real conversation_id and backend user_message_id
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

      // Existing conversation - persist optimistic message immediately
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
