import {
  applyStreamEvent,
  createTurnAccumulator,
} from "../chat/turnAccumulator";
import { LIVE_WORK_STATUS, SCREEN_ITEM_KIND } from "./entries";
import { DISPLAY_STATE, FRAME_KIND } from "./frames";
import type {
  ConversationFrame,
  ConversationView,
  FrameOutcome,
  PendingSend,
  ScreenItem,
  StreamDraft,
} from "./types";

// The parsed frame, whose payload is the stream event the accumulator folds.
type DeltaFrame = Extract<ConversationFrame, { kind: "reply_delta" }>;

export const EMPTY_CONVERSATION_VIEW: ConversationView = {
  items: [],
  drafts: [],
  closed: {},
  pending: [],
  display: DISPLAY_STATE.IDLE,
  work: [],
  head: 0,
};

const applied = (view: ConversationView): FrameOutcome => ({
  status: "applied",
  view,
});

const isDev = () => process.env.NODE_ENV !== "production";

/** The id whose stream an item's arrival ends: a settled reply's, or finished work's task. */
function endedStream(item: ScreenItem): string | null {
  if (item.kind === SCREEN_ITEM_KIND.REPLY)
    return item.outcome === null ? null : item.id;
  if (item.kind === SCREEN_ITEM_KIND.WORK)
    return LIVE_WORK_STATUS.has(item.status) ? null : item.task_id;
  return null;
}

/** Take the server's items: each replaces the one it updates, and every item sits at its seq. */
function withItems(
  view: ConversationView,
  incoming: readonly ScreenItem[],
): ConversationView {
  const byId = new Map(view.items.map((item) => [item.id, item]));
  for (const item of incoming) {
    const held = byId.get(item.id);
    // The server never moves an item; this firing means the projection broke that rule.
    if (held && held.seq !== item.seq && isDev())
      console.warn("[conversation] item moved", item.id, held.seq, item.seq);
    byId.set(item.id, item);
  }
  const items = [...byId.values()].sort((a, b) => a.seq - b.seq);
  const ended = incoming.flatMap((item) => endedStream(item) ?? []);
  const closed = { ...view.closed };
  for (const id of ended) closed[id] = true;
  const shown = new Set(items.map((item) => item.id));
  return {
    ...view,
    items,
    closed,
    drafts: view.drafts.filter(
      (draft) => !(draft.replyId && closed[draft.replyId]),
    ),
    pending: view.pending.filter((send) => !shown.has(send.id)),
  };
}

/** An update for an item older than everything held belongs to history not loaded here. */
function update(view: ConversationView, item: ScreenItem): ConversationView {
  const oldest = view.items[0];
  return oldest && item.seq < oldest.seq ? view : withItems(view, [item]);
}

const sameStream = (frame: DeltaFrame) => (draft: StreamDraft) =>
  draft.attemptId === frame.attempt_id;

function newDraft(frame: DeltaFrame): StreamDraft {
  return {
    attemptId: frame.attempt_id,
    replyId: frame.reply_id,
    nextIndex: 0,
    content: createTurnAccumulator(),
  };
}

function isClosed(view: ConversationView, frame: DeltaFrame): boolean {
  return Boolean(
    view.closed[frame.attempt_id] ||
      (frame.reply_id && view.closed[frame.reply_id]),
  );
}

function applyDelta(view: ConversationView, frame: DeltaFrame): FrameOutcome {
  if (isClosed(view, frame)) return applied(view);
  const existing = view.drafts.find(sameStream(frame));
  const draft = existing ?? newDraft(frame);
  if (frame.index < draft.nextIndex) return applied(view);
  if (frame.index > draft.nextIndex) {
    return { status: "index_gap", expected: draft.nextIndex, view };
  }
  const advanced = {
    nextIndex: draft.nextIndex + 1,
    content: applyStreamEvent(draft.content, frame.payload),
  };
  const updated: StreamDraft = {
    ...draft,
    ...advanced,
    replyId: frame.reply_id ?? draft.replyId,
  };
  const drafts = existing
    ? view.drafts.map((current) => (current === existing ? updated : current))
    : [...view.drafts, updated];
  return applied({ ...view, drafts });
}

function retract(view: ConversationView, attemptId: string): ConversationView {
  if (view.closed[attemptId]) return view;
  return {
    ...view,
    closed: { ...view.closed, [attemptId]: true },
    drafts: view.drafts.filter((draft) => draft.attemptId !== attemptId),
  };
}

/** Fold one frame into the view; a repeated frame of any kind changes nothing. */
export function applyFrame(
  view: ConversationView,
  frame: ConversationFrame,
): FrameOutcome {
  switch (frame.kind) {
    case FRAME_KIND.SCREEN:
      return applied(withItems(view, frame.items));
    case FRAME_KIND.SCREEN_INSERT:
      return applied(withItems(view, [frame.item]));
    case FRAME_KIND.SCREEN_UPDATE:
      return applied(update(view, frame.item));
    case FRAME_KIND.REPLY_DELTA:
      return applyDelta(view, frame);
    case FRAME_KIND.RETRACT:
      return applied(retract(view, frame.attempt_id));
    case FRAME_KIND.STATE:
      return applied(
        frame.head < view.head
          ? view
          : {
              ...view,
              head: frame.head,
              display: frame.display,
              work: frame.work,
            },
      );
    // The title is the conversation's metadata, held with the conversation list, not in the screen.
    case FRAME_KIND.CONVERSATION_UPDATED:
      return applied(view);
    default: {
      const unhandled: never = frame;
      return unhandled;
    }
  }
}

/** Take a page of the server's screen (a load, a sync or a page back) and its state. */
export function applyPage(
  view: ConversationView,
  items: readonly ScreenItem[],
  state: Extract<ConversationFrame, { kind: "state" }>,
): ConversationView {
  const outcome = applyFrame(withItems(view, items), state);
  return outcome.view;
}

/** Show this device's own send until the server's screen inserts it; a send already shown is not added. */
export function addPendingSend(
  view: ConversationView,
  send: PendingSend,
): ConversationView {
  const known =
    view.pending.some((pending) => pending.id === send.id) ||
    view.items.some((item) => item.id === send.id);
  return known ? view : { ...view, pending: [...view.pending, send] };
}
