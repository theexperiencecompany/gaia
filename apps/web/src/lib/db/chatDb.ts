import type { ScreenItem } from "@shared/conversation";
import Dexie, { type IndexableType, type Table } from "dexie";
import { EventEmitter } from "events";
import type { SystemPurpose } from "@/features/chat/api/chatApi";
import type { LocalSend } from "@/features/chat/live/liveConversationStore";
import type { ArtifactData } from "@/types/features/toolDataTypes";

export interface IConversation {
  id: string;
  title: string;
  description?: string;
  userId?: string;
  starred?: boolean;
  isSystemGenerated?: boolean;
  systemPurpose?: SystemPurpose | null;
  isUnread?: boolean;
  source?: string; // ConversationSource from backend (web, telegram, discord, etc.)
  // Live work here awaits the user's approval: the sidebar lists the
  // conversation for its card, and the row lights the approval dot.
  awaitingApproval: boolean;
  todoId?: string | null;
  // False when the server's conversation list never shows it (a todo's chat, a bot DM).
  listed?: boolean;
  // Conversation-level artifact registry: the single source of truth for this
  // conversation's agent-written files. Messages store path references that
  // resolve against this (see FileArtifactSection / chatStore).
  artifacts?: ArtifactData[];
  createdAt: Date;
  updatedAt: Date;
}

/** A conversation's screen and head as this device last saw them, where an older page starts, and the sends it made into it. */
export interface IConversationLog {
  conversationId: string;
  items: ScreenItem[];
  head: number;
  olderBefore: number | null;
  sends: Record<string, LocalSend>;
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
  public conversationLogs!: Table<IConversationLog, string>;

  /**
   * Whether IndexedDB persistence is usable this session — iOS Safari refuses
   * to open it under private browsing, storage pressure, or a long-standing
   * WebKit bug (`UnknownError: Unable to open database file on disk`). Probed
   * once and cached (see `run`); also flips to `false` when a later operation
   * rejects, so one failure degrades the whole session instead of leaking uncaught rejections.
   */
  private usable: Promise<boolean> | null = null;

  constructor() {
    super("ChatDatabase");

    this.version(1).stores({
      conversations: "id, updatedAt, createdAt",
      messages: "id, conversationId, createdAt",
    });
    this.version(3).stores({});
    // v4: the conversation event stream's log, so a reload shows it before the stream reconnects.
    this.version(4).stores({ conversationLogs: "conversationId" });
    // v5: a conversation is its log alone. Cached messages go, and logs saved without a page
    // cursor are dropped so each conversation refetches its newest page once.
    this.version(5)
      .stores({ messages: null })
      .upgrade((tx) => tx.table("conversationLogs").clear());
    // v6: a conversation is a copy of the server's screen; saved logs are dropped and refetched.
    this.version(6)
      .stores({})
      .upgrade((tx) => tx.table("conversationLogs").clear());
    // v7: every row carries awaitingApproval; rows cached without it are dropped and refetched.
    this.version(7)
      .stores({})
      .upgrade((tx) => tx.table("conversations").clear());

    this.conversations = this.table("conversations");
    this.conversationLogs = this.table("conversationLogs");
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
   * Run a Dexie operation, degrading to `fallback` when IndexedDB is
   * unavailable — the single guard so callers await a resolved promise
   * instead of an uncaught rejection on iOS Safari. A write/transaction
   * failure after a successful open degrades the same way, latching the
   * session unavailable. Event emissions live outside this gate, so the in-memory store still updates live.
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

  public getConversationLog(
    conversationId: string,
  ): Promise<IConversationLog | undefined> {
    return this.run(undefined, () => this.conversationLogs.get(conversationId));
  }

  public async putConversationLog(log: IConversationLog): Promise<void> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() => this.conversationLogs.put(log)),
    );
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

  public async deleteConversationAndLog(conversationId: string): Promise<void> {
    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction(
          "rw",
          [this.conversations, this.conversationLogs],
          async () => {
            await this.conversationLogs.delete(conversationId);
            await this.conversations.delete(conversationId);
          },
        ),
      ),
    );
  }

  /**
   * Bulk delete multiple conversations and their logs.
   * Used by sync service to clean up deleted conversations.
   */
  public async deleteConversationsAndLogsBulk(
    conversationIds: string[],
  ): Promise<void> {
    if (conversationIds.length === 0) return;

    await this.run(undefined, () =>
      messageQueue.enqueue(() =>
        (this as Dexie).transaction(
          "rw",
          [this.conversations, this.conversationLogs],
          async () => {
            await this.conversationLogs.bulkDelete(conversationIds);
            // Delete the conversations themselves
            await this.conversations.bulkDelete(conversationIds);
          },
        ),
      ),
    );

    // Emit event for store synchronization
    dbEventEmitter.emitConversationsDeletedBulk(conversationIds);
  }

  public async clearAll(): Promise<void> {
    const conversationIds = await this.run<IndexableType[]>([], () =>
      messageQueue.enqueue(async () => {
        const ids = await this.conversations.toCollection().primaryKeys();
        await (this as Dexie).transaction(
          "rw",
          [this.conversations, this.conversationLogs],
          async () => {
            await this.conversationLogs.clear();
            await this.conversations.clear();
          },
        );
        return ids;
      }),
    );

    // Emit event for store synchronization
    dbEventEmitter.emitConversationsDeletedBulk(conversationIds as string[]);
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
