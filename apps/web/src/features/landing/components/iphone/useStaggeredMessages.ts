/**
 * Staggered message cascade for `ChatDemo`. Replays a script over time:
 * shows a typing indicator, then the next bubble, then waits, then types
 * again. Used by the landing BotsShowcaseSection and the onboarding
 * platforms preview so they share one cadence and one re-mount story.
 */

"use client";

import { useEffect, useMemo, useState } from "react";
import type { ChatMessageItem } from "./ChatDemo";

const TYPING_DELAY_MS = 450;
const TYPING_DURATION_MS = 850;

export function useStaggeredMessages(
  messages: ChatMessageItem[],
  enabled: boolean,
): ChatMessageItem[] {
  const [visibleCount, setVisibleCount] = useState(1);
  const [showTyping, setShowTyping] = useState(false);

  useEffect(() => {
    setVisibleCount(1);
    setShowTyping(false);
    if (!enabled) return;
    if (messages.length <= 1) return;

    const timers: ReturnType<typeof setTimeout>[] = [];
    let elapsed = 0;
    for (let i = 1; i < messages.length; i++) {
      elapsed += TYPING_DELAY_MS;
      timers.push(setTimeout(() => setShowTyping(true), elapsed));
      elapsed += TYPING_DURATION_MS;
      timers.push(
        setTimeout(() => {
          setShowTyping(false);
          setVisibleCount((c) => c + 1);
        }, elapsed),
      );
    }

    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [messages, enabled]);

  return useMemo(() => {
    const real = messages.slice(0, visibleCount).map((m, i) => ({
      ...m,
      id: m.id ?? `msg-${i}`,
    }));
    if (!showTyping || visibleCount >= messages.length) return real;
    const next = messages[visibleCount];
    return [
      ...real,
      {
        id: `typing-${visibleCount}`,
        from: next.from,
        author: next.author,
        avatar: next.avatar,
        authorColor: next.authorColor,
        typing: true,
      },
    ];
  }, [messages, visibleCount, showTyping]);
}

export function cascadeDurationMs(messageCount: number): number {
  return Math.max(0, messageCount - 1) * (TYPING_DELAY_MS + TYPING_DURATION_MS);
}
