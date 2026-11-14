import type { ConversationMessageHit } from "../api/generated";
import {
  extractToolProgressMessage,
  type StreamToolDataEntry,
} from "../chat/streaming";
import { LIVE_WORK_STATUS, SCREEN_ITEM_KIND } from "./entries";
import { DISPLAY_STATE } from "./frames";
import type {
  ConversationView,
  DisplayState,
  PendingSend,
  ScreenItem,
  StreamDraft,
  UserMessage,
} from "./types";

/**
 * One row of the chat screen: a server item with what is still streaming into it, a
 * reply whose item the server has not inserted yet, or this device's own pending send.
 */
export type ScreenRow =
  | { kind: "item"; item: ScreenItem; draft: StreamDraft | null }
  | { kind: "draft"; draft: StreamDraft }
  | { kind: "pending"; send: PendingSend };

export interface LoadingRow {
  visible: boolean;
  status: DisplayState;
  /** The newest draft's tool progress line, shown under the status. */
  detail: string | null;
}

function streamKey(item: ScreenItem): string | null {
  if (item.kind === SCREEN_ITEM_KIND.REPLY) return `reply:${item.id}`;
  return null;
}

const draftKey = (draft: StreamDraft): string | null =>
  draft.replyId && `reply:${draft.replyId}`;

/** The rows to render, in the server's order: its items, then replies streaming ahead of their item, then pending sends. */
export function screenRows(view: ConversationView): ScreenRow[] {
  const drafts = new Map<string, StreamDraft>();
  for (const draft of view.drafts) {
    const key = draftKey(draft);
    if (key) drafts.set(key, draft);
  }
  const placed = new Set<StreamDraft>();
  const rows: ScreenRow[] = view.items.map((item) => {
    const key = streamKey(item);
    const draft = (key && drafts.get(key)) || null;
    if (draft) placed.add(draft);
    return { kind: "item", item, draft };
  });
  for (const draft of view.drafts) {
    if (!placed.has(draft)) rows.push({ kind: "draft", draft });
  }
  for (const send of view.pending) rows.push({ kind: "pending", send });
  return rows;
}

/** The cards streaming now: the newest reply draft's, else the newest running work's. */
function newestCards(view: ConversationView): readonly StreamToolDataEntry[] {
  const draft = view.drafts.at(-1);
  if (draft) return draft.content.toolData;
  const work = view.items.findLast(
    (item) =>
      item.kind === SCREEN_ITEM_KIND.WORK && LIVE_WORK_STATUS.has(item.status),
  );
  return work?.kind === SCREEN_ITEM_KIND.WORK
    ? (work.tool_data as StreamToolDataEntry[])
    : [];
}

/** The loading row: the server's display state, with the newest streaming cards' progress line. */
export function loadingRow(view: ConversationView): LoadingRow {
  const visible = view.display !== DISPLAY_STATE.IDLE;
  const progress = visible
    ? newestCards(view)
        .map(extractToolProgressMessage)
        .findLast((message) => message !== null)
    : undefined;
  return { visible, status: view.display, detail: progress ?? null };
}

/**
 * Whether GAIA owes this device a reply the server has not announced yet: a send not
 * shown (and not failed), or a shown one whose following state frame is still due.
 */
function awaitingServerState(
  view: ConversationView,
  sends: Readonly<Record<string, { failed: boolean }>>,
): boolean {
  if (view.pending.some((pending) => !sends[pending.id]?.failed)) return true;
  return view.items.some((item) => item.seq > view.head && sends[item.id]);
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

/** The user message a retry resends: the message itself, or the newest one before the reply. */
export function messageToRetry(
  view: ConversationView,
  itemId: string,
): UserMessage | null {
  const at = view.items.findIndex((item) => item.id === itemId);
  if (at === -1) return null;
  const asked = view.items
    .slice(0, at + 1)
    .findLast((item) => item.kind === SCREEN_ITEM_KIND.USER);
  return asked?.kind === SCREEN_ITEM_KIND.USER ? asked.message : null;
}

/** The words a pinned or searched item shows: the user's message, or a reply's or notice's text. */
export function itemText(item: ConversationMessageHit["item"]): string {
  return item.kind === SCREEN_ITEM_KIND.USER ? item.message.text : item.text;
}
