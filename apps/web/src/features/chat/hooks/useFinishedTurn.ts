"use client";

import { useEffect, useRef, useState } from "react";
import { randomUnit } from "@/lib/random";
import type { MessageType } from "@/types/features/convoTypes";

/**
 * The id of the last bot message, once a reply finishes while this view is
 * open and the roll at that moment lands under chance; null otherwise. A
 * conversation opened from history never qualifies, and each reply rolls once.
 */
export function useFinishedTurn(
  messages: readonly MessageType[],
  isBusy: boolean,
  conversationId: string | null,
  chance: number,
): string | null {
  const [finished, setFinished] = useState<{
    conversationId: string | null;
    turnId: string;
  } | null>(null);
  const wasBusy = useRef(isBusy);

  useEffect(() => {
    const justFinished = wasBusy.current && !isBusy;
    wasBusy.current = isBusy;
    if (!justFinished) return;
    const last = messages.at(-1);
    if (last?.type !== "bot" || !last.message_id) return;
    if (randomUnit() >= chance) return;
    setFinished({ conversationId, turnId: last.message_id });
  }, [isBusy, messages, conversationId, chance]);

  return finished?.conversationId === conversationId ? finished.turnId : null;
}
