import type {
  ImageData,
  SelectedWorkflowDataOutput,
  TodoRunWake,
  ToolDataEntry,
  WorkOutcome,
} from "../api/generated";
import { extractToolProgressMessage } from "../chat/streaming";
import type { TurnAccumulator } from "../chat/turnAccumulator";
import { ENTRY_KIND } from "./entries";
import { DISPLAY_STATE } from "./frames";
import type {
  ConversationView,
  DisplayState,
  LoggedEntry,
  PendingSend,
  Reaction,
  Reply,
  StreamDraft,
  UserMessage,
} from "./types";

export type WorkStatus = "running" | "awaiting_approval" | WorkOutcome;

/**
 * One row of the chat screen, in the order visibleBubbles returns them. messageId is
 * the id the server's history gives the same row, so a saved copy is recognised.
 */
export type LiveBubble =
  | {
      kind: "user";
      key: string;
      messageId: string;
      seq: number;
      message: UserMessage;
      reaction: Reaction | null;
    }
  | {
      kind: "reply";
      key: string;
      messageId: string;
      /** Null while the attempt streams before its Reply entry is appended. */
      seq: number | null;
      replyId: string | null;
      text: string;
      toolData: readonly ToolDataEntry[];
      followUpActions: readonly string[];
      image: ImageData | null;
      pinned: boolean;
      streaming: boolean;
    }
  | {
      kind: "notice";
      key: string;
      messageId: string;
      seq: number;
      text: string;
      toolData: readonly ToolDataEntry[];
    }
  /** The workflow card that started a run; the run's reply is its own row. */
  | {
      kind: "workflow_fired";
      key: string;
      messageId: string;
      seq: number;
      workflow: SelectedWorkflowDataOutput;
    }
  /** What woke a tracked todo's run; its write-up reply is its own row. */
  | {
      kind: "todo_woke";
      key: string;
      messageId: string;
      seq: number;
      wake: TodoRunWake;
    }
  | {
      kind: "work";
      key: string;
      messageId: string;
      /** Null when the task's WorkStarted entry is not in the view. */
      seq: number | null;
      taskId: string;
      status: WorkStatus;
      toolData: readonly ToolDataEntry[];
    }
  | { kind: "pending"; key: string; messageId: string; send: PendingSend };

export interface LoadingRow {
  visible: boolean;
  status: DisplayState;
  /** The newest draft's tool progress line, shown under the status. */
  detail: string | null;
}

type ReplyDraft = Extract<StreamDraft, { source: "reply" }>;
type WorkDraft = Extract<StreamDraft, { source: "work" }>;

const isReplyDraft = (draft: StreamDraft): draft is ReplyDraft =>
  draft.source === "reply";
const isWorkDraft = (draft: StreamDraft): draft is WorkDraft =>
  draft.source === "work";

const draftContent = (content: TurnAccumulator) => ({
  text: content.responseText,
  toolData: content.toolData,
  followUpActions: content.followUpActions ?? [],
});

function replyBubble(
  view: ConversationView,
  seq: number,
  entry: Reply,
): LiveBubble {
  const draft = view.drafts
    .filter(isReplyDraft)
    .find((d) => d.attemptId === entry.attempt_id);
  const content = draft
    ? draftContent(draft.content)
    : {
        text: entry.text,
        toolData: entry.tool_data,
        followUpActions: entry.follow_up_actions,
      };
  return {
    kind: "reply",
    key: `reply:${entry.reply_id}`,
    messageId: entry.reply_id,
    seq,
    replyId: entry.reply_id,
    ...content,
    image: entry.image,
    pinned: entry.pinned,
    streaming: draft !== undefined,
  };
}

