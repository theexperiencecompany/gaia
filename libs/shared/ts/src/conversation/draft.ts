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

/** Fold one reply delta into what the reply shows; the server already split and folded it. */
export function applyReplyDelta(
  draft: ReplyDraft,
  delta: ReplyDelta,
): ReplyDraft {
  switch (delta.type) {
    case "bubble_text": {
      const bubbles = [...draft.bubbles];
      bubbles[delta.bubble] = (bubbles[delta.bubble] ?? "") + delta.text;
      return { ...draft, bubbles };
    }
    case "bubbles":
      return { ...draft, bubbles: delta.bubbles };
    case "cards":
      return { ...draft, tool_data: delta.tool_data, timeline: delta.timeline };
    case "follow_up_actions":
      return { ...draft, follow_up_actions: delta.follow_up_actions };
    default: {
      const unhandled: never = delta;
      return unhandled;
    }
  }
}
