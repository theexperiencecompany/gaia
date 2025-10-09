import { chatApi, type Conversation } from "@/features/chat/api/chatApi";
import { mapApiConversation } from "@/hooks/useConversations";
import { db, type IMessage } from "@/lib/db/chatDb";
import { MessageType } from "@/types/features/convoTypes";

const MAX_SYNC_CONVERSATIONS = 50;

const mapApiMessagesToStored = (
  messages: MessageType[],
  conversationId: string,
): IMessage[] =>
  messages.map((message, index) => {
    const createdAt = message.date ? new Date(message.date) : new Date();
    const role = mapMessageRole(message.type);
    const messageId =
      message.message_id || `${conversationId}-${index}-${createdAt.getTime()}`;

    return {
      id: messageId,
      conversationId,
      content: message.response,
      role,
      status: message.loading ? "sending" : "sent",
      createdAt,
      updatedAt: createdAt,
      messageId: message.message_id,
      fileIds: message.fileIds,
      fileData: message.fileData,
      toolName: message.selectedTool ?? null,
      toolCategory: message.toolCategory ?? null,
      workflowId: message.selectedWorkflow?.id ?? null,
      metadata: {
        originalMessage: message,
      },
    } satisfies IMessage;
  });

const mapMessageRole = (
  role: MessageType["type"],
): "user" | "assistant" | "system" => {
  switch (role) {
    case "user":
      return "user";
    case "bot":
      return "assistant";
    default:
      return "system";
  }
};

const fetchRecentConversations = async (): Promise<Conversation[]> => {
  try {
    const { conversations } = await chatApi.fetchConversations(
      1,
      MAX_SYNC_CONVERSATIONS,
    );
    return conversations;
  } catch {
    return [];
  }
};

const toTimestamp = (timestamp?: string): number => {
  if (!timestamp) return Date.now();
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? Date.now() : parsed.getTime();
};

export const syncAndPrecacheMessages = async (): Promise<void> => {
  try {
    const [remoteConversations, cachedConversationIds, localConversations] =
      await Promise.all([
        fetchRecentConversations(),
        db.getConversationIdsWithMessages(),
        db.getAllConversations(),
      ]);

    if (remoteConversations.length === 0) {
      return;
    }

    const cachedSet = new Set(cachedConversationIds);
    const localConversationUpdatedAt = new Map(
      localConversations.map((conversation) => [
        conversation.id,
        conversation.updatedAt.getTime(),
      ]),
    );

    const pendingConversations = remoteConversations.filter(
      (conversation) => {
        const conversationId = conversation.conversation_id;
        if (!conversationId) return false;

        const remoteUpdatedAt = toTimestamp(
          conversation.updatedAt ?? conversation.createdAt,
        );
        const localUpdatedAt = localConversationUpdatedAt.get(conversationId);

        if (!cachedSet.has(conversationId)) {
          return true;
        }

        if (!localUpdatedAt) {
          return true;
        }

        return remoteUpdatedAt > localUpdatedAt;
      },
    );

    if (pendingConversations.length === 0) {
      return;
    }

    await Promise.allSettled(
      pendingConversations.map(async (conversation) => {
        const conversationId = conversation.conversation_id;
        if (!conversationId) return;

        try {
          const messages = await chatApi.fetchMessages(conversationId);
          if (messages.length === 0) return;

          const mappedMessages = mapApiMessagesToStored(
            messages,
            conversationId,
          );

          await Promise.allSettled([
            db.putMessagesBulk(mappedMessages),
            db.putConversation(mapApiConversation(conversation)),
          ]);
        } catch {
          // Ignore conversation-level sync failures
        }
      }),
    );
  } catch {
    // Ignore background sync errors to avoid impacting the UI
  }
};
