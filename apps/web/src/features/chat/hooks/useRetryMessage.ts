import { messageToRetry } from "@shared/conversation";
import { useCallback, useState } from "react";

import { deliverSend } from "@/features/chat/live/connection";
import { liveConversation } from "@/features/chat/live/liveConversationStore";
import { sendMessage } from "@/features/chat/live/sendMessage";

/**
 * Retry from a bubble's action. A send that never reached the server is resent
 * as-is, so the server's message id dedup holds; an accepted message is sent
 * again as a new message that names it in retry_of.
 */
export const useRetryMessage = () => {
  const [isRetrying, setIsRetrying] = useState(false);

  const retryMessage = useCallback(
    async (conversationId: string, messageId: string) => {
      if (isRetrying) return;
      const live = liveConversation(conversationId);
      setIsRetrying(true);
      try {
        if (live.sends[messageId]?.failed) {
          await deliverSend(conversationId, messageId);
          return;
        }
        const message = messageToRetry(live.view, messageId);
        if (!message) {
          console.error(
            "[useRetryMessage] No user message to retry:",
            messageId,
          );
          return;
        }
        await sendMessage(message.text, {
          conversationId,
          files: message.files,
          replyToMessage: message.reply_to_message,
          selectedTool: message.selected_tool,
          toolCategory: message.tool_category,
          selectedWorkflow: message.selected_workflow,
          selectedCalendarEvent: message.selected_calendar_event,
          retryOf: message.id,
        });
      } catch (error) {
        console.error("[useRetryMessage] Error retrying message:", error);
      } finally {
        setIsRetrying(false);
      }
    },
    [isRetrying],
  );

  return { retryMessage, isRetrying };
};