function entryBubble(
  view: ConversationView,
  { seq, entry }: LoggedEntry,
): LiveBubble | null {
  switch (entry.kind) {
    case ENTRY_KIND.USER_MESSAGE:
      return {
        kind: "user",
        key: `user:${entry.id}`,
        messageId: entry.id,
        seq,
        message: entry,
        reaction: entry.reaction,
      };
    case ENTRY_KIND.REPLY:
      return replyBubble(view, seq, entry);
    case ENTRY_KIND.NOTICE:
      return {
        kind: "notice",
        key: `notice:${entry.id}`,
        messageId: entry.id,
        seq,
        text: entry.text,
        toolData: entry.tool_data,
      };
    case ENTRY_KIND.WORKFLOW_FIRED:
      return {
        kind: "workflow_fired",
        key: `workflow:${entry.id}`,
        messageId: entry.id,
        seq,
        workflow: entry.run.workflow,
      };
    case ENTRY_KIND.TODO_WOKE:
      return {
        kind: "todo_woke",
        key: `todo:${entry.id}`,
        messageId: entry.id,
        seq,
        wake: entry.run.wake,
      };
    // An integration's need and connect add no row: the work's connect card shows both.
    default:
      return null;
  }
}

function workStatus(view: ConversationView, taskId: string): WorkStatus {
  const finished = view.entries.find(
    ({ entry }) =>
      entry.kind === ENTRY_KIND.WORK_FINISHED && entry.task_id === taskId,
  )?.entry;
  if (finished?.kind === ENTRY_KIND.WORK_FINISHED) return finished.outcome;
  const live = view.work.find((task) => task.task_id === taskId);
  return live?.awaiting_approval ? "awaiting_approval" : "running";
}

// A task handed to running work belongs to that work's bubble, through any chain of hand-overs.
function joinedRoots(view: ConversationView): (taskId: string) => string {
  const joins = new Map<string, string>();
  for (const { entry } of view.entries) {
    if (entry.kind === ENTRY_KIND.WORK_STARTED && entry.joins)
      joins.set(entry.task_id, entry.joins);
  }
  return (taskId) => {
    let root = taskId;
    const visited = new Set<string>();
    while (joins.has(root) && !visited.has(root)) {
      visited.add(root);
      root = joins.get(root) ?? root;
    }
    return root;
  };
}

