import type { SendMessageRequest } from "@gaia/shared/api/generated";
import { isConversationIdTaken, retryTarget } from "@gaia/shared/conversation";
import { randomUUID } from "expo-crypto";
import { queryClient } from "@/lib/query-provider";
import { usePaywallStore } from "@/stores/paywall-store";
import type { ApiFileData } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import type { Conversation } from "../types";
import { deliverRetry, deliverSend } from "./connection";
import {
  liveConversation,
  type MobileSend,
  useLiveConversationStore,
} from "./live-conversation-store";

const NEW_CONVERSATION_TITLE = "New conversation";

/** What the user sends; the ids, the reply pointer and the file ids are filled in here. */
export type OutgoingMessage = Omit<
  SendMessageRequest,
  "message_id" | "reply_to" | "file_ids"
>;

/** Mint a conversation id and show it in the sidebar before its first message is accepted. */
function startConversation(): string {
  const conversationId = randomUUID();
  const now = new Date().toISOString();
  const conversation: Conversation = {
    id: conversationId,
    title: NEW_CONVERSATION_TITLE,
    created_at: now,
    updated_at: now,
  };
  queryClient.setQueryData(
    chatKeys.conversations(),
    (previous: Conversation[] | undefined) =>
      previous ? [conversation, ...previous] : previous,
  );
  return conversationId;
}

/** Drop a conversation whose first message was refused, from the live store and the sidebar. */
function abandonConversation(conversationId: string): void {
  useLiveConversationStore.getState().discard(conversationId);
  queryClient.setQueryData(
    chatKeys.conversations(),
    (previous: Conversation[] | undefined) =>
      previous?.filter((conversation) => conversation.id !== conversationId),
  );
}

/** A new conversation's first send, which starts over once under a fresh id when its minted id is taken. */
interface Restart {
  onRestart: ((conversationId: string) => void) | undefined;
}

function queueAndDeliver(
  target: string,
  message: OutgoingMessage,
  files: ApiFileData[],
  restart: Restart | null,
): void {
  const messageId = randomUUID();
  const send: MobileSend = {
    body: {
      ...message,
      message_id: messageId,
      text: message.text.trim(),
      reply_to: message.reply_to_message?.id ?? null,
      file_ids: files.map((file) => file.fileId),
    },
    fileData: files,
    sentAt: new Date().toISOString(),
    failed: false,
  };
  // A previous wall comes straight back with the next 402; a subscribed user sends through.
  usePaywallStore.getState().clearBlock();
  useLiveConversationStore.getState().queueSend(target, send);
  deliverSend(target, messageId).catch((error: unknown) => {
    if (restart && isConversationIdTaken(error)) {
      abandonConversation(target);
      const fresh = startConversation();
      queueAndDeliver(fresh, message, files, null);
      restart.onRestart?.(fresh);
      return;
    }
    console.error("[sendMessage] send failed:", error);
  });
}

/**
 * Send a user message into a conversation, or a new one when it is null: its bubble
 * shows at once and the reply arrives on the conversation's events. Returns the
 * conversation it went into; when a new conversation's minted id turns out to be taken,
 * the send starts over under a fresh id and onRestart is told which.
 */
export function sendMessage(
  conversationId: string | null,
  message: OutgoingMessage,
  files: ApiFileData[] = [],
  onRestart?: (conversationId: string) => void,
): string {
  const target = conversationId ?? startConversation();
  queueAndDeliver(
    target,
    message,
    files,
    conversationId === null ? { onRestart } : null,
  );
  return target;
}

/**
 * Retry from a bubble: a send that never reached the server is resent as-is, so the
 * server's message id dedup holds; an accepted message is answered again by the server, in its place.
 */
export async function retryMessage(
  conversationId: string,
  messageId: string,
): Promise<void> {
  const live = liveConversation(conversationId);
  if (live.sends[messageId]?.failed) {
    await deliverSend(conversationId, messageId);
    return;
  }
  const target = retryTarget(live.view, messageId);
  if (!target) {
    console.error("[retryMessage] No user message to retry:", messageId);
    return;
  }
  await deliverRetry(conversationId, target);
}
