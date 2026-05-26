import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";
import { createIMessage } from "./messageBuilder";
import type { StreamContext } from "./types";

export const createPersistenceHelpers = (
  ctx: StreamContext,
  updateBotMessageInStore: (conversationId: string) => void,
) => {
  const schedulePersist = (conversationId: string) => {
    if (ctx.persistTimerRef.current) clearTimeout(ctx.persistTimerRef.current);
    ctx.persistTimerRef.current = setTimeout(() => {
      updateBotMessageInStore(conversationId);
      ctx.persistTimerRef.current = null;
    }, 250);
  };

  const persistBotMessage = async (
    conversationId: string,
    messageId: string,
  ) => {
    if (!ctx.refs.current.botMessage) return;

    try {
      // Ensure bot message timestamp is AFTER user message for correct ordering
      // Get user message timestamp and add 1ms offset
      const userMessageDate = ctx.refs.current.userMessage?.date
        ? new Date(ctx.refs.current.userMessage.date)
        : new Date();
      const botMessageDate = new Date(userMessageDate.getTime() + 1);

      // Create a copy of botMessage with the corrected date
      const botMessageWithDate: MessageType = {
        ...ctx.refs.current.botMessage,
        date: botMessageDate.toISOString(),
      };

      await db.putMessage(
        createIMessage(
          messageId,
          conversationId,
          "", // Empty content initially
          "assistant",
          "sending",
          botMessageWithDate,
        ),
      );
    } catch (error) {
      console.error("Failed to persist initial bot message:", error);
    }
  };

  const resolveConversationId = (): string | null =>
    ctx.refs.current.newConversation.id ||
    useChatStore.getState().activeConversationId;

  return { schedulePersist, persistBotMessage, resolveConversationId };
};
