"use client";

import { useEffect } from "react";
import { AssistantPopup } from "@/features/desktop-popup";

/**
 * Assistant popup window content. The Electron window provides the
 * glassy vibrancy backdrop, so this page must keep the document
 * background fully transparent.
 */
export default function DesktopPopupPage() {
  useEffect(() => {
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

  return <AssistantPopup />;
}