// Finished tasks whose narrating reply has not settled: their logged cards stand in for live ones.
function unsettledFinishedCards(
  view: ConversationView,
): Map<string, readonly ToolDataEntry[]> {
  const settled = new Set(
    view.entries.flatMap(({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY_SETTLED ? [entry.reply_id] : [],
    ),
  );
  const cards = new Map<string, readonly ToolDataEntry[]>();
  for (const { entry } of view.entries) {
    if (
      entry.kind === ENTRY_KIND.WORK_FINISHED &&
      !settled.has(entry.task_id) &&
      !view.closedTasks[entry.task_id]
    )
      cards.set(entry.task_id, entry.tool_data);
  }
  return cards;
}

// C2: one bubble per live task and per task whose cards no settled reply has taken over yet.
function workBubbles(view: ConversationView): LiveBubble[] {
  const rootOf = joinedRoots(view);
  const drafts = view.drafts.filter(isWorkDraft);
  const finishedCards = unsettledFinishedCards(view);
  const liveCards = new Map<string, ToolDataEntry[]>();
  for (const draft of drafts) {
    const root = rootOf(draft.taskId);
    liveCards.set(root, [
      ...(liveCards.get(root) ?? []),
      ...draft.content.toolData,
    ]);
  }
  const taskIds = [
    ...new Set(
      [
        ...view.work.map((task) => task.task_id),
        ...drafts.map((draft) => draft.taskId),
        ...finishedCards.keys(),
      ].map(rootOf),
    ),
  ];
  return taskIds.map((taskId) => ({
    kind: "work",
    key: `work:${taskId}`,
    messageId: `work:${taskId}`,
    seq:
      view.entries.find(
        ({ entry }) =>
          entry.kind === ENTRY_KIND.WORK_STARTED && entry.task_id === taskId,
      )?.seq ?? null,
    taskId,
    status: workStatus(view, taskId),
    toolData: liveCards.get(taskId) ?? finishedCards.get(taskId) ?? [],
  }));
}

const seqOf = (bubble: LiveBubble): number | null =>
  bubble.kind === "pending" ? null : bubble.seq;

/** The rows the chat screen renders: by seq, then drafts with no entry yet, then pending sends. */
export function visibleBubbles(view: ConversationView): LiveBubble[] {
  const opened = new Set(
    view.entries.flatMap(({ entry }) =>
      entry.kind === ENTRY_KIND.REPLY ? [entry.attempt_id] : [],
    ),
  );
  const unopened = view.drafts.flatMap((draft): LiveBubble[] =>
    isReplyDraft(draft) && !opened.has(draft.attemptId)
      ? [
          {
            kind: "reply",
            key: `draft:${draft.attemptId}`,
            messageId: draft.replyId ?? `draft:${draft.attemptId}`,
            seq: null,
            replyId: draft.replyId,
            ...draftContent(draft.content),
            image: null,
            pinned: false,
            streaming: true,
          },
        ]
      : [],
  );
  const placed = [
    ...view.entries.flatMap((logged) => entryBubble(view, logged) ?? []),
    ...workBubbles(view),
  ];
  const bySeq = placed.filter((bubble) => seqOf(bubble) !== null);
  bySeq.sort((a, b) => (seqOf(a) ?? 0) - (seqOf(b) ?? 0));
  const pending = view.pending.map(
    (send): LiveBubble => ({
      kind: "pending",
      key: `pending:${send.id}`,
      messageId: send.id,
      send,
    }),
  );
  return [
    ...bySeq,
    ...placed.filter((bubble) => seqOf(bubble) === null),
    ...unopened,
    ...pending,
  ];
}

/** The loading row, from the server's display state and the newest draft's progress only. */
export function loadingRow(view: ConversationView): LoadingRow {
  const visible = view.display !== DISPLAY_STATE.IDLE;
  const progress = visible
    ? view.drafts
        .at(-1)
        ?.content.toolData.map(extractToolProgressMessage)
        .findLast((message) => message !== null)
    : undefined;
  return { visible, status: view.display, detail: progress ?? null };
}

/** The user message a reply visibly points at: the server's choice at open, and its final one once settled. */
export function quoteFor(
  view: ConversationView,
  replyId: string,
): string | null {
  let opened: string | null = null;
  for (const { entry } of view.entries) {
    if (entry.kind === ENTRY_KIND.REPLY_SETTLED && entry.reply_id === replyId)
      return entry.quote_target;
    if (entry.kind === ENTRY_KIND.REPLY && entry.reply_id === replyId)
      opened = entry.quote_target;
  }
  return opened;
}

/**
 * Whether GAIA owes this device a reply the server has not announced yet: a send not
 * accepted (and not failed), or an accepted one whose following state frame is still due.
 */
export function awaitingServerState(
  view: ConversationView,
  sends: Readonly<Record<string, { failed: boolean }>>,
): boolean {
  if (view.pending.some((pending) => !sends[pending.id]?.failed)) return true;
  for (let at = view.entries.length - 1; at >= 0; at -= 1) {
    const { seq, entry } = view.entries[at];
    if (seq <= view.head) return false;
    if (sends[entry.id]) return true;
  }
  return false;
}

/** The user message a retry resends: the message itself, or the newest one before the reply. */
export function messageToRetry(
  view: ConversationView,
  messageId: string,
): UserMessage | null {
  const { entries } = view;
  const at = entries.findIndex(
    ({ entry }) =>
      entry.id === messageId ||
      (entry.kind === ENTRY_KIND.REPLY && entry.reply_id === messageId),
  );
  if (at === -1) return null;
  const asked = entries
    .slice(0, at + 1)
    .findLast(({ entry }) => entry.kind === ENTRY_KIND.USER_MESSAGE)?.entry;
  return asked?.kind === ENTRY_KIND.USER_MESSAGE ? asked : null;
}

/** The loading row a sending client shows: the server's, raised to thinking while this device's send is owed a state. */
export function sendingLoadingRow(
  view: ConversationView,
  sends: Readonly<Record<string, { failed: boolean }>>,
): LoadingRow {
  const row = loadingRow(view);
  if (row.visible || !awaitingServerState(view, sends)) return row;
  return { visible: true, status: DISPLAY_STATE.THINKING, detail: null };
}
