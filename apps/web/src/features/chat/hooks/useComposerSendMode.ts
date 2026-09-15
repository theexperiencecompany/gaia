"use client";

import { useActiveComposerLocked } from "@/stores/streamStore";

export type ComposerSendMode = "send" | "stop" | "queue";

/**
 * Derives the composer send-button mode from whether the turn is "open" (spans
 * the initial response and the held window while a background executor runs
 * over the same SSE) and whether the composer has content.
 *
 * Shared by `SendStopButton` and `ComposerRight` so they never drift apart.
 */
export function useComposerSendMode(hasContent: boolean) {
  const isStreaming = useActiveComposerLocked();

  const showQueue = isStreaming && hasContent;
  const showStop = isStreaming && !hasContent;
  let mode: ComposerSendMode = "send";
  if (showStop) mode = "stop";
  else if (showQueue) mode = "queue";

  return { isStreaming, showQueue, showStop, mode };
}
