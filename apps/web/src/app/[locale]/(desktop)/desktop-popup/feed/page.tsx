"use client";

import { useEffect } from "react";
import PopupFeed from "@/features/desktop-popup/components/PopupFeed";
import { usePopupChatConsumer } from "@/features/desktop-popup/sync";
import { useElectron } from "@/hooks/useElectron";
import { useLoadingStore } from "@/stores/loadingStore";
import { useLoginModalStore } from "@/stores/loginModalStore";

/**
 * Conversation island of the assistant popup — its own liquid-glass
 * window below the composer pill. Render-only: state is mirrored from
 * the composer window over a BroadcastChannel. Reports its content
 * height so the main process sizes (and shows/hides) the window.
 */
export default function DesktopPopupFeedPage() {
  const { dismissPopup, resizePopup } = useElectron();

  usePopupChatConsumer();

  useEffect(() => {
    useLoginModalStore.getState().suppressModal();

    const html = document.documentElement;
    const body = document.body;
    const previousHtmlBackground = html.style.background;
    const previousBodyBackground = body.style.background;
    html.style.background = "transparent";
    body.style.background = "transparent";
    return () => {
      html.style.background = previousHtmlBackground;
      body.style.background = previousBodyBackground;
    };
  }, []);

  // Report content height so the window grows with the conversation
  // (main clamps to the screen budget and hides it when empty).
  useEffect(() => {
    const content = document.querySelector<HTMLElement>(
      "[data-popup-feed-content]",
    );
    if (!content) return;

    const report = () => resizePopup(content.scrollHeight);
    const observer = new ResizeObserver(report);
    observer.observe(content);
    report();
    return () => observer.disconnect();
  }, [resizePopup]);

  useEffect(() => {
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const { isLoading, isMainResponseStreaming } = useLoadingStore.getState();
      if (isLoading || isMainResponseStreaming) return;
      dismissPopup();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [dismissPopup]);

  return (
    <div className="h-screen overflow-hidden text-zinc-100">
      <PopupFeed />
    </div>
  );
}
