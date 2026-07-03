import { useCallback, useState } from "react";

import { useSendMessage } from "@/hooks/useSendMessage";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
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

  const retryMessage = useCallback(
    async (conversationId: string, messageId: string) => {
      if (isRetrying) return;

      const store = useChatStore.getState();
      const messages = store.messagesByConversation[conversationId] ?? [];

      // Find the message being retried
      const targetMessageIndex = messages.findIndex(
        (msg) => msg.id === messageId || msg.messageId === messageId,
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

      trackEvent(ANALYTICS_EVENTS.CHAT_MESSAGE_RETRIED, {
        message_id: messageId,
        conversation_id: conversationId,
        retry_source: targetMessage.role === "user" ? "user" : "bot",
      });

      try {
        // The send flow handles everything — optimistic UI, persistence,
        // streaming, and the turn's loading indicator.
        await sendMessage(userMessage.content, {
          conversationId,
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
    [isRetrying, sendMessage],
  );

  return { retryMessage, isRetrying };
};
