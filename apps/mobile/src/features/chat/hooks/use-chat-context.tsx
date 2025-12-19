import { createContext, type ReactNode, useContext, useState } from "react";

interface ChatContextValue {
  activeChatId: string | null;
  setActiveChatId: (chatId: string | null) => void;
  createNewChat: () => string;
}

const ChatContext = createContext<ChatContextValue | undefined>(undefined);

interface ChatProviderProps {
  children: ReactNode;
}

export function ChatProvider({ children }: ChatProviderProps) {
  const [activeChatId, setActiveChatId] = useState<string | null>(null);

  const createNewChat = (): string => {
    const newChatId = `chat-${Date.now()}`;
    setActiveChatId(newChatId);
    return newChatId;
  };

  return (
    <ChatContext.Provider
      value={{ activeChatId, setActiveChatId, createNewChat }}
    >
      {children}
    </ChatContext.Provider>
  );
}

export function useChatContext(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error("useChatContext must be used within a ChatProvider");
  }
  return context;
}
