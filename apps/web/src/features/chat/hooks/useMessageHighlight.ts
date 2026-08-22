"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Two-phase scroll-to-message highlight, split into two effects so each timer
 * is owned by its own cleanup. Phase 1 pops the element (scale 1.07) after a
 * short delay; phase 2 resets it (scale 1) once it has popped.
 */
export function useMessageHighlight() {
  const [highlightedMessageId, setHighlightedMessageId] = useState<
    string | null
  >(null);
  const [poppedMessageId, setPoppedMessageId] = useState<string | null>(null);

  useEffect(() => {
    if (!highlightedMessageId) return;
    const messageElement = document.getElementById(highlightedMessageId);
    if (!messageElement) return;

    messageElement.style.transition = "all 0.3s ease";

    const popTimer = setTimeout(() => {
      messageElement.style.scale = "1.07";
      setPoppedMessageId(highlightedMessageId);
    }, 700);

    return () => clearTimeout(popTimer);
  }, [highlightedMessageId]);

  useEffect(() => {
    if (!poppedMessageId) return;
    const messageElement = document.getElementById(poppedMessageId);
    if (!messageElement) return;

    const resetTimer = setTimeout(() => {
      messageElement.style.scale = "1";
    }, 300);

    return () => clearTimeout(resetTimer);
  }, [poppedMessageId]);

  const scrollToMessage = useCallback((messageId: string) => {
    if (!messageId) return;

    const messageElement = document.getElementById(messageId);

    if (!messageElement) return;

    messageElement.scrollIntoView({ behavior: "smooth", block: "start" });
    setHighlightedMessageId(messageId);
  }, []);

  return { scrollToMessage };
}
