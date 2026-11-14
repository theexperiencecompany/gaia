import type { ToolProgress } from "@shared/api/generated";
import {
  DISPLAY_STATE,
  DISPLAY_STATUS_TEXT,
  type DisplayState,
  type ScreenRow,
  screenRows,
  sendingLoadingRow,
} from "@shared/conversation";
import { useEffect, useMemo } from "react";
import {
  type ActiveToolInfo,
  useAuxLoadingStore,
} from "@/stores/auxLoadingStore";
import { useChatStore } from "@/stores/chatStore";
import { getRandomThinkingMessage } from "@/utils/playfulThinking";
import { openConversation } from "./connection";
import {
  useLiveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";

/** Follow the conversation's events while the component that shows it is mounted. */
export function useOpenConversation(conversationId: string | null): void {
  useEffect(() => {
    if (!conversationId) return;
    return openConversation(conversationId);
  }, [conversationId]);
}

/** The rows of the conversation's screen, in the server's order. */
export function useScreenRows(conversationId: string | null): ScreenRow[] {
  const { view } = useLiveConversation(conversationId);
  return useMemo(() => screenRows(view), [view]);
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

const toolInfo = (progress: ToolProgress): ActiveToolInfo => ({
  toolName: progress.tool_name,
  toolCategory: progress.tool_category,
  integrationName: progress.integration_name ?? undefined,
  iconUrl: progress.icon_url ?? undefined,
  showCategory: progress.show_category,
});

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
        row.progress?.message ??
        (status === DISPLAY_STATE.THINKING
          ? thinkingText
          : DISPLAY_STATUS_TEXT[status]),
      toolInfo: row.progress ? toolInfo(row.progress) : undefined,
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
      ? (state.conversations[conversationId]?.view.drafts.length ?? 0) > 0
      : false,
  );
}

/** The loading row of the conversation on screen. */
export function useActiveLiveLoading(): LiveLoading {
  return useLiveLoading(useChatStore((state) => state.activeConversationId));
}
