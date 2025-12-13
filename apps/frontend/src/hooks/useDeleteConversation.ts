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
        try {
          await db.putConversation(conversation);
          if (messages.length > 0) {
            await db.putMessagesBulk(messages);
          }
        } catch {
          // If local persistence fails during rollback we proceed with store update only
        }

        upsertConversation(conversation);
        if (messages.length > 0) {
          setMessagesForConversation(conversationId, messages);
        }
      }

      if (apiResult.status === "rejected" || dbResult.status === "rejected") {
        if (rollbackError instanceof Error) {
          throw rollbackError;
        }

        const message =
          apiResult.status === "rejected"
            ? "Failed to delete conversation from server"
            : "Failed to delete conversation from local cache";

        throw new Error(message);
      }
    },
    [removeConversation, setMessagesForConversation, upsertConversation],
  );
};
