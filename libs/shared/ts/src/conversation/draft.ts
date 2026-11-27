import { applyChanges } from "./patch";
import type { ConversationFrame, ReplyDraft } from "./types";

type ReplyDelta = Extract<
  ConversationFrame,
  { kind: "reply_delta" }
>["payload"];

export const EMPTY_REPLY_DRAFT: ReplyDraft = {
  bubbles: [],
  tool_data: [],
  timeline: { steps: [], cards: [], progress: null },
  follow_up_actions: [],
};

/** Fold one reply delta into what the reply shows; null when its changes have no place in the draft's timeline. */
export function applyReplyDelta(
  draft: ReplyDraft,
  delta: ReplyDelta,
): ReplyDraft | null {
  switch (delta.type) {
    case "bubble_text": {
      const bubbles = [...draft.bubbles];
      bubbles[delta.bubble] = (bubbles[delta.bubble] ?? "") + delta.text;
      return { ...draft, bubbles };
    }
    case "cards":
      return { ...draft, tool_data: delta.tool_data, timeline: delta.timeline };
    case "timeline": {
      const timeline = applyChanges(draft.timeline, delta.changes);
      return timeline && { ...draft, timeline };
    }
    case "follow_up_actions":
      return { ...draft, follow_up_actions: delta.follow_up_actions };
    default: {
      const unhandled: never = delta;
      return unhandled;
    }
  }
}
