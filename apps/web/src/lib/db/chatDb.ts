import Dexie, { type Table } from "dexie";
import { EventEmitter } from "events";

import type { ToolDataEntry } from "@/config";
import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { ImageData, MemoryData } from "@/types";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared";

export interface IConversation {
  id: string;
  title: string;
  description?: string;
  userId?: string;
  starred?: boolean;
  isSystemGenerated?: boolean;
  systemPurpose?: SystemPurpose | null;
  isUnread?: boolean;
  createdAt: Date;
  updatedAt: Date;
}

export interface IMessage {
  id: string;
  conversationId: string;
  content: string;
  role: "user" | "assistant" | "system";
  status: "sending" | "sent" | "failed";
  createdAt: Date;
  updatedAt: Date;
  messageId?: string;

  // File data
  fileIds?: string[];
  fileData?: FileData[];

  // Tool/workflow data
  toolName?: string | null;
  toolCategory?: string | null;
  workflowId?: string | null;
  selectedWorkflow?: WorkflowData | null;
  selectedCalendarEvent?: SelectedCalendarEventData | null;

  // Rich content data from BaseMessageData
  tool_data?: ToolDataEntry[] | null;
  follow_up_actions?: string[] | null;
  image_data?: ImageData | null;
  memory_data?: MemoryData | null;

  // Message metadata
  pinned?: boolean;
  isConvoSystemGenerated?: boolean;
  metadata?: Record<string, unknown>;
  optimistic?: boolean; // Temporary message waiting for backend ID

  // Reply data
  replyToMessageId?: string | null;
  replyToMessageData?: {
    id: string;
    content: string;
    role: "user" | "assistant";
  } | null;
}

class MessageQueue {
  private queue: Promise<unknown> = Promise.resolve();

  async enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation);
    this.queue = result.catch(() => {}); // Don't propagate errors to queue
    return result;
  }
}

export const messageQueue = new MessageQueue();

class DBEventEmitter extends EventEmitter {
  constructor() {
    super();
    this.setMaxListeners(1); // Enforce single listener per event
  }

  emitMessageAdded(message: IMessage) {
    this.emit("messageAdded", message);
  }

  emitMessageUpdated(message: IMessage) {
    this.emit("messageUpdated", message);
  }

  emitMessageDeleted(messageId: string, conversationId: string) {
    this.emit("messageDeleted", messageId, conversationId);
  }

  emitMessagesSynced(conversationId: string, messages: IMessage[]) {
    this.emit("messagesSynced", conversationId, messages);
  }

  emitMessageIdReplaced(oldId: string, newMessage: IMessage) {
    this.emit("messageIdReplaced", oldId, newMessage);
  }

  emitConversationAdded(conversation: IConversation) {
    this.emit("conversationAdded", conversation);
  }

  emitConversationUpdated(conversation: IConversation) {
    this.emit("conversationUpdated", conversation);
  }

  emitConversationDeleted(conversationId: string) {
    this.emit("conversationDeleted", conversationId);
  }

  emitConversationsDeletedBulk(conversationIds: string[]) {
    this.emit("conversationsDeletedBulk", conversationIds);
  }
}

export const dbEventEmitter = new DBEventEmitter();

export class ChatDexie extends Dexie {
  public conversations!: Table<IConversation, string>;
  public messages!: Table<IMessage, string>;

  constructor() {
    super("ChatDatabase");

    this.version(1).stores({
      conversations: "id, updatedAt, createdAt",
      messages: "id, conversationId, createdAt",
    });

    this.conversations = this.table("conversations");
    this.messages = this.table("messages");
  }

  public getConversation(id: string): Promise<IConversation | undefined> {
    return this.conversations.get(id);
  }

  public getAllConversations(): Promise<IConversation[]> {
    return this.conversations.orderBy("updatedAt").reverse().toArray();
  }

  public async putConversation(conversation: IConversation): Promise<string> {
    const existing = await this.conversations.get(conversation.id);
    const id = await messageQueue.enqueue(async () => {
      return await this.conversations.put(conversation);
    });
    if (existing) {
      dbEventEmitter.emitConversationUpdated(conversation);
    } else {
      dbEventEmitter.emitConversationAdded(conversation);
    }
    return id;
  }

  public async putConversationsBulk(
    conversations: IConversation[],
  ): Promise<string[]> {
    // await this.conversations.bulkPut(conversations);
    // return conversations.map((conversation) => conversation.id);
    await messageQueue.enqueue(async () => {
      await this.conversations.bulkPut(conversations);
      conversations.forEach((conv) =>
        dbEventEmitter.emitConversationAdded(conv),
      );
    });
    return conversations.map((conversation) => conversation.id);
  }

  public getMessagesForConversation(
    conversationId: string,
  ): Promise<IMessage[]> {
    return this.messages
      .where("conversationId")
      .equals(conversationId)
      .sortBy("createdAt");
  }

  public async getConversationIdsWithMessages(): Promise<string[]> {
    const conversationIds = await this.messages
      .orderBy("conversationId")
      .keys();
    return Array.from(new Set(conversationIds)) as string[];
  }

  public async putMessage(message: IMessage): Promise<string> {
    const id = await messageQueue.enqueue(async () => {
      return await this.messages.put(message);
    });
    dbEventEmitter.emitMessageAdded(message);
    return id;
  }

  public async putMessagesBulk(messages: IMessage[]): Promise<string[]> {
    await messageQueue.enqueue(async () => {
      await this.messages.bulkPut(messages);
      messages.forEach((msg) => dbEventEmitter.emitMessageAdded(msg));
    });
    return messages.map((message) => message.id);
  }

