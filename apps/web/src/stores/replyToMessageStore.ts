import { create } from "zustand";
import { devtools } from "zustand/middleware";

/**
 * Data for the message being replied to.
 */
export interface ReplyToMessageData {
  id: string;
  content: string;
  role: "user" | "assistant";
}

interface ReplyToMessageState {
  replyToMessage: ReplyToMessageData | null;
  inputFocusCallback: (() => void) | null;
}

interface ReplyToMessageActions {
  setReplyToMessage: (message: ReplyToMessageData | null) => void;
  clearReplyToMessage: () => void;
  setInputFocusCallback: (callback: (() => void) | null) => void;
}

type ReplyToMessageStore = ReplyToMessageState & ReplyToMessageActions;

const initialState: ReplyToMessageState = {
  replyToMessage: null,
  inputFocusCallback: null,
};

export const useReplyToMessageStore = create<ReplyToMessageStore>()(
  devtools(
    (set, get) => ({
      ...initialState,

      setReplyToMessage: (message) => {
        set({ replyToMessage: message }, false, "setReplyToMessage");
        // Automatically focus input when reply is set
        if (message) {
          const callback = get().inputFocusCallback;
          if (callback) {
            // Small delay to ensure UI has updated
            setTimeout(() => callback(), 50);
          }
        }
      },

      clearReplyToMessage: () =>
        set({ replyToMessage: null }, false, "clearReplyToMessage"),

      setInputFocusCallback: (callback) =>
        set({ inputFocusCallback: callback }, false, "setInputFocusCallback"),
    }),
    { name: "reply-to-message-store" },
  ),
);

// Convenient hook for accessing reply-to-message state and actions
export const useReplyToMessage = () => {
  const {
    replyToMessage,
    setReplyToMessage,
    clearReplyToMessage,
    setInputFocusCallback,
  } = useReplyToMessageStore();

  return {
    replyToMessage,
    setReplyToMessage,
    clearReplyToMessage,
    setInputFocusCallback,
  };
};
