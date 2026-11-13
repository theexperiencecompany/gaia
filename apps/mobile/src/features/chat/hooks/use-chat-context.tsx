import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
} from "react";
import { AppState, InteractionManager } from "react-native";
import { chatDb } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chat-store";
import { chatKeys } from "../api/queries";
import type { Conversation } from "../types";

interface ChatContextValue {
  activeChatId: string | null;
  setActiveChatId: (chatId: string | null) => void;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

export function ChatProvider({ children }: ChatProviderProps) {
  const activeChatId = useChatStore((state) => state.activeChatId);
  const queryClient = useQueryClient();

  useEffect(() => {
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

    // Deferred via InteractionManager so a launch never blocks on storage.
    const interaction = InteractionManager.runAfterInteractions(() => {
      chatDb.dropRetiredMessages();
    });

    return () => {
      interaction.cancel();
    };
  }, [queryClient]);

  // Foreground sync: while the app is backgrounded, messages and conversations
  // may change on other devices (or via push). Revalidate both when the user
  // returns — cached data stays on screen until fresh data lands.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        queryClient.invalidateQueries({ queryKey: chatKeys.conversations() });
        queryClient.invalidateQueries({
          queryKey: [...chatKeys.all, "page"],
        });
      }
    });
    return () => subscription.remove();
  }, [queryClient]);

  const setActiveChatId = useCallback((chatId: string | null) => {
    const normalizedChatId = chatId?.trim() || null;
    const currentActiveChatId = useChatStore.getState().activeChatId;

    if (currentActiveChatId === normalizedChatId) {
      return;
    }

    useChatStore.getState().setActiveChatId(normalizedChatId);
  }, []);

  const value = useMemo(
    () => ({ activeChatId, setActiveChatId }),
    [activeChatId, setActiveChatId],
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