  public async replaceMessage(
    temporaryId: string,
    message: IMessage,
  ): Promise<void> {
    await messageQueue.enqueue(() =>
      (this as Dexie).transaction("rw", this.messages, async () => {
        await this.messages.delete(temporaryId);
        await this.messages.put(message);
        dbEventEmitter.emitMessageUpdated(message);
      }),
    );
  }

  public async deleteConversationAndMessages(
    conversationId: string,
  ): Promise<void> {
    await messageQueue.enqueue(() =>
      (this as Dexie).transaction(
        "rw",
        this.conversations,
        this.messages,
        async () => {
          await this.messages
            .where("conversationId")
            .equals(conversationId)
            .delete();
          await this.conversations.delete(conversationId);
        },
      ),
    );
  }

  /**
   * Bulk delete multiple conversations and their messages.
   * Used by sync service to clean up deleted conversations.
   */
  public async deleteConversationsAndMessagesBulk(
    conversationIds: string[],
  ): Promise<void> {
    if (conversationIds.length === 0) return;

    await messageQueue.enqueue(() =>
      (this as Dexie).transaction(
        "rw",
        this.conversations,
        this.messages,
        async () => {
          // Delete all messages for these conversations
          for (const conversationId of conversationIds) {
            await this.messages
              .where("conversationId")
              .equals(conversationId)
              .delete();
          }
          // Delete the conversations themselves
          await this.conversations.bulkDelete(conversationIds);
        },
      ),
    );

    // Emit event for store synchronization
    dbEventEmitter.emitConversationsDeletedBulk(conversationIds);
  }

  public async updateMessageContent(
    messageId: string,
    content: string,
  ): Promise<void> {
    let updatedMessage: IMessage | undefined;
    await messageQueue.enqueue(async () => {
      const message = await this.messages.get(messageId);
      if (message) {
        updatedMessage = { ...message, content, updatedAt: new Date() };
        await this.messages.put(updatedMessage);
      }
    });
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpdated(updatedMessage);
    }
  }

  public async updateMessage(
    messageId: string,
    updates: Partial<IMessage>,
  ): Promise<void> {
    let updatedMessage: IMessage | undefined;
    await messageQueue.enqueue(async () => {
      const message = await this.messages.get(messageId);
      if (message) {
        updatedMessage = { ...message, ...updates, updatedAt: new Date() };
        await this.messages.put(updatedMessage);
      }
    });
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpdated(updatedMessage);
    }
  }

  public async updateMessageStatus(
    messageId: string,
    status: IMessage["status"],
  ): Promise<void> {
    let updatedMessage: IMessage | undefined;
    await messageQueue.enqueue(async () => {
      await this.messages.update(messageId, {
        status,
        updatedAt: new Date(),
      });
      updatedMessage = await this.messages.get(messageId);
    });
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpdated(updatedMessage);
    }
  }

  public async replaceOptimisticMessage(
    optimisticId: string,
    backendId: string,
    updatedData?: Partial<IMessage>,
  ): Promise<void> {
    let finalMessage: IMessage | undefined;
    await messageQueue.enqueue(async () => {
      const message = await this.messages.get(optimisticId);
      if (!message) {
        console.warn(`Optimistic message ${optimisticId} not found`);
        return;
      }

      // Use atomic update to change only the ID fields, preserving everything else including createdAt
      await this.messages.update(optimisticId, {
        id: backendId,
        messageId: backendId,
        optimistic: false,
        updatedAt: new Date(),
        ...updatedData,
      });

      finalMessage = await this.messages.get(backendId);
    });
    if (finalMessage) {
      dbEventEmitter.emitMessageIdReplaced(optimisticId, finalMessage);
    }
  }

  public async syncMessages(
    conversationId: string,
    messages: IMessage[],
  ): Promise<void> {
    await messageQueue.enqueue(async () => {
      await (this as Dexie).transaction("rw", this.messages, async () => {
        await this.messages.bulkPut(messages);
        dbEventEmitter.emitMessagesSynced(conversationId, messages);
      });
    });
  }

  public async clearAll(): Promise<void> {
    await messageQueue.enqueue(() =>
      (this as Dexie).transaction(
        "rw",
        this.conversations,
        this.messages,
        async () => {
          await this.messages.clear();
          await this.conversations.clear();
        },
      ),
    );
  }

  public async cleanupOrphanedOptimisticMessages(
    maxAgeMinutes = 5,
  ): Promise<number> {
    const cutoffTime = Date.now() - maxAgeMinutes * 60 * 1000;
    let deletedCount = 0;

    await messageQueue.enqueue(async () => {
      const allMessages = await this.messages.toArray();
      const orphaned = allMessages.filter(
        (m) => m.optimistic && m.createdAt.getTime() < cutoffTime,
      );

      for (const msg of orphaned) {
        await this.messages.delete(msg.id);
        deletedCount++;
      }
    });

    return deletedCount;
  }

  public async updateConversationFields(
    conversationId: string,
    updates: Partial<IConversation>,
  ): Promise<void> {
    let updated: IConversation | undefined;
    await messageQueue.enqueue(async () => {
      const existing = await this.conversations.get(conversationId);
      if (existing) {
        updated = { ...existing, ...updates, updatedAt: new Date() };
        await this.conversations.put(updated);
      }
    });
    if (updated) {
      dbEventEmitter.emitConversationUpdated(updated);
    }
  }
}

export const db = new ChatDexie();
