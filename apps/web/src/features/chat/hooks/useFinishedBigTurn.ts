"use client";

import { TOOL_CALLS_DATA_TOOL_NAME, type ToolCallEntry } from "@shared/chat";
import { useEffect, useRef, useState } from "react";
import type { MessageType } from "@/types/features/convoTypes";

/** A turn that ran at least this many tools counts as a big task. */
const BIG_TASK_TOOL_CALLS = 3;

/** Tool calls the bot made since the user's last message. */
function lastTurnToolCalls(messages: readonly MessageType[]): number {
  let calls = 0;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.type === "user") break;
    for (const entry of message.tool_data ?? []) {
      if (entry.tool_name !== TOOL_CALLS_DATA_TOOL_NAME) continue;
      const steps = (
        Array.isArray(entry.data) ? entry.data : [entry.data]
      ) as ToolCallEntry[];
      // Thinking steps ride the same stream but are not tools the turn ran.
      calls += steps.filter((step) => !step.reasoning).length;
    }
  }
  return calls;
}

/**
 * The id of the last bot message, once a big task finishes while this view is
 * open; null otherwise. A conversation opened from history never qualifies,
 * so only work the user just watched can earn a follow-up card.
 */
export function useFinishedBigTurn(
  messages: readonly MessageType[],
  isBusy: boolean,
  conversationId: string | null,
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
    if (lastTurnToolCalls(messages) < BIG_TASK_TOOL_CALLS) return;
    setFinished({ conversationId, turnId: last.message_id });
  }, [isBusy, messages, conversationId]);

  return finished?.conversationId === conversationId ? finished.turnId : null;
}
