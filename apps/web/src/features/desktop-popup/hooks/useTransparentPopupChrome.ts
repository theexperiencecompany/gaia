"use client";

import { useEffect } from "react";
import { useLoginModalStore } from "@/stores/loginModalStore";

/**
 * Prepares a popup window's document chrome: the Electron window
 * supplies the glassy vibrancy backdrop, so the page must keep the
 * document background fully transparent. The login modal is suppressed —
 * the popup has its own compact sign-in affordance.
 *
 * Shared by both popup windows (composer + feed) so the two never drift.
 */
export function useTransparentPopupChrome(): void {
  useEffect(() => {
    const loginModal = useLoginModalStore.getState();
    loginModal.suppressModal();

    const html = document.documentElement;
    const body = document.body;
    const previousHtmlBackground = html.style.background;
    const previousBodyBackground = body.style.background;
    html.style.background = "transparent";
    body.style.background = "transparent";
    return () => {
      // Lift suppression so the modal works again in any non-popup window
      // that reuses this renderer process.
      loginModal.unsuppressModal();
      html.style.background = previousHtmlBackground;
      body.style.background = previousBodyBackground;
    };
  }, []);
}
