import type { ConversationPage } from "@shared/conversation";
import { createConversationFollower } from "@shared/conversation/live";
import { v4 as uuidv4 } from "uuid";
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
    items: [...view.items],
    head: view.screenHead,
    olderBefore,
    sends: { ...sends },
  }).catch((error: unknown) => {
    console.error("[conversation] failed to save the screen locally:", error);
  });
}

/** Save the conversation's screen, head and sends to IndexedDB, coalescing bursts of frames. */
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
    items: saved?.items ?? [],
    head: saved?.head ?? 0,
    olderBefore: saved?.olderBefore ?? null,
    sends: saved?.sends ?? {},
  });
}

/** Take a page of the server's screen into the conversation, over what this device saved of it, and save the result. */
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
      detail: { status: gap.status, at: gap.expected },
    });
  },
  onDrop: (_conversationId, error) => {
    console.error("[conversation] events stream dropped:", error);
  },
});

/** Follow a conversation's events while anything holds it open; the returned release closes it. */
export const openConversation = follower.open;

/** Each conversation's newest delivery: the server orders messages as they arrive, so the next waits on it. */
const deliveries = new Map<string, Promise<void>>();

/** POST a queued send after the conversation's earlier sends were answered; a failure marks its bubble failed, and the retry resends the same request. */
export function deliverSend(
  conversationId: string,
  messageId: string,
): Promise<void> {
  return afterEarlierDeliveries(conversationId, () =>
    postSend(conversationId, messageId),
  );
}

/** Ask the server to answer the user message target again, in order with this device's sends; it keeps the message's one bubble. */
export function deliverRetry(
  conversationId: string,
  target: string,
): Promise<void> {
  return afterEarlierDeliveries(conversationId, async () => {
    await chatApi.retryConversationMessage(conversationId, {
      message_id: uuidv4(),
      target,
    });
    follower.wake(conversationId);
  });
}

function afterEarlierDeliveries(
  conversationId: string,
  post: () => Promise<void>,
): Promise<void> {
  // An earlier send's failure is its own caller's to handle; this one goes out regardless.
  const delivery = (deliveries.get(conversationId) ?? Promise.resolve()).then(
    post,
    post,
  );
  deliveries.set(conversationId, delivery);
  const forget = () => {
    if (deliveries.get(conversationId) === delivery)
      deliveries.delete(conversationId);
  };
  delivery.then(forget, forget);
  return delivery;
}

async function postSend(
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
