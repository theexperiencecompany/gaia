/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 */
import type { MessageType } from "@/types/features/convoTypes";

const EMPTY_MESSAGES: MessageType[] = Object.freeze([]) as MessageType[];

export const useConversation = (): {
  convoMessages: MessageType[];
  updateConvoMessages: () => void;
  clearMessages: () => void;
} => ({
  convoMessages: EMPTY_MESSAGES,
  updateConvoMessages: () => {},
  clearMessages: () => {},
});
