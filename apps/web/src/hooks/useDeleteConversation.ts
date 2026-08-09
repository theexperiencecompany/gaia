import { useCallback } from "react";

import { chatApi } from "@/features/chat/api/chatApi";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

type ChatStoreState = ReturnType<typeof useChatStore.getState>;

const selectRemoveConversation = (state: ChatStoreState) =>
  state.removeConversation;
const selectUpsertConversation = (state: ChatStoreState) =>
  state.upsertConversation;
const selectSetMessagesForConversation = (state: ChatStoreState) =>
  state.setMessagesForConversation;

// Best-effort restore of the deleted conversation into IndexedDB during
// rollback. If local persistence fails we proceed with the store update only.
async function restoreConversationCache(
  conversation: IConversation,
  messages: IMessage[],
): Promise<void> {
  try {
    await db.putConversation(conversation);
    if (messages.length > 0) {
      await db.putMessagesBulk(messages);
    }
  } catch {
    // If local persistence fails during rollback we proceed with store update only
  }
}

// Build the error to surface when either the server delete or the local delete
// failed; returns null when both succeeded.
function resolveDeletionFailure(
  apiRejected: boolean,
  dbRejected: boolean,
  rollbackError: unknown,
): Error | null {
  if (!apiRejected && !dbRejected) return null;

  if (rollbackError instanceof Error) return rollbackError;

  const message = apiRejected
    ? "Failed to delete conversation from server"
    : "Failed to delete conversation from local cache";
  return new Error(message);
}

export const useDeleteConversation = () => {
  const removeConversation = useChatStore(selectRemoveConversation);
  const upsertConversation = useChatStore(selectUpsertConversation);
  const setMessagesForConversation = useChatStore(
    selectSetMessagesForConversation,
  );

  return useCallback(
    async (conversationId: string) => {
      const snapshot = useChatStore.getState();
      const conversation: IConversation | undefined =
        snapshot.conversations.find((item) => item.id === conversationId);
      const messages: IMessage[] =
        snapshot.messagesByConversation[conversationId] ?? [];

      removeConversation(conversationId);

      const [dbResult, apiResult] = await Promise.allSettled([
        db.deleteConversationAndMessages(conversationId),
        chatApi.deleteConversation(conversationId),
      ]);

      if (dbResult.status === "fulfilled" && apiResult.status === "fulfilled") {
        return;
      }

      const rollbackError =
        apiResult.status === "rejected"
          ? apiResult.reason
          : dbResult.status === "rejected"
            ? dbResult.reason
            : undefined;

      if (conversation) {
        await restoreConversationCache(conversation, messages);
        upsertConversation(conversation);
        if (messages.length > 0) {
          setMessagesForConversation(conversationId, messages);
        }
      }

      const failure = resolveDeletionFailure(
        apiResult.status === "rejected",
        dbResult.status === "rejected",
        rollbackError,
      );
      if (failure) throw failure;
    },
    [removeConversation, setMessagesForConversation, upsertConversation],
  );
};
