import { useChatStore } from "@/stores/chatStore";

export const useConversationList = () => {
  const conversations = useChatStore((state) => state.conversations);
  const messagesByConversation = useChatStore(
    (state) => state.messagesByConversation,
  );

  return {
    conversations: conversations.map((conv) => ({
      conversation_id: conv.id,
      description: conv.description || conv.title,
      title: conv.title,
      starred: conv.starred,
      is_system_generated: conv.isSystemGenerated,
      system_purpose: conv.systemPurpose,
      is_unread: conv.isUnread,
      user_id: conv.userId,
      created_at: conv.createdAt.toISOString(),
      updated_at: conv.updatedAt.toISOString(),
      createdAt: conv.createdAt,
      updatedAt: conv.updatedAt,
      messageCount: messagesByConversation[conv.id]?.length || 0,
    })),
    paginationMeta: null,
  };
};
