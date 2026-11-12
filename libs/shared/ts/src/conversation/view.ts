import {
  applyStreamEvent,
  createTurnAccumulator,
} from "../chat/turnAccumulator";
import { ENTRY_KIND } from "./entries";
import { DISPLAY_STATE, FRAME_KIND } from "./frames";
import type {
  ConversationFrame,
  ConversationView,
  Entry,
  FrameOutcome,
  LoggedEntry,
  PendingSend,
  ReplyDeltaFrame,
  StateFrame,
  StreamDraft,
  WorkDeltaFrame,
} from "./types";

export const EMPTY_CONVERSATION_VIEW: ConversationView = {
  entries: [],
  drafts: [],
  closedAttempts: {},
  closedTasks: {},
  pending: [],
  display: DISPLAY_STATE.IDLE,
  work: [],
  head: 0,
};

const applied = (view: ConversationView): FrameOutcome => ({
  status: "applied",
  view,
});

// Index of seq in entries, or the insertion point encoded as -(point + 1).
function findSeq(entries: readonly LoggedEntry[], seq: number): number {
  let low = 0;
  let high = entries.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    const found = entries[middle].seq;
    if (found === seq) return middle;
    if (found < seq) low = middle + 1;
    else high = middle - 1;
  }
  return -(low + 1);
}

const revisionOf = (entry: Entry): number | null =>
  entry.kind === ENTRY_KIND.USER_MESSAGE || entry.kind === ENTRY_KIND.REPLY
    ? entry.revision
    : null;

const withRecord = (record: Readonly<Record<string, true>>, key: string) =>
  record[key] ? record : { ...record, [key]: true as const };

// C1 and C2: a settled reply ends its attempt's draft and, when keyed by a task, that task's cards.
function settle(view: ConversationView, replyId: string): ConversationView {
  const opened = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY && entry.reply_id === replyId,
  )?.entry;
  const attempts = view.drafts.flatMap((draft) =>
    draft.source === "reply" && draft.replyId === replyId
      ? [draft.attemptId]
      : [],
  );
  if (opened?.kind === ENTRY_KIND.REPLY) attempts.push(opened.attempt_id);
  let closedAttempts = view.closedAttempts;
  for (const attemptId of attempts)
    closedAttempts = withRecord(closedAttempts, attemptId);
  const keyedByTask = view.drafts.some(
    (draft) => draft.source === "work" && draft.taskId === replyId,
  );
  const closedTasks = keyedByTask
    ? withRecord(view.closedTasks, replyId)
    : view.closedTasks;
  const drafts = view.drafts.filter((draft) =>
    draft.source === "reply"
      ? !closedAttempts[draft.attemptId]
      : !closedTasks[draft.taskId],
  );
  return { ...view, drafts, closedAttempts, closedTasks };
}

function applyEntry(
  view: ConversationView,
  logged: LoggedEntry,
): ConversationView {
  const index = findSeq(view.entries, logged.seq);
  // An append never changes content: a replayed original must not undo a later fill.
  if (index >= 0) return view;
  const point = -(index + 1);
  const entries = [
    ...view.entries.slice(0, point),
    logged,
    ...view.entries.slice(point),
  ];
  const pending = view.pending.filter((send) => send.id !== logged.entry.id);
  const next = {
    ...view,
    entries,
    pending: pending.length === view.pending.length ? view.pending : pending,
  };
  return logged.entry.kind === ENTRY_KIND.REPLY_SETTLED
    ? settle(next, logged.entry.reply_id)
    : next;
}

function applyEntryUpdated(
  view: ConversationView,
  seq: number,
  entry: Entry,
): FrameOutcome {
  const index = findSeq(view.entries, seq);
  if (index < 0) return { status: "unknown_seq", seq, view };
  const held = view.entries[index];
  const incoming = revisionOf(entry);
  const current = revisionOf(held.entry);
  if (incoming === null || current === null || incoming <= current)
    return applied(view);
  const entries = view.entries.map((logged, at) =>
    at === index ? { ...held, entry } : logged,
  );
  return applied({ ...view, entries });
}

const sameStream =
  (frame: ReplyDeltaFrame | WorkDeltaFrame) => (draft: StreamDraft) =>
    frame.kind === FRAME_KIND.REPLY_DELTA
      ? draft.source === "reply" && draft.attemptId === frame.attempt_id
      : draft.source === "work" && draft.taskId === frame.task_id;

function newDraft(frame: ReplyDeltaFrame | WorkDeltaFrame): StreamDraft {
  const fresh = { nextIndex: 0, content: createTurnAccumulator() };
  return frame.kind === FRAME_KIND.REPLY_DELTA
    ? {
        source: "reply",
        attemptId: frame.attempt_id,
        replyId: frame.reply_id,
        ...fresh,
      }
    : { source: "work", taskId: frame.task_id, ...fresh };
}

function applyDelta(
  view: ConversationView,
  frame: ReplyDeltaFrame | WorkDeltaFrame,
): FrameOutcome {
  const closed =
    frame.kind === FRAME_KIND.REPLY_DELTA
      ? view.closedAttempts[frame.attempt_id]
      : view.closedTasks[frame.task_id];
  if (closed) return applied(view);
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
  const updated: StreamDraft =
    draft.source === "reply" && frame.kind === FRAME_KIND.REPLY_DELTA
      ? { ...draft, ...advanced, replyId: frame.reply_id ?? draft.replyId }
      : { ...draft, ...advanced };
  const drafts = existing
    ? view.drafts.map((current) => (current === existing ? updated : current))
    : [...view.drafts, updated];
  return applied({ ...view, drafts });
}

function retract(view: ConversationView, attemptId: string): ConversationView {
  if (view.closedAttempts[attemptId]) return view;
  return {
    ...view,
    closedAttempts: withRecord(view.closedAttempts, attemptId),
    drafts: view.drafts.filter(
      (draft) => draft.source !== "reply" || draft.attemptId !== attemptId,
    ),
  };
}

function applyState(
  view: ConversationView,
  frame: StateFrame,
): ConversationView {
  if (frame.head < view.head) return view;
  return {
    ...view,
    head: frame.head,
    display: frame.display,
    work: frame.work,
  };
}

/** Fold one frame into the view; a duplicated or replayed frame of any kind changes nothing. */
export function applyFrame(
  view: ConversationView,
  frame: ConversationFrame,
): FrameOutcome {
  switch (frame.kind) {
    case FRAME_KIND.ENTRY:
      return applied(
        applyEntry(view, { seq: frame.seq, at: frame.at, entry: frame.entry }),
      );
    case FRAME_KIND.ENTRY_UPDATED:
      return applyEntryUpdated(view, frame.seq, frame.entry);
    case FRAME_KIND.REPLY_DELTA:
    case FRAME_KIND.WORK_DELTA:
      return applyDelta(view, frame);
    case FRAME_KIND.RETRACT:
      return applied(retract(view, frame.attempt_id));
    case FRAME_KIND.STATE:
      return applied(applyState(view, frame));
    default: {
      const unhandled: never = frame;
      return unhandled;
    }
  }
}

/** Show a send optimistically until its entry arrives; a send the log already holds is not added. */
export function addPendingSend(
  view: ConversationView,
  send: PendingSend,
): ConversationView {
  const known =
    view.pending.some((pending) => pending.id === send.id) ||
    view.entries.some((logged) => logged.entry.id === send.id);
  return known ? view : { ...view, pending: [...view.pending, send] };
}
