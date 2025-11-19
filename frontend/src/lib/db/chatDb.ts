import Dexie, { Table } from "dexie";
import { EventEmitter } from "events";

import { SystemPurpose } from "@/features/chat/api/chatApi";
import { FileData } from "@/types/shared";

type MessageRole = "user" | "assistant" | "system";
type MessageStatus = "sending" | "sent" | "failed";

export interface IConversation {
  id: string;
  title: string;
  description?: string;
  userId?: string;
  starred?: boolean;
  isSystemGenerated?: boolean;
  systemPurpose?: SystemPurpose | null;
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
  fileIds?: string[];
  fileData?: FileData[];
  toolName?: string | null;
  toolCategory?: string | null;
  workflowId?: string | null;
  metadata?: Record<string, unknown>;
  optimistic?: boolean; // Temporary message waiting for backend ID
}

class MessageQueue {
  private queue: Promise<any> = Promise.resolve();

  async enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.queue.then(operation);
    this.queue = result.catch(() => {}); // Don't propagate errors to queue
    return result;
  }
}

export const messageQueue = new MessageQueue();

class DBEventEmitter extends EventEmitter {
  emitMessageAdded(message: IMessage) {
    this.emit("messageAdded", message);
  }

  emitMessageUpdated(message: IMessage) {
    this.emit("messageUpdated", message);
  }

  emitMessagesSynced(conversationId: string, messages: IMessage[]) {
    this.emit("messagesSynced", conversationId, messages);
  }

  emitConversationAdded(conversation: IConversation) {
    this.emit("conversationAdded", conversation);
  }

  emitConversationUpdated(conversation: IConversation) {
    this.emit("conversationUpdated", conversation);
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
    return messageQueue.enqueue(async () => {
      const existing = await this.conversations.get(conversation.id);
      const id = await this.conversations.put(conversation);
      if (existing) {
        dbEventEmitter.emitConversationUpdated(conversation);
      } else {
        dbEventEmitter.emitConversationAdded(conversation);
      }
      return id;
    });
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

  public putMessage(message: IMessage): Promise<string> {
    return messageQueue.enqueue(async () => {
      const id = await this.messages.put(message);
      dbEventEmitter.emitMessageAdded(message);
      return id;
    });
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

  public async updateMessageContent(
    messageId: string,
    content: string,
  ): Promise<void> {
    await messageQueue.enqueue(async () => {
      const message = await this.messages.get(messageId);
      if (message) {
        const updatedMessage = { ...message, content, updatedAt: new Date() };
        await this.messages.put(updatedMessage);
        dbEventEmitter.emitMessageUpdated(updatedMessage);
      }
    });
  }

  public async updateMessageStatus(
    messageId: string,
    status: IMessage["status"],
  ): Promise<void> {
    return messageQueue.enqueue(async () => {
      await this.messages.update(messageId, {
        status,
        updatedAt: new Date(),
      });

      const updatedMessage = await this.messages.get(messageId);
      if (updatedMessage) {
        dbEventEmitter.emitMessageUpdated(updatedMessage);
      }
    });
  }

  public async replaceOptimisticMessage(
    optimisticId: string,
    backendId: string,
  ): Promise<void> {
    return messageQueue.enqueue(async () => {
      const message = await this.messages.get(optimisticId);
      if (!message) {
        console.warn(`Optimistic message ${optimisticId} not found`);
        return;
      }

      // Delete optimistic message
      await this.messages.delete(optimisticId);

      // Create new message with backend ID
      const updatedMessage: IMessage = {
        ...message,
        id: backendId,
        messageId: backendId,
        optimistic: false,
        updatedAt: new Date(),
      };

      await this.messages.put(updatedMessage);

      dbEventEmitter.emitMessageUpdated(updatedMessage);
    });
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

  public async updateConversationFields(
    conversationId: string,
    updates: Partial<IConversation>,
  ): Promise<void> {
    await messageQueue.enqueue(async () => {
      const existing = await this.conversations.get(conversationId);
      if (existing) {
        const updated = { ...existing, ...updates, updatedAt: new Date() };
        await this.conversations.put(updated);
        dbEventEmitter.emitConversationUpdated(updated);
      }
    });
  }
}

export const db = new ChatDexie();
