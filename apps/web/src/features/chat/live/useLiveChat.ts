import { TOOL_CALLS_DATA_TOOL_NAME } from "@shared/chat";
import {
  type ConversationView,
  DISPLAY_STATE,
  DISPLAY_STATUS_TEXT,
  type DisplayState,
  sendingLoadingRow,
} from "@shared/conversation";
import { useEffect, useMemo } from "react";
import { useApprovalSettlementStore } from "@/features/chat/stores/approvalSettlementStore";
import { readToolDataLoadingHints } from "@/features/chat/utils/loadingHints";
import {
  type ActiveToolInfo,
  useAuxLoadingStore,
} from "@/stores/auxLoadingStore";
import { useChatStore } from "@/stores/chatStore";
import type { MessageType } from "@/types/features/convoTypes";
import { getRandomThinkingMessage } from "@/utils/playfulThinking";
import { openConversation } from "./connection";
import {
  useLiveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";
import { liveMessages } from "./liveMessages";

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
  const verdicts = useApprovalSettlementStore((state) => state.settled);
  return useMemo(
    () => liveMessages(view, sends, verdicts),
    [view, sends, verdicts],
  );
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
function useLiveLoading(conversationId: string | null): LiveLoading {
  const { view, sends } = useLiveConversation(conversationId);
  const aux = useAuxLoadingStore((state) => state.auxLoading);
  const row = sendingLoadingRow(view, sends);
  const { status } = row;
  // One playful line per thinking phase, not a new one per frame.
  const thinkingText = useMemo(
    () => (status === DISPLAY_STATE.THINKING ? getRandomThinkingMessage() : ""),
    [status],
  );
  if (row.visible) {
    return {
      isLoading: true,
      loadingText:
        row.detail ??
        (status === DISPLAY_STATE.THINKING
          ? thinkingText
          : DISPLAY_STATUS_TEXT[status]),
      toolInfo: newestToolInfo(view),
    };
  }
  if (aux) {
    return { isLoading: true, loadingText: aux.text, toolInfo: aux.toolInfo };
  }
  return { isLoading: false, loadingText: "" };
}

/** Whether a reply is streaming into the conversation on screen. */
export function useActiveReplyStreaming(): boolean {
  const conversationId = useChatStore((state) => state.activeConversationId);
  return useLiveConversationStore((state) =>
    conversationId
      ? (state.conversations[conversationId]?.view.drafts.some(
          (draft) => draft.source === "reply",
        ) ?? false)
      : false,
  );
}

/** The loading row of the conversation on screen. */
export function useActiveLiveLoading(): LiveLoading {
  return useLiveLoading(useChatStore((state) => state.activeConversationId));
}
