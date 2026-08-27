import Dexie, { type IndexableType, type Table } from "dexie";
import { EventEmitter } from "events";

import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type { SelectedCalendarEventData } from "@/stores/calendarEventSelectionStore";
import type { TodoProgressData } from "@/types/features/todoProgressTypes";
import type {
  ArtifactData,
  ImageData,
  MemoryData,
} from "@/types/features/toolDataTypes";
import type { WorkflowData } from "@/types/features/workflowTypes";
import type { FileData } from "@/types/shared/fileTypes";

export interface IConversation {
  id: string;
  title: string;
  description?: string;
  userId?: string;
  starred?: boolean;
  isSystemGenerated?: boolean;
  isOnboardingConversation?: boolean;
  systemPurpose?: SystemPurpose | null;
  isUnread?: boolean;
  source?: string; // ConversationSource from backend (web, telegram, discord, etc.)
  // Conversation-level artifact registry: the single source of truth for this
  // conversation's agent-written files. Messages store path references that
  // resolve against this (see FileArtifactSection / chatStore).
  artifacts?: ArtifactData[];
  createdAt: Date;
  updatedAt: Date;
}

export interface IMessage {
  id: string;
  conversationId: string;
  content: string;
  role: "user" | "assistant" | "system";
  status: "sending" | "sent" | "failed" | "queued";
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
  todo_progress?: TodoProgressData | null;

  // Message metadata
  pinned?: boolean;
  isConvoSystemGenerated?: boolean;
  // Present when a bot turn died with no response text (persisted server-side).
  error?: string | null;
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
    // Don't propagate errors to the queue chain; `result` still rejects for the caller.
    this.queue = result.catch(() => {
      /* swallowed on purpose so the chain stays alive — see comment above */
    });
    return result;
  }
}

const messageQueue = new MessageQueue();

class DBEventEmitter extends EventEmitter {
  constructor() {
    super();
    this.setMaxListeners(1); // Enforce single listener per event
  }

