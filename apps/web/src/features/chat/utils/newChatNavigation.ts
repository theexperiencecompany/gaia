import { useChatStore } from "@/stores/chatStore";

/**
 * Prepares the app for a new chat by clearing relevant Zustand state.
 * Call this BEFORE navigating to /c to ensure messages clear immediately.
 */
export const prepareNewChat = () => {
  useChatStore.getState().setActiveConversationId(null);
  useChatStore.getState().clearOptimisticMessage();
};
