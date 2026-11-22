"use client";

import { DISPLAY_STATE } from "@shared/conversation";
import { useConversationDisplay } from "@/features/chat/live/useLiveChat";
import { useChatStore } from "@/stores/chatStore";

export type ComposerSendMode = "send" | "stop";

/**
 * The send button's mode: Stop while GAIA is busy in this conversation and the
 * composer is empty, Send otherwise. Typing always sends; nothing is held.
 *
 * Shared by `SendStopButton` and `ComposerRight` so they never drift apart.
 */
export function useComposerSendMode(hasContent: boolean) {
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );
  const isBusy =
    useConversationDisplay(activeConversationId) !== DISPLAY_STATE.IDLE;
  const showStop = isBusy && !hasContent;
  const mode: ComposerSendMode = showStop ? "stop" : "send";
  return { showStop, mode };
}
