import { useEffect } from "react";

import { chatApi, type Conversation } from "@/features/chat/api/chatApi";
import { db, type IConversation } from "@/lib/db/chatDb";
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
        const { conversations: apiConversations } =
          await chatApi.fetchConversations(1, 20);
        if (!isActive) return;

  const mappedConversations = mapApiConversations(apiConversations);

        try {
          await db.putConversationsBulk(mappedConversations);
        } catch {
          // Ignore persistence errors; UI state has already been updated from the network response
        }

        if (!isActive) return;

        setConversations(mappedConversations);
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

export const mapApiConversation = (
  conversation: Conversation,
): IConversation => ({
  id: conversation.conversation_id,
  title: conversation.description || "Untitled conversation",
  description: conversation.description,
  userId: conversation.user_id,
  starred: conversation.starred ?? false,
  isSystemGenerated: conversation.is_system_generated ?? false,
  systemPurpose: conversation.system_purpose ?? null,
  createdAt: new Date(conversation.createdAt),
  updatedAt: conversation.updatedAt
    ? new Date(conversation.updatedAt)
    : new Date(conversation.createdAt),
});

export const mapApiConversations = (
  conversations: Conversation[],
): IConversation[] => conversations.map(mapApiConversation);
