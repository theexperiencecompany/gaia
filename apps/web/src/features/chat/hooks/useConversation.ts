import { useMemo } from "react";
import { useLiveMessages } from "@/features/chat/live/useLiveChat";
import type { OptimisticMessage } from "@/stores/chatStore";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";

/**
 * The optimistic message is a separate shape from a logged one — it has no
 * status field, so `failed` is carried explicitly rather than derived. It only
 * exists before the backend assigns ids, and it is the only record of a send
 * that died there.
 */
export const mapOptimisticMessageToConversationMessage = (
  message: OptimisticMessage,
): MessageType => ({
  type: message.role === "user" ? ("user" as const) : ("bot" as const),
  response: message.content,
  message_id: message.id,
  date: message.createdAt?.toISOString(),
  fileIds: message.fileIds,
  fileData: message.fileData,
  selectedTool: message.toolName ?? undefined,
  toolCategory: message.toolCategory ?? undefined,
  selectedWorkflow: message.selectedWorkflow ?? undefined,
  selectedCalendarEvent: message.selectedCalendarEvent ?? undefined,
  replyToMessage: message.replyToMessage ?? undefined,
  loading: false,
  failed: message.failed,
});

/** The active conversation's rows: its log's view, or the first send of a conversation not created yet. */
export const useConversation = () => {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const optimisticMessage = useChatStore((state) => state.optimisticMessage);
  const liveMessages = useLiveMessages(activeConversationId);

  const convoMessages = useMemo(() => {
    if (
      optimisticMessage &&
      !activeConversationId &&
      optimisticMessage.conversationId === null
    ) {
      return [mapOptimisticMessageToConversationMessage(optimisticMessage)];
    }
    return liveMessages;
  }, [activeConversationId, optimisticMessage, liveMessages]);

  return { convoMessages };
};
