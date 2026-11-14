import type { ConversationFrame, ReplyDraft } from "./types";

type ReplyDelta = Extract<
  ConversationFrame,
  { kind: "reply_delta" }
>["payload"];

export const EMPTY_REPLY_DRAFT: ReplyDraft = {
  bubbles: [],
  toolData: [],
  timeline: { steps: [], cards: [] },
  followUpActions: [],
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
      return { ...draft, toolData: delta.tool_data, timeline: delta.timeline };
    case "follow_up_actions":
      return { ...draft, followUpActions: delta.follow_up_actions };
    default: {
      const unhandled: never = delta;
      return unhandled;
    }
  }
}
