import type {
  ReplyToMessageData,
  SelectedWorkflowDataInput,
} from "@gaia/shared/api/generated";
import { messageToRetry } from "@gaia/shared/conversation";
import { randomUUID } from "expo-crypto";
import { queryClient } from "@/lib/query-provider";
import { usePaywallStore } from "@/stores/paywall-store";
import type { ApiFileData } from "../api/chat-api";
import { chatKeys } from "../api/queries";
import type { Conversation } from "../types";
import { deliverSend } from "./connection";
import {
  liveConversation,
  type MobileSend,
  useLiveConversationStore,
} from "./live-conversation-store";
import { toApiFileData } from "./live-messages";

const NEW_CONVERSATION_TITLE = "New conversation";

export interface SendInput {
  text: string;
  /** The conversation to send into; null starts a new one. */
  conversationId: string | null;
  files?: ApiFileData[];
  replyToMessage?: ReplyToMessageData | null;
  selectedTool?: string | null;
  toolCategory?: string | null;
  selectedWorkflow?: SelectedWorkflowDataInput | null;
  /** The accepted message this one resends from its retry action. */
  retryOf?: string | null;
}

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

/**
 * Send a user message: its bubble shows at once and the reply arrives on the
 * conversation's events. Returns the conversation it went into, minted for a new chat.
 */
export function sendMessage(input: SendInput): string {
  const conversationId = input.conversationId ?? startConversation();
  const files = input.files ?? [];
  const replyToMessage = input.replyToMessage ?? null;
  const messageId = randomUUID();
  const send: MobileSend = {
    body: {
      message_id: messageId,
      text: input.text.trim(),
      reply_to: replyToMessage?.id ?? null,
      reply_to_message: replyToMessage,
      retry_of: input.retryOf ?? null,
      file_ids: files.map((file) => file.fileId),
      selected_tool: input.selectedTool ?? null,
      tool_category: input.toolCategory ?? null,
      selected_workflow: input.selectedWorkflow ?? null,
    },
    fileData: files,
    sentAt: new Date().toISOString(),
    failed: false,
  };
  // A previous wall comes straight back with the next 402; a subscribed user sends through.
  usePaywallStore.getState().clearBlock();
  useLiveConversationStore.getState().queueSend(conversationId, send);
  deliverSend(conversationId, messageId).catch((error: unknown) => {
    console.error("[sendMessage] send failed:", error);
  });
  return conversationId;
}

/**
 * Retry from a bubble: a send that never reached the server is resent as-is, so the
 * server's message id dedup holds; an accepted message is sent again naming it in retry_of.
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
  const message = messageToRetry(live.view, messageId);
  if (!message) {
    console.error("[retryMessage] No user message to retry:", messageId);
    return;
  }
  sendMessage({
    text: message.text,
    conversationId,
    files: toApiFileData(message.files),
    replyToMessage: message.reply_to_message,
    selectedTool: message.selected_tool,
    toolCategory: message.tool_category,
    selectedWorkflow: message.selected_workflow,
    retryOf: message.id,
  });
}
