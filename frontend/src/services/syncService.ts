import {
  chatApi,
  type Conversation,
  type ConversationSyncItem,
} from "@/features/chat/api/chatApi";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { MessageType } from "@/types/features/convoTypes";

const MAX_SYNC_CONVERSATIONS = 100;

const mergeMessageLists = (
  localMessages: IMessage[],
  remoteMessages: IMessage[],
): IMessage[] => {
  const messageMap = new Map<string, IMessage>();

  // Start with local messages
  localMessages.forEach((msg) => messageMap.set(msg.id, msg));

  // Merge with remote messages - prefer remote for existing messages
  remoteMessages.forEach((msg) => {
    const existing = messageMap.get(msg.id);
    if (!existing) {
      // New message from remote
      messageMap.set(msg.id, msg);
    } else if (existing.optimistic) {
      // Always replace optimistic messages with remote versions
      messageMap.set(msg.id, msg);
    } else {
      // Message exists locally - prefer remote if it's newer
      const remoteTime = msg.updatedAt?.getTime() ?? msg.createdAt.getTime();
      const localTime =
        existing.updatedAt?.getTime() ?? existing.createdAt.getTime();
      if (remoteTime > localTime) {
        messageMap.set(msg.id, msg);
      }
    }
  });

  // Convert back to array and sort by creation time
  return Array.from(messageMap.values()).sort(
    (a, b) => a.createdAt.getTime() - b.createdAt.getTime(),
  );
};

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

const toTimestamp = (timestamp?: string): number => {
  if (!timestamp) return 0;
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
};

const identifyStaleConversations = (
  localConversations: IConversation[],
  remoteConversations: Conversation[],
): ConversationSyncItem[] => {
  const localMap = new Map(
    localConversations.map((conv) => [
      conv.id,
      conv.updatedAt || conv.createdAt,
    ]),
  );

  const staleItems: ConversationSyncItem[] = [];

  for (const remote of remoteConversations) {
    const conversationId = remote.conversation_id;
    const localUpdatedAt = localMap.get(conversationId);

    if (!localUpdatedAt) {
      // New conversation not in local DB
      staleItems.push({
        conversation_id: conversationId,
        last_updated: undefined,
      });
      continue;
    }

    const remoteUpdated = toTimestamp(remote.updatedAt ?? remote.createdAt);
    const localUpdated = localUpdatedAt.getTime();

    if (remoteUpdated > localUpdated) {
      // Remote is newer than local
      staleItems.push({
        conversation_id: conversationId,
        last_updated: localUpdatedAt.toISOString(),
      });
    }
  }

  return staleItems;
};

export const batchSyncConversations = async (): Promise<void> => {
  try {
    const [remoteConversations, localConversations] = await Promise.all([
      chatApi
        .fetchConversations(1, MAX_SYNC_CONVERSATIONS)
        .then((res) => res.conversations),
      db.getAllConversations(),
    ]);

    if (remoteConversations.length === 0) {
      return;
    }

    const staleItems = identifyStaleConversations(
      localConversations,
      remoteConversations,
    );

    if (staleItems.length === 0) {
      return;
    }

    const { conversations: freshConversations } =
      await chatApi.batchSyncConversations(staleItems);

    if (freshConversations.length === 0) {
      return;
    }

    await Promise.allSettled(
      freshConversations.map(async (conversation) => {
        const conversationId = conversation.conversation_id;
        const messages = conversation.messages ?? [];

        const mappedConversation: IConversation = {
          id: conversationId,
          title: conversation.description || "Untitled conversation",
          description: conversation.description,
          starred: conversation.starred ?? false,
          isSystemGenerated: conversation.is_system_generated ?? false,
          systemPurpose: conversation.system_purpose ?? null,
          createdAt: new Date(conversation.createdAt),
          updatedAt: conversation.updatedAt
            ? new Date(conversation.updatedAt)
            : new Date(conversation.createdAt),
        };

        const remoteMessages = mapApiMessagesToStored(messages, conversationId);
        const localMessages =
          await db.getMessagesForConversation(conversationId);
        const mergedMessages = mergeMessageLists(localMessages, remoteMessages);

        await Promise.allSettled([
          db.putConversation(mappedConversation),
          messages.length > 0
            ? db.syncMessages(conversationId, mergedMessages)
            : Promise.resolve(),
        ]);
      }),
    );
  } catch {
    // Ignore background sync errors to avoid impacting the UI
  }
};
