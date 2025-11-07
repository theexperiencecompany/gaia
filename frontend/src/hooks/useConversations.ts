import { useEffect } from "react";

import { db, type IConversation } from "@/lib/db/chatDb";
import { batchSyncConversations } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";

type ChatStoreState = ReturnType<typeof useChatStore.getState>;

const selectConversations = (state: ChatStoreState) => state.conversations;
const selectLoadingStatus = (state: ChatStoreState) =>
  state.conversationsLoadingStatus;
const selectSetConversations = (state: ChatStoreState) =>
  state.setConversations;
const selectSetLoadingStatus = (state: ChatStoreState) =>
  state.setConversationsLoadingStatus;

type ConversationsHookResult = {
  conversations: IConversation[];
  conversationsLoadingStatus: ChatStoreState["conversationsLoadingStatus"];
};

export const useConversations = (): ConversationsHookResult => {
  const conversations = useChatStore(selectConversations);
  const conversationsLoadingStatus = useChatStore(selectLoadingStatus);
  const setConversations = useChatStore(selectSetConversations);
  const setLoadingStatus = useChatStore(selectSetLoadingStatus);

  useEffect(() => {
    let isActive = true;

    const hydrateFromCacheAndNetwork = async () => {
      setLoadingStatus("loading");

      try {
        const cachedConversations = await db.getAllConversations();
        if (isActive) {
          setConversations(cachedConversations);
        }
      } catch {
        // Ignore cache read errors and proceed with network fetch
      }

      try {
        await batchSyncConversations();

        if (!isActive) return;

        const updatedConversations = await db.getAllConversations();
        setConversations(updatedConversations);
        setLoadingStatus("success");
      } catch {
        if (!isActive) return;
        setLoadingStatus("error");
      }
    };

    hydrateFromCacheAndNetwork();

    return () => {
      isActive = false;
    };
  }, [setConversations, setLoadingStatus]);

  return {
    conversations,
    conversationsLoadingStatus,
  };
};
