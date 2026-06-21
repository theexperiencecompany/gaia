"use client";

import { useChatStore } from "@/stores/chatStore";
import { useIsMainResponseStreaming } from "@/stores/loadingStore";

export type ComposerSendMode = "send" | "stop" | "queue";

/**
 * Derives the composer send-button mode from the live stream state.
 *
 * A stream is "open" for the active conversation across BOTH phases of a turn —
 * the initial response (`isResponding`) and the held window after it (stream
 * still open while a background executor runs). Any send during that whole
 * window is held in the queue by `streamFunction`, so the button must reflect
 * that the entire time:
 *  - streaming + typed content → `queue`
 *  - streaming + empty composer → `stop`
 *  - otherwise → `send`
 *
 * Shared by `SendStopButton` (the button itself) and `ComposerRight` (the
 * tooltip), so the two never drift apart.
 */
export function useComposerSendMode(hasContent: boolean) {
  const isResponding = useIsMainResponseStreaming();
  const streamingConversationId = useChatStore(
    (state) => state.streamingConversationId,
  );
  const activeConversationId = useChatStore(
    (state) => state.activeConversationId,
  );

  const isStreaming =
    isResponding ||
    (streamingConversationId != null &&
      streamingConversationId === activeConversationId);
  const showQueue = isStreaming && hasContent;
  const showStop = isStreaming && !hasContent;
  let mode: ComposerSendMode = "send";
  if (showStop) mode = "stop";
  else if (showQueue) mode = "queue";

  return { isStreaming, showQueue, showStop, mode };
}
