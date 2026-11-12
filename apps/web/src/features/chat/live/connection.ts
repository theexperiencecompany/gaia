import { parseConversationEvent } from "@shared/conversation";
import {
  ConversationNotFoundError,
  chatApi,
} from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import {
  type FrameGap,
  liveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";
import { resumeAfter } from "./resume";

const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 15_000;
const PERSIST_DEBOUNCE_MS = 400;

interface Connection {
  refs: number;
  closed: boolean;
  controller: AbortController | null;
  /** Resolves the current wait early: a send just created the conversation, or the caller closed. */
  wake: (() => void) | null;
}

const connections = new Map<string, Connection>();
const persistTimers = new Map<string, ReturnType<typeof setTimeout>>();

function persistNow(conversationId: string): void {
  const timer = persistTimers.get(conversationId);
  if (timer) clearTimeout(timer);
  persistTimers.delete(conversationId);
  const { view, sends } = liveConversation(conversationId);
  db.putConversationLog({
    conversationId,
    entries: [...view.entries],
    sends: { ...sends },
  }).catch((error: unknown) => {
    console.error("[conversation] failed to save the log locally:", error);
  });
}

/** Save the conversation's log and sends to IndexedDB, coalescing bursts of frames. */
export function persistConversation(
  conversationId: string,
  { immediately = false } = {},
): void {
  if (immediately) {
    persistNow(conversationId);
    return;
  }
  if (persistTimers.has(conversationId)) return;
  persistTimers.set(
    conversationId,
    setTimeout(() => persistNow(conversationId), PERSIST_DEBOUNCE_MS),
  );
}

const backoff = (attempt: number): number =>
  Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);

function wait(connection: Connection, ms: number | null): Promise<void> {
  return new Promise((resolve) => {
    const timer = ms === null ? null : setTimeout(done, ms);
    function done() {
      if (timer) clearTimeout(timer);
      connection.wake = null;
      resolve();
    }
    connection.wake = done;
  });
}

// An entry update for a seq this client never held must replay from before that seq.
const reopenAfter = (conversationId: string, gap: FrameGap | null): number => {
  const after = resumeAfter(liveConversation(conversationId).view);
  return gap?.status === "unknown_seq" ? Math.min(after, gap.seq - 1) : after;
};

async function hydrate(conversationId: string): Promise<void> {
  const saved = await db.getConversationLog(conversationId);
  useLiveConversationStore
    .getState()
    .hydrate(conversationId, saved?.entries ?? [], saved?.sends ?? {});
}

/** Read one stream until it ends; returns the gap that ended it early, if one did. */
async function readStream(
  conversationId: string,
  connection: Connection,
  after: number,
): Promise<{ gap: FrameGap | null; delivered: boolean }> {
  const controller = new AbortController();
  connection.controller = controller;
  let gap: FrameGap | null = null;
  let delivered = false;
  await chatApi.subscribeToConversationEvents(
    conversationId,
    after,
    (raw) => {
      if (gap) return;
      const parsed = parseConversationEvent(raw);
      if (!parsed.ok) {
        streamLogError("sse", "conversation-frame-invalid", {
          conversationId,
          detail: { ...parsed.error },
        });
        console.error("[conversation] unreadable frame:", parsed.error);
        return;
      }
      delivered = true;
      gap = useLiveConversationStore
        .getState()
        .applyFrames(conversationId, [parsed.event.frame]);
      persistConversation(conversationId);
      if (gap) controller.abort();
    },
    controller.signal,
  );
  return { gap, delivered };
}

async function follow(
  conversationId: string,
  connection: Connection,
): Promise<void> {
  await hydrate(conversationId);
  deliverOutstandingSends(conversationId);
  let attempt = 0;
  let gap: FrameGap | null = null;
  while (!connection.closed) {
    const after = reopenAfter(conversationId, gap);
    gap = null;
    try {
      const ended = await readStream(conversationId, connection, after);
      gap = ended.gap;
      if (ended.delivered) attempt = 0;
    } catch (error) {
      if (connection.closed) return;
      if (error instanceof ConversationNotFoundError) {
        // Nothing to follow until this device's first send creates it.
        await wait(connection, null);
        continue;
      }
      console.error("[conversation] events stream dropped:", error);
    }
    if (connection.closed) return;
    if (gap) {
      streamLog("sse", "conversation-reopen-on-gap", {
        conversationId,
        detail: {
          status: gap.status,
          at: gap.status === "unknown_seq" ? gap.seq : gap.expected,
        },
      });
      continue;
    }
    await wait(connection, backoff(attempt));
    attempt += 1;
  }
}

/** POST a queued send; a failure marks its bubble failed, and the retry resends the same request. */
export async function deliverSend(
  conversationId: string,
  messageId: string,
): Promise<void> {
  const send = liveConversation(conversationId).sends[messageId];
  if (!send)
    throw new Error(`No queued send ${messageId} in ${conversationId}`);
  const store = useLiveConversationStore.getState();
  store.setSendFailed(conversationId, messageId, false);
  try {
    await chatApi.sendConversationMessage(conversationId, send.body);
  } catch (error) {
    store.setSendFailed(conversationId, messageId, true);
    persistConversation(conversationId, { immediately: true });
    throw error;
  }
  wakeConversation(conversationId);
}

/** Resend what this device queued and never saw accepted, as a reload finds it; failed sends wait for their retry. */
function deliverOutstandingSends(conversationId: string): void {
  const { view, sends } = liveConversation(conversationId);
  for (const pending of view.pending) {
    if (sends[pending.id]?.failed !== false) continue;
    deliverSend(conversationId, pending.id).catch((error: unknown) => {
      console.error("[sendMessage] resend failed:", error);
    });
  }
}

/** Follow a conversation's events while anything holds it open; the returned release closes it. */
export function openConversation(conversationId: string): () => void {
  let connection = connections.get(conversationId);
  if (!connection) {
    const opened: Connection = {
      refs: 0,
      closed: false,
      controller: null,
      wake: null,
    };
    connections.set(conversationId, opened);
    connection = opened;
    follow(conversationId, opened).catch((error: unknown) => {
      console.error("[conversation] follower stopped:", error);
    });
  }
  connection.refs += 1;
  const held = connection;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    held.refs -= 1;
    if (held.refs > 0) return;
    held.closed = true;
    held.controller?.abort();
    held.wake?.();
    connections.delete(conversationId);
  };
}

/** Reconnect now instead of after the backoff: a send has just landed in this conversation. */
export function wakeConversation(conversationId: string): void {
  connections.get(conversationId)?.wake?.();
}
