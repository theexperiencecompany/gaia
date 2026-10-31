import { useMemo } from "react";
import type { IConversation } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const toConversationRow = (conv: IConversation, messageCount: number) => ({
  conversation_id: conv.id,
  description: conv.description || conv.title,
  title: conv.title,
  starred: conv.starred,
  is_system_generated: conv.isSystemGenerated,
  system_purpose: conv.systemPurpose,
  is_unread: conv.isUnread,
  has_live_approval: conv.hasLiveApproval ?? false,
  todo_id: conv.todoId ?? null,
  user_id: conv.userId,
  created_at: conv.createdAt.toISOString(),
  updated_at: conv.updatedAt.toISOString(),
  createdAt: conv.createdAt,
  updatedAt: conv.updatedAt,
  messageCount,
});

export type ConversationRow = ReturnType<typeof toConversationRow>;

/**
 * The conversations the user browses: every one except a tracked todo's chat,
 * which is reached only from its todo (the server never lists it either, but a
 * client that opened it keeps it in its local store).
 */
export const useConversationList = () => {
  const conversations = useChatStore((state) => state.conversations);
  const messagesByConversation = useChatStore(
    (state) => state.messagesByConversation,
  );

  // Memoized so consumers (ChatsList accordions) can safely depend on array
  // identity — a fresh map() result per render caused an infinite effect loop.
  const list = useMemo(
    () =>
      conversations.flatMap((conv) =>
        conv.todoId
          ? []
          : [
              toConversationRow(
                conv,
                messagesByConversation[conv.id]?.length || 0,
              ),
            ],
      ),
    [conversations, messagesByConversation],
  );

  return {
    conversations: list,
    paginationMeta: null,
  };
};

/** One conversation by id, listed or not — a tracked todo's chat included. */
export const useConversationRow = (
  conversationId: string | undefined,
): ConversationRow | undefined => {
  const conversation = useChatStore((state) =>
    state.conversations.find((conv) => conv.id === conversationId),
  );
  const messageCount = useChatStore((state) =>
    conversationId
      ? (state.messagesByConversation[conversationId]?.length ?? 0)
      : 0,
  );

  return useMemo(
    () =>
      conversation ? toConversationRow(conversation, messageCount) : undefined,
    [conversation, messageCount],
  );
};
