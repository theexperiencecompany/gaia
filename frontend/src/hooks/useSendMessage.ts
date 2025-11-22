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

  return useCallback(
    async (content: string, overrides?: SendMessageOverrides) => {
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

      const trimmedContent = content.trim();
      // Allow sending if there's text OR tool OR workflow OR calendar event OR files
      const hasValidContent =
        trimmedContent ||
        selectedTool ||
        selectedWorkflow ||
        selectedCalendarEvent ||
        normalizedFiles.length > 0;

      if (!hasValidContent) {
        return;
      }

      const isoTimestamp = fetchDate();
      const createdAt = new Date(isoTimestamp);
      const optimisticId = uuidv4();
      const conversationId = useChatStore.getState().activeConversationId;

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

      // For new conversations: use Zustand optimistic message (no conversationId yet)
      // For existing conversations: persist directly to IndexedDB with optimistic ID
      if (!conversationId) {
        // New conversation - use Zustand optimistic message
        useChatStore.getState().setOptimisticMessage({
          id: optimisticId,
          conversationId: null,
          content: trimmedContent,
          role: "user",
          createdAt,
          fileIds: normalizedFiles.map((file) => file.fileId),
          fileData: normalizedFiles,
          toolName: selectedTool,
          toolCategory: selectedToolCategory,
          workflowId: selectedWorkflow?.id ?? null,
        });

        await fetchChatStream(
          trimmedContent,
          [userMessage],
          normalizedFiles,
          selectedTool,
          selectedToolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
          optimisticId,
        );
        return;
      }

      // For existing conversations: persist to IndexedDB immediately with optimistic ID
      // Backend will send real ID which will replace this optimistic message
      const optimisticMessage: IMessage = {
        id: optimisticId,
        conversationId,
        content: trimmedContent,
        role: "user",
        status: "sending",
        createdAt,
        updatedAt: createdAt,
        messageId: optimisticId,
        fileIds: normalizedFiles.map((file) => file.fileId),
        fileData: normalizedFiles,
        toolName: selectedTool,
        toolCategory: selectedToolCategory,
        workflowId: selectedWorkflow?.id ?? null,
        selectedWorkflow: selectedWorkflow,
        selectedCalendarEvent: selectedCalendarEvent,
        optimistic: true,
      };
      try {
        await db.putMessage(optimisticMessage);

        const streamingUserMessage: MessageType = {
          ...userMessage,
          loading: false,
        };

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
    [fetchChatStream],
  );
};