  emitMessageUpserted(message: IMessage) {
    this.emit("messageUpserted", message);
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

class ChatDexie extends Dexie {
  public conversations!: Table<IConversation, string>;
  public messages!: Table<IMessage, string>;

  /**
   * Resolves to whether IndexedDB persistence is usable for this session.
   * iOS Safari refuses to open the database entirely under private browsing,
   * storage pressure, or the long-standing WebKit bug — the open throws
   * `DOMException: UnknownError: Unable to open database file on disk`.
   * Probed once and cached; see `run`. Also flips to `false` when a later
   * operation rejects (a transaction can fail after a successful open, e.g.
   * under storage pressure), so one failure degrades the whole session
   * instead of leaking uncaught rejections.
   */
  private usable: Promise<boolean> | null = null;

  constructor() {
    super("ChatDatabase");

    this.version(1).stores({
      conversations: "id, updatedAt, createdAt",
      messages: "id, conversationId, createdAt",
    });

    this.conversations = this.table("conversations");
    this.messages = this.table("messages");
  }

  /**
   * Whether IndexedDB persistence is usable this session. Attempts to open the
   * database once and caches the verdict; a failed open resolves to `false`
   * rather than rejecting, so callers degrade gracefully instead of surfacing
   * an uncaught rejection.
   */
  private isUsable(): Promise<boolean> {
    if (this.usable === null) {
      this.usable = this.open()
        .then(() => true)
        .catch((error: unknown) => {
          console.error(
            "IndexedDB unavailable — chat history will not persist this session:",
            error,
          );
          return false;
        });
    }
    return this.usable;
  }

  /**
   * Run a Dexie operation, degrading to `fallback` when IndexedDB persistence
   * is unavailable. This is the single guard for the whole store: callers keep
   * awaiting a resolved promise instead of every write becoming an uncaught
   * rejection on iOS Safari. A rejection from the operation itself (open
   * succeeded but the write/transaction failed) degrades the same way — the
   * session latches to unavailable and the fallback is returned. Event
   * emissions live outside this gate, so the in-memory store still updates
   * live and only cross-reload persistence is lost.
   */
  private async run<T>(fallback: T, operation: () => Promise<T>): Promise<T> {
    if (!(await this.isUsable())) return fallback;
    try {
      return await operation();
    } catch (error: unknown) {
      console.error(
        "IndexedDB unavailable — chat history will not persist this session:",
        error,
      );
      this.usable = Promise.resolve(false);
      return fallback;
    }
  }

  public getConversation(id: string): Promise<IConversation | undefined> {
    return this.run(undefined, () => this.conversations.get(id));
  }

  public getAllConversations(): Promise<IConversation[]> {
    return this.run([], () =>
      this.conversations.orderBy("updatedAt").reverse().toArray(),
    );
  }

  public async putConversation(conversation: IConversation): Promise<string> {
    const existing = await this.run(undefined, () =>
      this.conversations.get(conversation.id),
    );
    await this.run(undefined, () =>
      messageQueue.enqueue(() => this.conversations.put(conversation)),
    );
    if (existing) {
      dbEventEmitter.emitConversationUpdated(conversation);
    } else {
      dbEventEmitter.emitConversationAdded(conversation);
    }
    return conversation.id;
  }

  public async putConversationsBulk(
    conversations: IConversation[],
  ): Promise<string[]> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() => this.conversations.bulkPut(conversations)),
    );
    conversations.forEach((conv) => dbEventEmitter.emitConversationAdded(conv));
    return conversations.map((conversation) => conversation.id);
  }

  public getMessagesForConversation(
    conversationId: string,
  ): Promise<IMessage[]> {
    return this.run([], () =>
      this.messages
        .where("conversationId")
        .equals(conversationId)
        .sortBy("createdAt"),
    );
  }

  public getAllMessages(): Promise<IMessage[]> {
    return this.run([], () => this.messages.orderBy("createdAt").toArray());
  }

  public async getConversationIdsWithMessages(): Promise<string[]> {
    const conversationIds = await this.run([], () =>
      this.messages.orderBy("conversationId").keys(),
    );
    return Array.from(new Set(conversationIds)) as string[];
  }

  public async putMessage(message: IMessage): Promise<string> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() => this.messages.put(message)),
    );
    dbEventEmitter.emitMessageUpserted(message);
    return message.id;
  }

  public async putMessagesBulk(messages: IMessage[]): Promise<string[]> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() => this.messages.bulkPut(messages)),
    );
    messages.forEach((message) => dbEventEmitter.emitMessageUpserted(message));
    return messages.map((message) => message.id);
  }

  /**
   * Atomically persist a user-bot message pair in a single transaction.
   * This ensures both messages are saved together or neither is saved.
   */
  public async persistMessagePair(
    userMessage: IMessage | null,
    botMessage: IMessage | null,
  ): Promise<{ userMessage: IMessage | null; botMessage: IMessage | null }> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction("rw", this.messages, async () => {
          if (userMessage) {
            await this.messages.put(userMessage);
          }
          if (botMessage) {
            await this.messages.put(botMessage);
          }
        }),
      ),
    );

    // Emit events after successful transaction
    if (userMessage) {
      dbEventEmitter.emitMessageUpserted(userMessage);
    }
    if (botMessage) {
      dbEventEmitter.emitMessageUpserted(botMessage);
    }

    return { userMessage, botMessage };
  }

  public async replaceMessage(
    temporaryId: string,
    message: IMessage,
  ): Promise<void> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction("rw", this.messages, async () => {
          await this.messages.delete(temporaryId);
          await this.messages.put(message);
        }),
      ),
    );
    dbEventEmitter.emitMessageUpserted(message);
  }

  public async deleteConversationAndMessages(
    conversationId: string,
  ): Promise<void> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
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

    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction(
          "rw",
          this.conversations,
          this.messages,
          async () => {
            // Delete all messages for these conversations in one indexed
            // query — same rw transaction, no sequential await loop.
            await this.messages
              .where("conversationId")
              .anyOf(conversationIds)
              .delete();
            // Delete the conversations themselves
            await this.conversations.bulkDelete(conversationIds);
          },
        ),
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
    await this.run(undefined, () =>
      messageQueue.enqueue(async () => {
        const message = await this.messages.get(messageId);
        if (message) {
          updatedMessage = { ...message, content, updatedAt: new Date() };
          await this.messages.put(updatedMessage);
        }
      }),
    );
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpserted(updatedMessage);
    }
  }

  /** Merge `updates` into an existing message. Returns the updated record,
   *  or `undefined` when no record with that id exists (nothing is written). */
  public async updateMessage(
    messageId: string,
    updates: Partial<IMessage>,
  ): Promise<IMessage | undefined> {
    let updatedMessage: IMessage | undefined;
    await this.run(undefined, () =>
      messageQueue.enqueue(async () => {
        const message = await this.messages.get(messageId);
        if (message) {
          updatedMessage = {
            ...message,
            ...updates,
            updatedAt: new Date(),
          };
          await this.messages.put(updatedMessage);
        }
      }),
    );
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpserted(updatedMessage);
    }
    return updatedMessage;
  }

  public async updateMessageStatus(
    messageId: string,
    status: IMessage["status"],
  ): Promise<void> {
    let updatedMessage: IMessage | undefined;
    await this.run(undefined, () =>
      messageQueue.enqueue(async () => {
        const message = await this.messages.get(messageId);
        if (message) {
          updatedMessage = { ...message, status, updatedAt: new Date() };
          await this.messages.put(updatedMessage);
        }
      }),
    );
    if (updatedMessage) {
      dbEventEmitter.emitMessageUpserted(updatedMessage);
    }
  }

  public async replaceOptimisticMessage(
    optimisticId: string,
    backendId: string,
    updatedData?: Partial<IMessage>,
  ): Promise<void> {
    let finalMessage: IMessage | undefined;
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction("rw", this.messages, async () => {
          const message = await this.messages.get(optimisticId);
          if (!message) {
            console.warn(`Optimistic message ${optimisticId} not found`);
            return;
          }

          // Create the replacement message with the new backend ID
          // IndexedDB cannot change primary key via update(), so we delete + put
          finalMessage = {
            ...message,
            id: backendId,
            messageId: backendId,
            optimistic: false,
            updatedAt: new Date(),
            ...updatedData,
          };

          // Atomically delete old + add new within transaction
          await this.messages.delete(optimisticId);
          await this.messages.put(finalMessage);
        }),
      ),
    );
    if (finalMessage) {
      dbEventEmitter.emitMessageIdReplaced(optimisticId, finalMessage);
    }
  }

  public async syncMessages(
    conversationId: string,
    messages: IMessage[],
  ): Promise<void> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction("rw", this.messages, async () => {
          await this.messages.bulkPut(messages);
        }),
      ),
    );
    dbEventEmitter.emitMessagesSynced(conversationId, messages);
  }

  public async clearAll(): Promise<void> {
    const conversationIds = await this.run<IndexableType[]>([], () =>
      messageQueue.enqueue(async () => {
        const ids = await this.conversations.toCollection().primaryKeys();
        await (this as Dexie).transaction(
          "rw",
          this.conversations,
          this.messages,
          async () => {
            await this.messages.clear();
            await this.conversations.clear();
          },
        );
        return ids;
      }),
    );

    // Emit event for store synchronization
    dbEventEmitter.emitConversationsDeletedBulk(conversationIds as string[]);
  }

  public async cleanupOrphanedOptimisticMessages(
    maxAgeMinutes = 5,
  ): Promise<number> {
    const cutoffTime = Date.now() - maxAgeMinutes * 60 * 1000;
    let deletedCount = 0;

    await this.run(undefined, () =>
      messageQueue.enqueue(async () => {
        const allMessages = await this.messages.toArray();
        const orphaned = allMessages.filter(
          (m) => m.optimistic && m.createdAt.getTime() < cutoffTime,
        );
        const orphanedIds = orphaned.map((m) => m.id);

        await this.messages.bulkDelete(orphanedIds);
        deletedCount = orphaned.length;
      }),
    );

    return deletedCount;
  }

  public async updateConversationFields(
    conversationId: string,
    updates: Partial<IConversation>,
  ): Promise<void> {
    let updated: IConversation | undefined;
    await this.run(undefined, () =>
      messageQueue.enqueue(async () => {
        const existing = await this.conversations.get(conversationId);
        if (existing) {
          updated = { ...existing, ...updates, updatedAt: new Date() };
          await this.conversations.put(updated);
        }
      }),
    );
    if (updated) {
      dbEventEmitter.emitConversationUpdated(updated);
    }
  }
}

export const db = new ChatDexie();
