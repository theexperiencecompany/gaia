"use client";

import { AssistantPopup } from "@/features/desktop-popup";
import { useTransparentPopupChrome } from "@/features/desktop-popup/hooks/useTransparentPopupChrome";

/**
 * Assistant popup window content. The Electron window provides the
 * glassy vibrancy backdrop, so this page keeps the document background
 * transparent and suppresses the login modal (see the shared hook).
 */
export default function DesktopPopupPage() {
  useTransparentPopupChrome();

  return <AssistantPopup />;
}
