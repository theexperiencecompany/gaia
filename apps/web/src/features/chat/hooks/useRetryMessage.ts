import { useCallback, useState } from "react";

import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { useSendMessage } from "@/hooks/useSendMessage";
import { useChatStore } from "@/stores/chatStore";

/**
 * Simple hook for retrying/regenerating a message.
 * Finds the relevant user message and resends it using the existing send message flow.
 * The message appears in the UI like a normal message (user bubble + loading indicator).
 *
 * Uses the same loading state management as Composer for consistent UX.
 */
export const useRetryMessage = () => {
  const [isRetrying, setIsRetrying] = useState(false);
  const sendMessage = useSendMessage();
  const { setContextualLoading } = useLoadingText();

  const retryMessage = useCallback(
    async (conversationId: string, messageId: string) => {
      console.log("Retrying message:", messageId);
      if (isRetrying) return;

      const store = useChatStore.getState();
      const messages = store.messagesByConversation[conversationId] ?? [];

      // Find the message being retried
      const targetMessageIndex = messages.findIndex(
        (msg) =>
          msg.id === messageId ||
          msg.messageId === messageId ||
          (msg as { message_id?: string }).message_id === messageId,
      );

      if (targetMessageIndex === -1) {
        console.error("[useRetryMessage] Message not found:", messageId);
        return;
      }

      const targetMessage = messages[targetMessageIndex];

      // Determine the user message to resend
      let userMessage: (typeof messages)[0] | null = null;

      if (targetMessage.role === "user") {
        // Retrying a user message - use this message directly
        userMessage = targetMessage;
      } else {
        // Retrying a bot message - find the preceding user message
        for (let i = targetMessageIndex - 1; i >= 0; i--) {
          if (messages[i].role === "user") {
            userMessage = messages[i];
            break;
          }
        }
      }

      if (!userMessage) {
        console.error("[useRetryMessage] No user message found to retry");
        return;
      }

      setIsRetrying(true);

      // Set loading state with user's message context (same as Composer)
      // This enables similarity-based loading text
      setContextualLoading(true, userMessage.content);

      try {
        // Use the existing sendMessage hook - it handles everything
        // (optimistic UI, IndexedDB persistence, streaming, etc.)
        // Loading state is managed by useChatStream (sets isLoading to false when done)
        await sendMessage(userMessage.content, {
          files: userMessage.fileData ?? undefined,
          selectedTool: userMessage.toolName,
          selectedToolCategory: userMessage.toolCategory,
          selectedWorkflow: userMessage.selectedWorkflow,
          selectedCalendarEvent: userMessage.selectedCalendarEvent,
          replyToMessage: userMessage.replyToMessageData,
        });
      } catch (error) {
        console.error("[useRetryMessage] Error retrying message:", error);
      } finally {
        setIsRetrying(false);
      }
    },
    [isRetrying, sendMessage, setContextualLoading],
  );

  return { retryMessage, isRetrying };
};
