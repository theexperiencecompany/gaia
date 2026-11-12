import {
  applyStreamEvent,
  createTurnAccumulator,
  type TurnAccumulator,
} from "../chat/turnAccumulator";
import { ENTRY_KIND, type Entry, type LoggedEntry } from "./entries";
import {
  CONVERSATION_DISPLAY,
  type ConversationDisplay,
  type ConversationFrame,
  type DeltaFrame,
  FRAME_KIND,
  type StateFrame,
  WORK_PHASE,
  type WorkPhase,
} from "./frames";

/** What one attempt streamed and the log has not saved yet, for a reply or for running work. */
export interface AttemptDraft {
  attemptId: string;
  replyId: string | null;
  taskId: string | null;
  content: TurnAccumulator;
}

/** A message this device sent that the log has not given a seq yet. */
export interface PendingSend {
  id: string;
  text: string;
}

/** Everything a client knows about one conversation, folded from its event stream. */
export interface ConversationView {
  /** Ascending by seq, one entry per seq. */
  entries: readonly LoggedEntry[];
  /** In the order their first delta arrived. */
  drafts: readonly AttemptDraft[];
  /** Attempts retracted or saved: their late or replayed deltas are dropped. */
  closedAttempts: Readonly<Record<string, true>>;
  /** In send order. */
  pending: readonly PendingSend[];
  display: ConversationDisplay;
  workPhase: WorkPhase;
  head: number;
}

export type FrameOutcome =
  | { status: "applied"; view: ConversationView }
  | { status: "unknown_seq"; seq: number; view: ConversationView };

export const EMPTY_CONVERSATION_VIEW: ConversationView = {
  entries: [],
  drafts: [],
  closedAttempts: {},
  pending: [],
  display: CONVERSATION_DISPLAY.IDLE,
  workPhase: WORK_PHASE.NONE,
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

// The drafts an entry makes obsolete because the log now holds what they streamed.
function supersededBy(view: ConversationView, entry: Entry): AttemptDraft[] {
  switch (entry.kind) {
    case ENTRY_KIND.REPLY:
    case ENTRY_KIND.REPLY_SETTLED:
      return view.drafts.filter((draft) => draft.replyId === entry.reply_id);
    case ENTRY_KIND.WORK_FINISHED:
      return view.drafts.filter((draft) => draft.taskId === entry.task_id);
    default:
      return [];
  }
}

function settledAttempt(view: ConversationView, entry: Entry): string | null {
  if (entry.kind !== ENTRY_KIND.REPLY_SETTLED) return null;
  const opened = view.entries.find(
    (logged) =>
      logged.entry.kind === ENTRY_KIND.REPLY &&
      logged.entry.reply_id === entry.reply_id,
  );
  return opened?.entry.kind === ENTRY_KIND.REPLY
    ? opened.entry.attempt_id
    : null;
}

function closeAttempts(
  view: ConversationView,
  attemptIds: readonly string[],
): ConversationView {
  const open = attemptIds.filter(
    (attemptId) => !view.closedAttempts[attemptId],
  );
  if (open.length === 0) return view;
  const closing = new Set(open);
  const closedAttempts = { ...view.closedAttempts };
  for (const attemptId of open) closedAttempts[attemptId] = true;
  return {
    ...view,
    closedAttempts,
    drafts: view.drafts.filter((draft) => !closing.has(draft.attemptId)),
  };
}

function supersede(
  view: ConversationView,
  entry: Entry,
  closesOpenedReply: boolean,
) {
  const attempts = supersededBy(view, entry).map((draft) => draft.attemptId);
  const opened = settledAttempt(view, entry);
  if (opened !== null) attempts.push(opened);
  if (closesOpenedReply && entry.kind === ENTRY_KIND.REPLY)
    attempts.push(entry.attempt_id);
  return closeAttempts(view, attempts);
}

function applyEntry(
  view: ConversationView,
  logged: LoggedEntry,
): ConversationView {
  const index = findSeq(view.entries, logged.seq);
  // An append is never re-content: a replayed original must not undo a later fill.
  if (index >= 0) return view;
  const point = -(index + 1);
  const entries = [
    ...view.entries.slice(0, point),
    logged,
    ...view.entries.slice(point),
  ];
  const pending = view.pending.filter((send) => send.id !== logged.entry.id);
  const pendingChanged = pending.length !== view.pending.length;
  // An empty Reply keeps its draft on screen: superseding it here would flash an empty bubble.
  const next = {
    ...view,
    entries,
    pending: pendingChanged ? pending : view.pending,
  };
  return logged.entry.kind === ENTRY_KIND.REPLY
    ? next
    : supersede(next, logged.entry, false);
}

function applyEntryUpdated(
  view: ConversationView,
  logged: LoggedEntry,
): FrameOutcome {
  const index = findSeq(view.entries, logged.seq);
  if (index < 0) return { status: "unknown_seq", seq: logged.seq, view };
  const entries = view.entries.map((current, at) =>
    at === index ? logged : current,
  );
  return applied(supersede({ ...view, entries }, logged.entry, true));
}

function applyDelta(
  view: ConversationView,
  frame: DeltaFrame,
): ConversationView {
  if (view.closedAttempts[frame.attempt_id]) return view;
  const existing = view.drafts.find(
    (draft) => draft.attemptId === frame.attempt_id,
  );
  const draft: AttemptDraft = existing ?? {
    attemptId: frame.attempt_id,
    replyId: frame.reply_id,
    taskId: frame.task_id,
    content: createTurnAccumulator(),
  };
  const updated = {
    ...draft,
    content: applyStreamEvent(draft.content, frame.payload),
  };
  const drafts = existing
    ? view.drafts.map((current) => (current === existing ? updated : current))
    : [...view.drafts, updated];
  return { ...view, drafts };
}

function applyState(
  view: ConversationView,
  frame: StateFrame,
): ConversationView {
  if (frame.head < view.head) return view;
  if (
    frame.head === view.head &&
    frame.display === view.display &&
    frame.work_phase === view.workPhase
  ) {
    return view;
  }
  return {
    ...view,
    head: frame.head,
    display: frame.display,
    workPhase: frame.work_phase,
  };
}

/** Fold one frame into the view; replays and duplicates of entry, update, retract and state frames are no-ops. */
export function applyFrame(
  view: ConversationView,
  frame: ConversationFrame,
): FrameOutcome {
  switch (frame.kind) {
    case FRAME_KIND.ENTRY:
      return applied(applyEntry(view, frame.entry));
    case FRAME_KIND.ENTRY_UPDATED:
      return applyEntryUpdated(view, frame.entry);
    case FRAME_KIND.DELTA:
      return applied(applyDelta(view, frame));
    case FRAME_KIND.RETRACT:
      return applied(closeAttempts(view, [frame.attempt_id]));
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

/** Drop open drafts before a resumed stream re-sends their deltas from the attempt's start. */
export function beginReplay(view: ConversationView): ConversationView {
  return view.drafts.length === 0 ? view : { ...view, drafts: [] };
}
