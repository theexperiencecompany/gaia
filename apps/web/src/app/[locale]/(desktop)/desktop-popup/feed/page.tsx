"use client";

import { useEffect } from "react";
import { useConversation } from "@/features/chat/hooks/useConversation";
import PopupFeed from "@/features/desktop-popup/components/PopupFeed";
import { usePopupEscapeDismiss } from "@/features/desktop-popup/hooks/usePopupEscapeDismiss";
import { useTransparentPopupChrome } from "@/features/desktop-popup/hooks/useTransparentPopupChrome";
import { usePopupChatConsumer } from "@/features/desktop-popup/sync";
import { useElectron } from "@/hooks/useElectron";
import { usePaywallModalStore } from "@/stores/paywallModalStore";
import { useActiveLoading } from "@/stores/streamStore";

/**
 * Conversation island of the assistant popup — its own liquid-glass
 * window below the composer pill. Render-only: state is mirrored from
 * the composer window over a BroadcastChannel. Reports its content
 * height so the main process sizes (and shows/hides) the window.
 */
export default function DesktopPopupFeedPage() {
  const { resizePopup } = useElectron();

  usePopupChatConsumer();
  useTransparentPopupChrome();
  usePopupEscapeDismiss();

  // Report content height so the window grows with the conversation
  // (main clamps to the screen budget and hides it when empty). An
  // empty conversation reports 0 — padding alone must not summon an
  // empty glass card.
  const { convoMessages } = useConversation();
  const { isLoading } = useActiveLoading();
  // A paid-only block is content too: a free user's very first send produces
  // no messages at all, so without this the window stays hidden and the
  // paywall notice never reaches the screen.
  const isPaywalled = usePaywallModalStore((s) => s.open);
  const hasContent =
    (convoMessages?.length ?? 0) > 0 || isLoading || isPaywalled;
  useEffect(() => {
    const content = document.querySelector<HTMLElement>(
      "[data-popup-feed-content]",
    );
    if (!content) return;

    const report = () => resizePopup(hasContent ? content.scrollHeight : 0);
    const observer = new ResizeObserver(report);
    observer.observe(content);
    report();
    return () => observer.disconnect();
  }, [resizePopup, hasContent]);

  return (
    <div className="h-screen overflow-hidden text-zinc-100">
      <PopupFeed />
    </div>
  );
}
