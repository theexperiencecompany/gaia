"use client";

import { useEffect, useRef } from "react";

import { useSendMessage } from "@/hooks/useSendMessage";
import {
  useComposerTextActions,
  usePendingPrompt,
  usePendingPromptAutoSend,
} from "@/stores/composerStore";

/**
 * Delivers a prompt staged in the composer store: either straight into the
 * composer, or — for onboarding's web path — sent as the user's own turn into
 * a new conversation, so they see their bubble and GAIA's streamed reply
 * rather than a pre-filled composer they still have to submit.
 */
export const usePendingPromptDelivery = (
  appendToInputRef: React.RefObject<((text: string) => void) | null>,
): void => {
  const pendingPrompt = usePendingPrompt();
  const pendingPromptAutoSend = usePendingPromptAutoSend();
  const { clearPendingPrompt } = useComposerTextActions();
  const sendMessage = useSendMessage();
  // Exactly-once guard: the auto-send clears the store, but StrictMode's
  // simulated remount re-runs the effect before the clear has propagated.
  const pendingAutoSendFiredRef = useRef(false);

  useEffect(() => {
    if (!pendingPrompt) return;

    if (pendingPromptAutoSend) {
      if (pendingAutoSendFiredRef.current) return;
      pendingAutoSendFiredRef.current = true;
      clearPendingPrompt();
      sendMessage(pendingPrompt, {
        selectedTool: null,
        selectedToolCategory: null,
        conversationId: null,
      });
      return;
    }

    if (appendToInputRef.current) {
      appendToInputRef.current(pendingPrompt);
      clearPendingPrompt();
    }
  }, [
    pendingPrompt,
    pendingPromptAutoSend,
    clearPendingPrompt,
    appendToInputRef,
    sendMessage,
  ]);
};
