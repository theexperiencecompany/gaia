import {
  DISPLAY_STATE,
  DISPLAY_STATUS_TEXT,
  sendingLoadingRow,
} from "@gaia/shared/conversation";
import { useApprovalSettlementStore } from "@gaia/shared/conversation/live";
import { getRandomThinkingMessage } from "@gaia/shared/utils";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { AppState } from "react-native";
import { chatApi, type Message } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import { applyConversationPage, openConversation } from "./connection";
import {
  useLiveConversation,
  useLiveConversationStore,
} from "./live-conversation-store";
import { liveMessages } from "./live-messages";

/**
 * Follow the conversation's events while its screen is mounted and the app is in
 * the foreground; coming back resumes from where the view left off.
 */
export function useOpenConversation(conversationId: string | null): void {
  const [foreground, setForeground] = useState(
    AppState.currentState === "active",
  );
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) =>
      setForeground(state === "active"),
    );
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    if (!conversationId || !foreground) return;
    return openConversation(conversationId);
  }, [conversationId, foreground]);
}

/** The conversation's rows from its event stream, in the shape the chat bubbles render. */
export function useLiveMessages(conversationId: string | null): Message[] {
  const { view, sends } = useLiveConversation(conversationId);
  const verdicts = useApprovalSettlementStore((state) => state.settled);
  return useMemo(
    () => liveMessages(view, sends, new Date(), verdicts),
    [view, sends, verdicts],
  );
}

export interface LiveLoading {
  visible: boolean;
  text: string;
}

/** The loading row: shown whenever GAIA owes the user something in this conversation. */
export function useLiveLoading(conversationId: string | null): LiveLoading {
  const { view, sends } = useLiveConversation(conversationId);
  const row = sendingLoadingRow(view, sends);
  // One playful line per thinking phase, not a new one per frame.
  const thinkingText = useMemo(
    () =>
      row.status === DISPLAY_STATE.THINKING ? getRandomThinkingMessage() : "",
    [row.status],
  );
  if (!row.visible) return { visible: false, text: "" };
  return {
    visible: true,
    text:
      row.detail ??
      (row.status === DISPLAY_STATE.THINKING
        ? thinkingText
        : DISPLAY_STATUS_TEXT[row.status]),
  };
}

/** The conversations GAIA is busy in right now, as far as this device follows them. */
export function useBusyConversationIds(): ReadonlySet<string> {
  const conversations = useLiveConversationStore(
    (state) => state.conversations,
  );
  return useMemo(
    () =>
      new Set(
        Object.entries(conversations)
          .filter(([, live]) => live.view.display !== DISPLAY_STATE.IDLE)
          .map(([id]) => id),
      ),
    [conversations],
  );
}

/** Fetch the conversation's newest page and fold it into the live view, over the saved log. */
async function loadNewestPage(conversationId: string): Promise<number> {
  const page = await chatApi.fetchConversationPage(conversationId);
  await applyConversationPage(conversationId, page);
  return page.state.head;
}

export function useConversationPageQuery(conversationId: string | null) {
  return useQuery({
    queryKey: chatKeys.page(conversationId!),
    queryFn: () => loadNewestPage(conversationId!),
    enabled: !!conversationId && !conversationId.startsWith("temp-"),
    // Short staleness window: the saved log renders at once, but revisiting a
    // conversation revalidates quickly enough that other devices' messages appear.
    staleTime: 15_000,
  });
}
