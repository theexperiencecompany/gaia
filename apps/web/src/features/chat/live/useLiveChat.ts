import { TOOL_CALLS_DATA_TOOL_NAME } from "@shared/chat";
import {
  type ConversationView,
  DISPLAY_STATE,
  type DisplayState,
} from "@shared/conversation";
import { useEffect, useMemo } from "react";
import { readToolDataLoadingHints } from "@/features/chat/utils/loadingHints";
import {
  type ActiveToolInfo,
  useAuxLoadingStore,
} from "@/stores/auxLoadingStore";
import type { MessageType } from "@/types/features/convoTypes";
import { getRandomThinkingMessage } from "@/utils/playfulThinking";
import { openConversation } from "./connection";
import {
  useLiveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";
import { liveMessages } from "./liveMessages";
import { loadingRow } from "./selectors";

const STATUS_TEXT: Record<Exclude<DisplayState, "thinking">, string> = {
  [DISPLAY_STATE.IDLE]: "",
  [DISPLAY_STATE.WORKING]: "Working on it",
  [DISPLAY_STATE.AWAITING_APPROVAL]: "Waiting for your approval",
};

/** Follow the conversation's events while the component that shows it is mounted. */
export function useOpenConversation(conversationId: string | null): void {
  useEffect(() => {
    if (!conversationId) return;
    return openConversation(conversationId);
  }, [conversationId]);
}

/** The conversation's rows from its event stream, in the shape the chat bubbles render. */
export function useLiveMessages(conversationId: string | null): MessageType[] {
  const { view, sends } = useLiveConversation(conversationId);
  return useMemo(() => liveMessages(view, sends), [view, sends]);
}

/** What the server says GAIA is doing in this conversation; idle for one not open here. */
export function useConversationDisplay(
  conversationId: string | null,
): DisplayState {
  return useLiveConversationStore((state) =>
    conversationId
      ? (state.conversations[conversationId]?.view.display ??
        DISPLAY_STATE.IDLE)
      : DISPLAY_STATE.IDLE,
  );
}

function newestToolInfo(view: ConversationView): ActiveToolInfo | undefined {
  const entry = view.drafts
    .at(-1)
    ?.content.toolData.findLast(
      (candidate) => candidate.tool_name === TOOL_CALLS_DATA_TOOL_NAME,
    );
  const hints = entry ? readToolDataLoadingHints(entry.data) : null;
  if (!hints) return undefined;
  const { message: _message, ...toolInfo } = hints;
  return toolInfo;
}

export interface LiveLoading {
  isLoading: boolean;
  loadingText: string;
  toolInfo?: ActiveToolInfo;
}

/** The loading row: shown whenever GAIA owes the user something, or a voice or upload flow is busy. */
export function useLiveLoading(conversationId: string | null): LiveLoading {
  const { view, sends } = useLiveConversation(conversationId);
  const aux = useAuxLoadingStore((state) => state.auxLoading);
  const row = loadingRow(view);
  // A send the server has not accepted yet is owed a reply before any state frame says so.
  const sending = view.pending.some((pending) => !sends[pending.id]?.failed);
  const status = !row.visible && sending ? DISPLAY_STATE.THINKING : row.status;
  // One playful line per thinking phase, not a new one per frame.
  const thinkingText = useMemo(
    () => (status === DISPLAY_STATE.THINKING ? getRandomThinkingMessage() : ""),
    [status],
  );
  if (row.visible || sending) {
    return {
      isLoading: true,
      loadingText:
        row.detail ??
        (status === DISPLAY_STATE.THINKING
          ? thinkingText
          : STATUS_TEXT[status]),
      toolInfo: newestToolInfo(view),
    };
  }
  if (aux) {
    return { isLoading: true, loadingText: aux.text, toolInfo: aux.toolInfo };
  }
  return { isLoading: false, loadingText: "" };
}
