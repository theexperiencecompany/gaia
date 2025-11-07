import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";

import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { SelectedCalendarEventData } from "@/features/chat/hooks/useCalendarEventSelection";
import { db, type IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import { useCalendarEventSelectionStore } from "@/stores/calendarEventSelectionStore";
import { useComposerStore } from "@/stores/composerStore";
import { useConversationStore } from "@/stores/conversationStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";
import { MessageType } from "@/types/features/convoTypes";
import { WorkflowData } from "@/types/features/workflowTypes";
import fetchDate from "@/utils/date/dateUtils";

type ChatStoreState = ReturnType<typeof useChatStore.getState>;

const selectAddOrUpdateMessage = (state: ChatStoreState) =>
  state.addOrUpdateMessage;
const selectSetMessagesForConversation = (state: ChatStoreState) =>
  state.setMessagesForConversation;

type SendMessageOverrides = {
  files?: MessageType["fileData"];
  selectedTool?: string | null;
  selectedToolCategory?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;
};

export const useSendMessage = () => {
  const addOrUpdateMessage = useChatStore(selectAddOrUpdateMessage);
  const setMessagesForConversation = useChatStore(
    selectSetMessagesForConversation,
  );
  const addLegacyMessage = useConversationStore((state) => state.addMessage);
  const fetchChatStream = useChatStream();

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

      addLegacyMessage(userMessage);

      if (!conversationId) {
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

      addOrUpdateMessage(optimisticMessage);

      const finalMessage: IMessage = {
        ...optimisticMessage,
        status: "sent",
        updatedAt: new Date(),
        metadata: {
          originalMessage: {
            ...userMessage,
            loading: false,
          },
        },
      };

      try {
        await db.replaceMessage(optimisticMessage.id, finalMessage);
      } catch {
        try {
          await db.putMessage(finalMessage);
        } catch {
          // Ignore persistence failures when updating the final state
        }
      }

      const existingMessages =
        useChatStore.getState().messagesByConversation[conversationId] ?? [];
      const withoutOptimistic = existingMessages.filter(
        (message) => message.id !== optimisticMessage.id,
      );
      setMessagesForConversation(conversationId, [
        ...withoutOptimistic,
        finalMessage,
      ]);
      addOrUpdateMessage(finalMessage);

      const streamingUserMessage: MessageType = {
        ...userMessage,
        loading: false,
      };

      try {
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
      } catch {
        const failedMessage: IMessage = {
          ...finalMessage,
          status: "failed",
          updatedAt: new Date(),
        };

        try {
          await db.putMessage(failedMessage);
        } catch {
          // Ignore persistence failures for failure state updates
        }

        addOrUpdateMessage(failedMessage);
      }
    },
    [
      addLegacyMessage,
      addOrUpdateMessage,
      fetchChatStream,
      setMessagesForConversation,
    ],
  );
};
