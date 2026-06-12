"use client";

import { useCallback, useEffect } from "react";
import { useElectron } from "@/hooks/useElectron";
import { useLoadingStore } from "@/stores/loadingStore";

/**
 * The idle-guarded popup dismiss: closes the popup, but never mid-turn —
 * a streaming response (or an in-flight background task) would be lost
 * off-screen and the conversation would look broken.
 *
 * Returned as a callback so element-level handlers (the composer Input,
 * whose react-aria clear swallows Escape before it reaches the window)
 * can reuse the exact same guard.
 */
export function usePopupDismissGuard(): () => void {
  const { dismissPopup } = useElectron();
  return useCallback(() => {
    const { isLoading, isMainResponseStreaming } = useLoadingStore.getState();
    if (isLoading || isMainResponseStreaming) return;
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
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismissIfIdle]);
}
