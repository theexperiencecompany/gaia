import { useCallback, useEffect, useRef } from "react";
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
  const hookIdRef = useRef(
    `sendMessage-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
  );
  const hookId = hookIdRef.current;

  const fetchChatStream = useChatStream();

  useEffect(() => {
    console.log(`[useSendMessage:${hookId}] Hook MOUNTED`);
    return () => {
      console.log(`[useSendMessage:${hookId}] Hook UNMOUNTING`);
    };
  }, [hookId]);

  useEffect(() => {
    console.log(`[useSendMessage:${hookId}] fetchChatStream reference updated`);
  }, [hookId, fetchChatStream]);

  return useCallback(
    async (
      content: string,
      conversationId?: string | null,
      overrides?: SendMessageOverrides,
    ) => {
      console.log(`[useSendMessage:${hookId}] sendMessage called:`, {
        contentLength: content.length,
        conversationId,
        hasOverrides: !!overrides,
      });

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
      const tempMessageId = uuidv4();
      const botMessageId = uuidv4();

      const userMessage: MessageType = {
        type: "user",
        response: trimmedContent,
        date: isoTimestamp,
        message_id: tempMessageId,
        fileIds: normalizedFiles.map((file) => file.fileId),
        fileData: normalizedFiles,
        selectedTool: selectedTool ?? undefined,
        toolCategory: selectedToolCategory ?? undefined,
        selectedWorkflow: selectedWorkflow ?? undefined,
        selectedCalendarEvent: selectedCalendarEvent ?? undefined,
      };

      if (!conversationId) {
        console.log(
          `[useSendMessage:${hookId}] No conversationId - creating new conversation`,
        );
        await fetchChatStream(
          trimmedContent,
          [userMessage],
          botMessageId,
          normalizedFiles,
          selectedTool,
          selectedToolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
        );
        return;
      }

      console.log(
        `[useSendMessage:${hookId}] Persisting optimistic message to IndexedDB`,
      );

      const optimisticMessage: IMessage = {
        id: tempMessageId,
        conversationId,
        content: trimmedContent,
        role: "user",
        status: "sending",
        createdAt,
        updatedAt: createdAt,
        messageId: tempMessageId,
        fileIds: userMessage.fileIds,
        fileData: userMessage.fileData,
        toolName: userMessage.selectedTool ?? null,
        toolCategory: userMessage.toolCategory ?? null,
        workflowId: userMessage.selectedWorkflow?.id ?? null,
        metadata: {
          originalMessage: userMessage,
        },
      };

      try {
        await db.putMessage(optimisticMessage);
      } catch {
        // Ignore local persistence errors to keep the UI responsive
      }

      // db.putMessage will emit event that updates Zustand store automatically
      // Status will be updated to "sent" after successful streaming or "failed" on error

      const streamingUserMessage: MessageType = {
        ...userMessage,
        loading: false,
      };

      try {
        console.log(
          `[useSendMessage:${hookId}] Starting stream with existing conversationId`,
        );
        await fetchChatStream(
          trimmedContent,
          [streamingUserMessage],
          botMessageId,
          normalizedFiles,
          selectedTool,
          selectedToolCategory,
          selectedWorkflow,
          selectedCalendarEvent,
        );
        console.log(`[useSendMessage:${hookId}] Stream completed successfully`);
      } catch {
        const failedMessage: IMessage = {
          ...optimisticMessage,
          status: "failed",
          updatedAt: new Date(),
        };

        try {
          await db.putMessage(failedMessage);
        } catch {
          // Ignore persistence failures for failure state updates
        }
      }
    },
    [fetchChatStream, hookId],
  );
};
