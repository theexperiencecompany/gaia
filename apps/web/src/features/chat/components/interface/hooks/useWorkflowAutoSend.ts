"use client";

import { useEffect, useRef } from "react";

import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useSendMessage } from "@/hooks/useSendMessage";
import { usePaywallModalStore } from "@/stores/paywallModalStore";
import { useWorkflowSelectionStore } from "@/stores/workflowSelectionStore";

/**
 * Runs a workflow the user picked outside the composer (sidebar, workflow page)
 * as a real chat turn.
 *
 * Hosted at ChatPage (not Composer) because ChatPage is memoized and never
 * remounts, whereas Composer remounts across the NewChatLayout →
 * ChatWithMessages layout switch that fires when the optimistic message flips
 * hasMessages to true. Keeping the once-only guard (autoSendFiredRef) here
 * stops that remount from resetting it and firing the workflow twice.
 */
export const useWorkflowAutoSend = (): void => {
  const sendMessage = useSendMessage();
  const selectedWorkflow = useWorkflowSelectionStore((s) => s.selectedWorkflow);
  const autoSend = useWorkflowSelectionStore((s) => s.autoSend);
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const openPaywallModal = usePaywallModalStore((s) => s.openModal);
  // Exactly-once guard for the deferred auto-send below. Set inside the timer
  // callback (not at schedule time) so StrictMode's simulated remount and
  // dep-driven re-runs reschedule instead of assuming the send already fired.
  const autoSendFiredRef = useRef(false);

  useEffect(() => {
    if (!(selectedWorkflow && autoSend)) return;
    if (autoSendFiredRef.current) return;

    const workflow = selectedWorkflow;

    // Defer one macrotask so navigation settles, then clear + send inside
    // the callback: clearing the store HERE (in the effect body) would
    // re-render before the macrotask fires, running this effect's cleanup
    // and cancelling the send — silently dropping the execution (an e2e-
    // verified regression). With the clear inside the callback, a cleanup
    // on supersede is harmless: firedRef makes the next pass a no-op.
    const sendTimer = setTimeout(() => {
      autoSendFiredRef.current = true;
      useWorkflowSelectionStore.getState().clearSelectedWorkflow();

      // GAIA is paid-only, and this is a real send: useComposerSubmit's own
      // pre-check never runs for this path (handleFormSubmit returns early
      // on `autoSend` before reaching it), so this is the one place that has
      // to gate it. While the subscription-status is still unknown, let the
      // send proceed — the backend's 402 is the backstop — rather than trap
      // a paying user on a not-yet-resolved "false".
      if (!isSubscriptionStatusUnknown && !isPaid) {
        openPaywallModal();
        return;
      }

      sendMessage("Run this workflow", {
        selectedWorkflow: workflow,
        selectedTool: null,
        selectedToolCategory: null,
        conversationId: null,
      });
    }, 0);

    // Supersede semantics: a genuinely NEW selection replaces the pending
    // send; genuine unmount cancels it (master's own behavior).
    return () => clearTimeout(sendTimer);
  }, [
    selectedWorkflow,
    autoSend,
    sendMessage,
    isPaid,
    isSubscriptionStatusUnknown,
    openPaywallModal,
  ]);
};
