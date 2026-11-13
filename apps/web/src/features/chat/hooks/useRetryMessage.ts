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
          reply_to_message: message.reply_to_message,
          selected_tool: message.selected_tool,
          tool_category: message.tool_category,
          selected_workflow: message.selected_workflow,
          selected_calendar_event: message.selected_calendar_event,
          retry_of: message.id,
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
