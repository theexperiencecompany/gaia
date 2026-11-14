import { type ConversationView, SCREEN_ITEM_KIND } from "@shared/conversation";
import { useMemo } from "react";
import { useLiveConversationStore } from "@/features/chat/live/liveConversationStore";
import type { IConversation } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

const MESSAGE_KINDS: ReadonlySet<string> = new Set([
  SCREEN_ITEM_KIND.USER,
  SCREEN_ITEM_KIND.REPLY,
  SCREEN_ITEM_KIND.NOTICE,
]);

/** The messages this device holds of a conversation's screen. */
const messageCount = (view: ConversationView | undefined): number =>
  view?.items.filter((item) => MESSAGE_KINDS.has(item.kind)).length ?? 0;

const toConversationRow = (conv: IConversation, messageCount: number) => ({
  conversation_id: conv.id,
  description: conv.description || conv.title,
  title: conv.title,
  starred: conv.starred,
  is_system_generated: conv.isSystemGenerated,
  system_purpose: conv.systemPurpose,
  is_unread: conv.isUnread,
  awaiting_approval: conv.awaitingApproval ?? false,
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
 * The conversations the user browses: every one the server lists. A client that
 * opened an unlisted chat (a todo's, a bot DM) keeps it in its local store.
 */
export const useConversationList = () => {
  const conversations = useChatStore((state) => state.conversations);
  const live = useLiveConversationStore((state) => state.conversations);

  // Memoized so consumers (ChatsList accordions) can safely depend on array
  // identity — a fresh map() result per render caused an infinite effect loop.
  const list = useMemo(
    () =>
      conversations.flatMap((conv) =>
        conv.listed === false
          ? []
          : [toConversationRow(conv, messageCount(live[conv.id]?.view))],
      ),
    [conversations, live],
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
  const count = useLiveConversationStore((state) =>
    conversationId
      ? messageCount(state.conversations[conversationId]?.view)
      : 0,
  );

  return useMemo(
    () => (conversation ? toConversationRow(conversation, count) : undefined),
    [conversation, count],
  );
};
