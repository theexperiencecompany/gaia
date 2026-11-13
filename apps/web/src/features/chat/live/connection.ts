import type { ConversationPage } from "@shared/conversation";
import { createConversationFollower } from "@shared/conversation/live";
import {
  ConversationNotFoundError,
  chatApi,
} from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import {
  liveConversation,
  useLiveConversationStore,
} from "./liveConversationStore";

const PERSIST_DEBOUNCE_MS = 400;

const persistTimers = new Map<string, ReturnType<typeof setTimeout>>();

function persistNow(conversationId: string): void {
  const timer = persistTimers.get(conversationId);
  if (timer) clearTimeout(timer);
  persistTimers.delete(conversationId);
  const { view, sends, olderBefore } = liveConversation(conversationId);
  db.putConversationLog({
    conversationId,
    entries: [...view.entries],
    olderBefore,
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

async function restore(conversationId: string): Promise<void> {
  const saved = await db.getConversationLog(conversationId);
  useLiveConversationStore.getState().restore(conversationId, {
    entries: saved?.entries ?? [],
    olderBefore: saved?.olderBefore ?? null,
    sends: saved?.sends ?? {},
  });
}

/** Fold a page of the server's log into the conversation, over what this device saved of it, and save the result. */
export async function applyConversationPage(
  conversationId: string,
  page: ConversationPage,
): Promise<void> {
  await restore(conversationId);
  useLiveConversationStore.getState().applyPage(conversationId, page);
  persistConversation(conversationId, { immediately: true });
}

// The sidebar and the header read the title from the conversation list, which this update feeds.
function retitle(conversationId: string, description: string): void {
  db.updateConversationFields(conversationId, {
    description,
    title: description,
  }).catch((error: unknown) => {
    console.error("[conversation] failed to save the title:", error);
  });
}

const follower = createConversationFollower({
  subscribe: chatApi.subscribeToConversationEvents,
  isNotFound: (error) => error instanceof ConversationNotFoundError,
  view: (conversationId) => liveConversation(conversationId).view,
  apply: (conversationId, frame) => {
    const gap = useLiveConversationStore
      .getState()
      .applyFrames(conversationId, [frame]);
    persistConversation(conversationId);
    return gap;
  },
  retitle,
  prepare: async (conversationId) => {
    await restore(conversationId);
    deliverOutstandingSends(conversationId);
  },
  onInvalidFrame: (conversationId, error) => {
    streamLogError("sse", "conversation-frame-invalid", {
      conversationId,
      detail: { ...error },
    });
    console.error("[conversation] unreadable frame:", error);
  },
  onReopen: (conversationId, gap) => {
    streamLog("sse", "conversation-reopen-on-gap", {
      conversationId,
      detail: {
        status: gap.status,
        at: gap.status === "unknown_seq" ? gap.seq : gap.expected,
      },
    });
  },
  onDrop: (_conversationId, error) => {
    console.error("[conversation] events stream dropped:", error);
  },
});

/** Follow a conversation's events while anything holds it open; the returned release closes it. */
export const openConversation = follower.open;

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
  follower.wake(conversationId);
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
