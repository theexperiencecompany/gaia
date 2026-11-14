import { ApiError, parseSubscriptionRequiredBody } from "@gaia/shared";
import type { ConversationPage } from "@gaia/shared/conversation";
import { createConversationFollower } from "@gaia/shared/conversation/live";
import { chatDb } from "@/lib/db/chatDb";
import { queryClient } from "@/lib/query-provider";
import { EventStreamHttpError } from "@/lib/sse-client";
import { usePaywallStore } from "@/stores/paywall-store";
import { chatApi } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import type { Conversation } from "../types";
import {
  liveConversation,
  useLiveConversationStore,
} from "./live-conversation-store";

const HTTP_NOT_FOUND = 404;
const HTTP_PAYMENT_REQUIRED = 402;
const PERSIST_DEBOUNCE_MS = 400;

const persistTimers = new Map<string, ReturnType<typeof setTimeout>>();

function persistNow(conversationId: string): void {
  clearTimeout(persistTimers.get(conversationId));
  persistTimers.delete(conversationId);
  const { view, olderBefore } = liveConversation(conversationId);
  chatDb.saveLog(conversationId, {
    items: [...view.items],
    head: view.head,
    olderBefore,
  });
}

/** Save the conversation's screen to AsyncStorage, coalescing bursts of frames. */
function persistConversation(conversationId: string): void {
  if (persistTimers.has(conversationId)) return;
  persistTimers.set(
    conversationId,
    setTimeout(() => persistNow(conversationId), PERSIST_DEBOUNCE_MS),
  );
}

async function restore(conversationId: string): Promise<void> {
  const saved = await chatDb.getLog(conversationId);
  useLiveConversationStore.getState().restore(conversationId, {
    items: saved?.items ?? [],
    head: saved?.head ?? 0,
    olderBefore: saved?.olderBefore ?? null,
    sends: {},
  });
}

/** Fold a page of the server's log into the conversation, over what this device saved of it, and save the result. */
export async function applyConversationPage(
  conversationId: string,
  page: ConversationPage,
): Promise<void> {
  await restore(conversationId);
  useLiveConversationStore.getState().applyPage(conversationId, page);
  persistNow(conversationId);
}

/** Write a conversation's title into the sidebar's list, the one place mobile reads it from. */
function retitleConversation(conversationId: string, title: string) {
  queryClient.setQueryData(
    chatKeys.conversations(),
    (previous: Conversation[] | undefined) =>
      previous?.map((conversation) =>
        conversation.id === conversationId
          ? { ...conversation, title }
          : conversation,
      ),
  );
}

const follower = createConversationFollower({
  subscribe: chatApi.subscribeToConversationEvents,
  isNotFound: (error) =>
    error instanceof EventStreamHttpError && error.status === HTTP_NOT_FOUND,
  apply: (conversationId, frame) => {
    const gap = useLiveConversationStore
      .getState()
      .applyFrames(conversationId, [frame]);
    persistConversation(conversationId);
    return gap;
  },
  retitle: retitleConversation,
  // The saved screen shows at once, until the stream's first frame replaces it.
  prepare: restore,
  onInvalidFrame: (conversationId, error) => {
    console.error("[conversation] unreadable frame:", conversationId, error);
  },
  onReopen: (conversationId, gap) => {
    console.warn("[conversation] reopening from the log:", conversationId, gap);
  },
  onDrop: (conversationId, error) => {
    console.warn(
      "[conversation] events stream dropped:",
      conversationId,
      error,
    );
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
    const offer =
      error instanceof ApiError && error.status === HTTP_PAYMENT_REQUIRED
        ? parseSubscriptionRequiredBody(error.body)
        : undefined;
    if (offer) usePaywallStore.getState().setBlocked(offer);
    throw error;
  }
  follower.wake(conversationId);
}
