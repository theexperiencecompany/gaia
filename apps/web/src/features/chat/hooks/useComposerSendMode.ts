"use client";

import { useActiveComposerLocked } from "@/stores/streamStore";

export type ComposerSendMode = "send" | "stop" | "queue";

/**
 * Derives the composer send-button mode from the active conversation's turn.
 *
 * A turn is "open" across both the initial response and the held window after
 * it (stream still open while a background executor runs over the same SSE).
 * Any send during that window is queued by the turn manager, so the button
 * must reflect that the entire time:
 *  - turn open + typed content → `queue`
 *  - turn open + empty composer → `stop`
 *  - otherwise → `send`
 *
 * Shared by `SendStopButton` (the button itself) and `ComposerRight` (the
 * tooltip), so the two never drift apart.
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
