import { isConversationIdTaken } from "@shared/conversation";
import { v4 as uuidv4 } from "uuid";

import { setUserProperties } from "@/lib/analytics";
import { db, type IConversation } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";
import type { FileData } from "@/types/shared/fileTypes";
import { deliverSend, persistConversation } from "./connection";
import {
  type LocalSend,
  type LocalSendBody,
  useLiveConversationStore,
} from "./liveConversationStore";

/** The composer's choices for one send: the request fields it sets, its files, and where it goes. */
export type SendMessageOverrides = Partial<
  Pick<
    LocalSendBody,
    | "reply_to_message"
    | "retry_of"
    | "selected_tool"
    | "tool_category"
    | "selected_workflow"
    | "selected_calendar_event"
  >
> & {
  files?: FileData[];
  /** The conversation to send into; null starts a new one. Omitted: the active conversation. */
  conversationId?: string | null;
};

const NEW_CONVERSATION_ROUTE_ID = "new";
const NEW_CONVERSATION_TITLE = "New Chat";

const trackFirstMessageMilestone = () => {
  try {
    if (localStorage.getItem("gaia_first_message_sent")) return;
    // Volume is chat:message_submitted server-side; this only sets the person property.
    setUserProperties({ first_message_sent: true });
    localStorage.setItem("gaia_first_message_sent", "true");
  } catch {
    // localStorage unavailable: the milestone is a segmentation nicety, not state.
  }
};

const targetConversationId = (overrides?: SendMessageOverrides) => {
  const requested =
    overrides && "conversationId" in overrides
      ? (overrides.conversationId ?? null)
      : useChatStore.getState().activeConversationId;
  return requested === NEW_CONVERSATION_ROUTE_ID ? null : requested;
};

/** Mint a conversation id and show it as the open chat before its first message is accepted. */
async function startConversation(): Promise<string> {
  const conversationId = uuidv4();
  const now = new Date();
  const conversation: IConversation = {
    id: conversationId,
    title: NEW_CONVERSATION_TITLE,
    description: NEW_CONVERSATION_TITLE,
    starred: false,
    isSystemGenerated: false,
    createdAt: now,
    updatedAt: now,
  };
  const chatStore = useChatStore.getState();
  chatStore.upsertConversation(conversation);
  chatStore.setActiveConversationId(conversationId);
  if (/^\/c(\/|$)/.test(globalThis.location.pathname)) {
    globalThis.history.replaceState({}, "", `/c/${conversationId}`);
  }
  await db.putConversation(conversation);
  return conversationId;
}

/** Drop a conversation whose first message was refused, so the next attempt starts under a fresh id. */
async function abandonConversation(conversationId: string): Promise<void> {
  useLiveConversationStore.getState().discard(conversationId);
  useChatStore.getState().removeConversation(conversationId);
  await db.deleteConversationAndLog(conversationId);
}

async function queueAndDeliver(
  conversationId: string,
  send: LocalSend,
): Promise<void> {
  useLiveConversationStore.getState().queueSend(conversationId, send);
  persistConversation(conversationId, { immediately: true });
  await deliverSend(conversationId, send.body.message_id);
}

/** Send a user message: its bubble shows at once, and the reply arrives on the conversation's events. */
export async function sendMessage(
  content: string,
  overrides?: SendMessageOverrides,
): Promise<void> {
  const text = content.trim();
  const fileData = overrides?.files ?? [];
  const replyToMessage = overrides?.reply_to_message ?? null;
  const selectedTool = overrides?.selected_tool ?? null;
  const selectedWorkflow = overrides?.selected_workflow ?? null;
  const selectedCalendarEvent = overrides?.selected_calendar_event ?? null;
  const hasSelection =
    selectedTool || selectedWorkflow || selectedCalendarEvent;
  if (!text && fileData.length === 0 && !hasSelection) return;

  trackFirstMessageMilestone();
  const existingId = targetConversationId(overrides);
  const buildSend = (): LocalSend => ({
    body: {
      message_id: uuidv4(),
      text,
      reply_to: replyToMessage?.id ?? null,
      reply_to_message: replyToMessage,
      retry_of: overrides?.retry_of ?? null,
      file_ids: fileData.map((file) => file.fileId),
      selected_tool: selectedTool,
      tool_category: overrides?.tool_category ?? null,
      selected_workflow: selectedWorkflow,
      selected_calendar_event: selectedCalendarEvent,
    },
    fileData,
    failed: false,
  });

  if (existingId) {
    await queueAndDeliver(existingId, buildSend());
    return;
  }
  const conversationId = await startConversation();
  try {
    await queueAndDeliver(conversationId, buildSend());
  } catch (error) {
    if (!isConversationIdTaken(error)) throw error;
    await abandonConversation(conversationId);
    await queueAndDeliver(await startConversation(), buildSend());
  }
}
