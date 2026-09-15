"use client";

import { useEffect, useRef } from "react";

import { useIsPaid } from "@/features/pricing/hooks/useIsPaid";
import { useSendMessage } from "@/hooks/useSendMessage";
import { useComposerStore } from "@/stores/composerStore";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

/**
 * Runs a workflow the user picked outside the composer (sidebar, workflow
 * page) as a real chat turn.
 *
 * Hosted at ChatPage, not Composer: ChatPage is memoized and never
 * remounts, while Composer remounts across the NewChatLayout ->
 * ChatWithMessages switch (hasMessages flipping true), which would reset the once-only guard (autoSendFiredRef) and fire twice.
 */
export const useWorkflowAutoSend = (): void => {
  const sendMessage = useSendMessage();
  const selectedWorkflow = useComposerStore((s) => s.selectedWorkflow);
  const autoSend = useComposerStore((s) => s.workflowAutoSend);
  const { isPaid, isUnknown: isSubscriptionStatusUnknown } = useIsPaid();
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  // Exactly-once guard for the deferred auto-send below. Set inside the timer
  // callback (not at schedule time) so StrictMode's simulated remount and
  // dep-driven re-runs reschedule instead of assuming the send already fired.
  const autoSendFiredRef = useRef(false);

  useEffect(() => {
    if (!(selectedWorkflow && autoSend)) return;
    if (autoSendFiredRef.current) return;

    const workflow = selectedWorkflow;

    // Defer one macrotask, then clear+send inside the callback: clearing in
    // the effect body would re-render before the macrotask fires, cancelling
    // the send (e2e-verified regression) — clearing in-callback makes a superseding cleanup a no-op.
    const sendTimer = setTimeout(() => {
      autoSendFiredRef.current = true;
      useComposerStore.getState().clearSelectedWorkflow();

      // GAIA is paid-only: useComposerSubmit's pre-check never runs for this
      // path (handleFormSubmit returns early on `autoSend`), so this is the
      // one gate — while unknown, proceed since the backend's 402 is the backstop.
      if (!isSubscriptionStatusUnknown && !isPaid) {
        openUpgradeModal(undefined, { source: "workflow_autosend" });
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
    openUpgradeModal,
  ]);
};
