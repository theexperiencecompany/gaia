import { retryTarget } from "@shared/conversation";
import { useCallback, useState } from "react";

import { deliverRetry, deliverSend } from "@/features/chat/live/connection";
import { liveConversation } from "@/features/chat/live/liveConversationStore";

/**
 * Retry from a bubble's action. A send that never reached the server is resent
 * as-is, so the server's message id dedup holds; an accepted message is
 * answered again by the server, in its place, with no new bubble.
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
        const target = retryTarget(live.view, messageId);
        if (!target) {
          console.error(
            "[useRetryMessage] No user message to retry:",
            messageId,
          );
          return;
        }
        await deliverRetry(conversationId, target);
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
