import type { MessageReaction } from "@shared/api/generated";
import { db } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

/** Set GAIA's reaction on a message in place of any earlier one: painted now, kept in IndexedDB for reload. */
export async function applyMessageReaction(
  conversationId: string,
  messageId: string,
  reaction: MessageReaction,
): Promise<void> {
  const store = useChatStore.getState();
  const shown = store.messagesByConversation[conversationId]?.find(
    (message) => message.id === messageId,
  );
  if (shown) store.updateMessageInPlace({ ...shown, reaction });
  await db.updateMessage(messageId, { reaction });
}
