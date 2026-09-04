"use client";

import { useChatStore } from "@/stores/chatStore";
import { useActiveComposerLocked } from "@/stores/streamStore";

export type ComposerSendMode = "send" | "stop" | "queue";

/**
 * Derives the composer send-button mode from the active conversation's turn.
 *
 * A turn is "open" across both the initial response and the held window after
 * it (stream still open while a background executor runs over the same SSE).
 * A send during that window steers the live run immediately, so the button
 * stays on `send`:
 *  - turn open + typed content → `send` (steers)
 *  - turn open + empty composer → `stop`
 *  - otherwise → `send`
 *
 * The `queue` mode survives only for not-yet-created conversations, where the
 * backend has no id to fold into and the turn manager still holds the send.
 *
 * Shared by `SendStopButton` (the button itself) and `ComposerRight` (the
 * tooltip), so the two never drift apart.
 */
export function useComposerSendMode(hasContent: boolean) {
  const isStreaming = useActiveComposerLocked();
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );

  const canSteer =
    activeConversationId != null && activeConversationId !== "new";
  const showQueue = isStreaming && hasContent && !canSteer;
  const showStop = isStreaming && !hasContent;
  let mode: ComposerSendMode = "send";
  if (showStop) mode = "stop";
  else if (showQueue) mode = "queue";

  return { isStreaming, showQueue, showStop, mode };
}
