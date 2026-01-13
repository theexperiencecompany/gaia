import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
} from "react";
import { useChatStore } from "@/stores/chat-store";

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

  const setActiveChatId = useCallback((chatId: string | null) => {
    useChatStore.getState().setActiveChatId(chatId);
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
