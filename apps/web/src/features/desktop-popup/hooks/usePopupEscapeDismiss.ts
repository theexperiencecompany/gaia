"use client";

import { DISPLAY_STATE } from "@shared/conversation";
import { useCallback, useEffect } from "react";
import { liveConversation } from "@/features/chat/live/liveConversationStore";
import { useElectron } from "@/hooks/useElectron";
import { useAuxLoadingStore } from "@/stores/auxLoadingStore";
import { useChatStore } from "@/stores/chatStore";

/**
 * The idle-guarded popup dismiss: closes the popup, but never while GAIA is
 * busy in the conversation — the reply would land off-screen.
 *
 * Returned as a callback so element-level handlers (the composer Input,
 * whose react-aria clear swallows Escape before it reaches the window)
 * can reuse the exact same guard.
 */
export function usePopupDismissGuard(): () => void {
  const { dismissPopup } = useElectron();
  return useCallback(() => {
    const id = useChatStore.getState().activeConversationId;
    const busy =
      id !== null && liveConversation(id).view.display !== DISPLAY_STATE.IDLE;
    if (busy || useAuxLoadingStore.getState().auxLoading) return;
    dismissPopup();
  }, [dismissPopup]);
}

/**
 * Window-level Escape-to-dismiss for a popup island. Mounted in both
 * popup windows (composer + feed) so the single source of dismiss logic
 * isn't copy-pasted per window.
 */
export function usePopupEscapeDismiss(): void {
  const dismissIfIdle = usePopupDismissGuard();
  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      dismissIfIdle();
    };
    globalThis.addEventListener("keydown", handleKeyDown);
    return () => globalThis.removeEventListener("keydown", handleKeyDown);
  }, [dismissIfIdle]);
}
