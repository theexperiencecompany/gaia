"use client";

import { useEffect, useRef } from "react";

import { useSendMessage } from "@/hooks/useSendMessage";
import {
  useComposerTextActions,
  usePendingPrompt,
  usePendingPromptAutoSend,
} from "@/stores/composerStore";

/**
 * Onboarding's web path: a prompt staged with the auto-send flag is sent as the
 * user's own turn into a new conversation, so they see their bubble and GAIA's
 * streamed reply rather than a pre-filled composer they still have to submit.
 *
 * Lives on the page, not the composer: this path never touches the input, and
 * the page is memoized so the once-only guard survives the composer's remount
 * across the NewChatLayout → ChatWithMessages switch. Prompts WITHOUT the flag
 * are composer text and are consumed by useComposerSeeds instead.
 */
export const useAutoSendPendingPrompt = (): void => {
  const pendingPrompt = usePendingPrompt();
  const pendingPromptAutoSend = usePendingPromptAutoSend();
  const { clearPendingPrompt } = useComposerTextActions();
  const sendMessage = useSendMessage();
  // Exactly-once guard: the auto-send clears the store, but StrictMode's
  // simulated remount re-runs the effect before the clear has propagated.
  const firedRef = useRef(false);

  useEffect(() => {
    if (!(pendingPrompt && pendingPromptAutoSend)) return;
    if (firedRef.current) return;
    firedRef.current = true;
    clearPendingPrompt();
    sendMessage(pendingPrompt, {
      selectedTool: null,
      selectedToolCategory: null,
      conversationId: null,
    });
  }, [pendingPrompt, pendingPromptAutoSend, clearPendingPrompt, sendMessage]);
};
