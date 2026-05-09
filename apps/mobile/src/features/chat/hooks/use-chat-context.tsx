import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { InteractionManager } from "react-native";
import { chatDb } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chat-store";
import type { Message } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import type { Conversation } from "../types";

interface ChatContextValue {
  activeChatId: string | null;
  setActiveChatId: (chatId: string | null) => void;
  createNewChat: () => string;
  clearActiveMessages: () => void;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

export function ChatProvider({ children }: ChatProviderProps) {
  const activeChatId = useChatStore((state) => state.activeChatId);
  const queryClient = useQueryClient();

  useEffect(() => {
    useChatStore.getState().hydrate();

    // Seed the conversations React Query cache from AsyncStorage so the
    // sidebar list renders instantly on launch (web parity — Zustand+IDB).
    // After seeding, invalidate so a background network sync still runs.
    const cacheKey = chatKeys.conversations();
    chatDb.getConversations().then((cached) => {
      if (cached.length > 0) {
        queryClient.setQueryData(
          cacheKey,
          (existing: Conversation[] | undefined) => existing ?? cached,
        );
      }
      queryClient.invalidateQueries({ queryKey: cacheKey });
    });

    // Pre-warm messages for every cached conversation in one multiGet so
    // tapping any chat in the sidebar is instant (no skeleton flash). Web
    // does the equivalent with a single Dexie getAllMessages at module load.
    // Deferred via InteractionManager so the JSON.parse work doesn't compete
    // with the initial render/animation frame and trigger an ANR.
    const interaction = InteractionManager.runAfterInteractions(() => {
      chatDb.getAllMessages().then((messagesByConversation) => {
        for (const [conversationId, messages] of messagesByConversation) {
          if (messages.length === 0) continue;
          queryClient.setQueryData(
            chatKeys.messages(conversationId),
            (existing: Message[] | undefined) => existing ?? messages,
          );
        }
        // Mark all messages queries stale so the next time a conversation is
        // opened, React Query revalidates against the API in the background
        // (cached messages stay on screen — stale-while-revalidate). Without
        // this, the seeded data would stay "fresh" for the 5min staleTime,
        // suppressing any background sync until the user idled past it.
        queryClient.invalidateQueries({
          queryKey: [...chatKeys.all, "messages"],
        });
      });
    });

    return () => {
      interaction.cancel();
    };
  }, [queryClient]);

  const setActiveChatId = useCallback((chatId: string | null) => {
    const normalizedChatId = chatId?.trim() || null;
    const currentActiveChatId = useChatStore.getState().activeChatId;

    if (currentActiveChatId === normalizedChatId) {
      return;
    }

    useChatStore.getState().setActiveChatId(normalizedChatId);
  }, []);

  const createNewChat = useCallback((): string => {
    const newChatId = `chat-${Date.now()}`;
    useChatStore.getState().setActiveChatId(newChatId);
    return newChatId;
  }, []);

  const clearActiveMessages = useCallback(() => {
    const store = useChatStore.getState();
    const currentChatId = store.activeChatId;
    if (currentChatId) {
      store.clearMessages(currentChatId);
    }
    store.setStreamingState({
      isTyping: false,
      isStreaming: false,
      conversationId: null,
      progress: null,
    });
  }, []);

  const value = useMemo(
    () => ({
      activeChatId,
      setActiveChatId,
      createNewChat,
      clearActiveMessages,
    }),
    [activeChatId, setActiveChatId, createNewChat, clearActiveMessages],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChatContext(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within a ChatProvider");
  }
  return context;
}
