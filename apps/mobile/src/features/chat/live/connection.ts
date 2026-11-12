import { ApiError, parseSubscriptionRequiredBody } from "@gaia/shared";
import { createConversationFollower } from "@gaia/shared/conversation/live";
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
  view: (conversationId) => liveConversation(conversationId).view,
  apply: (conversationId, frame) =>
    useLiveConversationStore.getState().applyFrames(conversationId, [frame]),
  retitle: retitleConversation,
  // Mobile keeps the live log in memory only: a fresh follow replays it from the server.
  prepare: async () => undefined,
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
