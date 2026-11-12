import { ENTRY_KIND, type UserMessage } from "@shared/conversation";
import { useCallback, useState } from "react";

import { deliverSend } from "@/features/chat/live/connection";
import { liveConversation } from "@/features/chat/live/liveConversationStore";
import { sendMessage } from "@/features/chat/live/sendMessage";

/** The user message a retry resends: the message itself, or the newest one before the reply. */
function messageToRetry(
  conversationId: string,
  messageId: string,
): UserMessage | null {
  const { entries } = liveConversation(conversationId).view;
  const at = entries.findIndex(
    ({ entry }) =>
      entry.id === messageId ||
      (entry.kind === ENTRY_KIND.REPLY && entry.reply_id === messageId),
  );
  if (at === -1) return null;
  const asked = entries
    .slice(0, at + 1)
    .findLast(({ entry }) => entry.kind === ENTRY_KIND.USER_MESSAGE)?.entry;
  return asked?.kind === ENTRY_KIND.USER_MESSAGE ? asked : null;
}

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
        const message = messageToRetry(conversationId, messageId);
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
