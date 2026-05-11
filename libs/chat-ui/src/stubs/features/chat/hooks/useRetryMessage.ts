/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import { useCallback } from "react";

export const useRetryMessage = (): {
  retryMessage: (conversationId: string, messageId: string) => Promise<void>;
  isRetrying: boolean;
} => {
  const retryMessage = useCallback(
    async (_conversationId: string, _messageId: string): Promise<void> => {},
    [],
  );
  return { retryMessage, isRetrying: false };
};
