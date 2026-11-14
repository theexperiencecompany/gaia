import { useMemo } from "react";
import type { ChatRow } from "@/features/chat/components/interface/rows/rows";
import { useScreenRows } from "@/features/chat/live/useLiveChat";
import { useChatStore } from "@/stores/chatStore";

/** The active conversation's rows: its screen, or the first send of a conversation not created yet. */
export const useChatRows = (): ChatRow[] => {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const optimisticMessage = useChatStore((state) => state.optimisticMessage);
  const screenRows = useScreenRows(activeConversationId);

  return useMemo(
    () =>
      optimisticMessage &&
      !activeConversationId &&
      optimisticMessage.conversationId === null
        ? [{ kind: "optimistic", message: optimisticMessage }]
        : screenRows,
    [activeConversationId, optimisticMessage, screenRows],
  );
};
