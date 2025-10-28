import { useShallow } from "zustand/react/shallow";

import { useConversationStore } from "@/stores/conversationStore";
import { MessageType } from "@/types/features/convoTypes";

export const useConversation = () => {
  const { messages, setMessages, resetMessages } = useConversationStore(
    useShallow((state) => ({
      messages: state.messages,
      setMessages: state.setMessages,
      resetMessages: state.resetMessages,
    })),
  );

  const updateConvoMessages = (
    updater: MessageType[] | ((oldMessages: MessageType[]) => MessageType[]),
  ): void => {
    const newMessages =
      typeof updater === "function" ? updater(messages) : updater;
    setMessages(newMessages);
  };

  const clearMessages = (): void => {
    resetMessages();
  };

  return {
    convoMessages: messages,
    updateConvoMessages,
    clearMessages,
  };
};
