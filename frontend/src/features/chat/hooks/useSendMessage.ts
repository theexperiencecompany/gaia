// useSendMessage.ts
"use client";

import ObjectID from "bson-objectid";
import { useCallback } from "react";

import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { useConversationStore } from "@/stores/conversationStore";
import { MessageType } from "@/types/features/convoTypes";
import { WorkflowData } from "@/types/features/workflowTypes";
import { FileData } from "@/types/shared";
import fetchDate from "@/utils/date/dateUtils";

export const useSendMessage = () => {
  const { addMessage } = useConversationStore();
  const fetchChatStream = useChatStream();
  const { resetLoadingText } = useLoadingText();

  return useCallback(
    async (
      inputText: string,
      fileData: FileData[] = [],
      selectedTool: string | null = null,
      toolCategory: string | null = null,
      selectedWorkflow: WorkflowData | null = null,
    ) => {
      const botMessageId = String(ObjectID());
      // const isWebSearch = currentMode === "web_search";
      // const isDeepSearch = currentMode === "deep_research";

      const userMessage: MessageType = {
        type: "user",
        response: inputText,
        date: fetchDate(),
        message_id: String(ObjectID()),
        fileIds: fileData.map((f) => f.fileId),
        fileData,
        selectedTool, // Add selectedTool to the message
        toolCategory, // Add toolCategory to the message
        selectedWorkflow, // Add selectedWorkflow to the message
      };

      addMessage(userMessage);

      // Reset loading text when starting a new message to get a fresh thinking message
      resetLoadingText();

      await fetchChatStream(
        inputText,
        [userMessage],
        botMessageId,
        fileData,
        selectedTool,
        toolCategory,
        selectedWorkflow,
      );
    },
    [addMessage, fetchChatStream, resetLoadingText],
  );
};
