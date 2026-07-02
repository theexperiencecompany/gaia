import { v4 as uuidv4 } from "uuid";
import { chatApi } from "@/features/chat/api/chatApi";
import { db } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { useChatStore } from "@/stores/chatStore";
import { PENDING_KEY_PREFIX } from "@/stores/streamStore";
import { TurnSession } from "./turnSession";
import type { SendArgs } from "./types";

/** A resumed turn re-attaches to an existing stream — it never POSTs, so the
 *  send-time fields are inert placeholders. */
const buildResumeArgs = (
  conversationId: string,
  resumeStreamId: string,
): SendArgs => ({
  inputText: "",
  userMessage: {
    type: "user",
    response: "",
    date: new Date().toISOString(),
    message_id: "",
  },
  options: {
    fileData: [],
    selectedTool: null,
    toolCategory: null,
    selectedWorkflow: null,
    selectedCalendarEvent: null,
    optimisticUserId: null,
    replyToMessage: null,
    conversationId,
    isOnboardingDemo: false,
    resumeStreamId,
  },
});

/**
 * Registry of active turn sessions, keyed by conversation id (or a pending key
 * for a not-yet-created conversation). Each conversation streams independently
 * — concurrent turns across conversations are first-class — and each holds its
 * own FIFO queue of sends that arrived while its turn was open.
 */
class TurnManager {
  private sessions = new Map<string, TurnSession>();
  private queues = new Map<string, SendArgs[]>();
  /** Key of the in-flight new-conversation session, if any. */
  private pendingKey: string | null = null;
  /** Conversations with a resume discovery in flight (guards double-attach). */
  private resuming = new Set<string>();

  /** Resolve which session key a send targets. */
  resolveKey(conversationId: string | null): string {
    if (conversationId && conversationId !== "new") return conversationId;
    return this.pendingKey ?? `${PENDING_KEY_PREFIX}${uuidv4()}`;
  }

  /** True when a send for this key would be queued rather than started. */
  isTurnActive(conversationId: string | null): boolean {
    return this.sessions.has(this.resolveKey(conversationId));
  }

  /** Start a turn, or queue the send if this conversation is mid-turn. */
  send(args: SendArgs): void {
    const key = this.resolveKey(args.options.conversationId);

    if (this.sessions.has(key)) {
      const queue = this.queues.get(key) ?? [];
      queue.push(args);
      this.queues.set(key, queue);
      streamLog("lifecycle", "send:queued", {
        turnKey: key,
        conversationId: args.options.conversationId,
        detail: { queueLength: queue.length },
      });
      return;
    }

    this.startSession(key, args);
  }

  /**
   * Re-attach to a conversation's in-flight turn after a reload, if one
   * exists. The event log replays everything missed, so the resumed session
   * renders the turn exactly as if the page had been open the whole time.
   * No-op when the conversation is idle or already has a session.
   */
  async resumeIfActive(conversationId: string): Promise<void> {
    if (
      this.sessions.has(conversationId) ||
      this.resuming.has(conversationId)
    ) {
      return;
    }
    this.resuming.add(conversationId);
    try {
      const streamId = await chatApi.getActiveStream(conversationId);
      // Re-check: a send may have started a session during the fetch.
      if (!streamId || this.sessions.has(conversationId)) return;
      streamLog("lifecycle", "turn:resume", {
        turnKey: conversationId,
        conversationId,
        detail: { streamId },
      });
      this.startSession(
        conversationId,
        buildResumeArgs(conversationId, streamId),
      );
    } catch (error) {
      // Discovery is a recovery path — a failure must never break the page,
      // but it must be visible.
      streamLogError("lifecycle", "turn:resume-discovery-failed", {
        conversationId,
        detail: String(error),
      });
    } finally {
      this.resuming.delete(conversationId);
    }
  }

  /** Abort the active turn for a conversation. Returns true if one existed. */
  async stop(conversationId: string | null): Promise<boolean> {
    const key = this.resolveKey(conversationId);
    const session = this.sessions.get(key);
    if (!session) return false;
    // Stopping also discards this conversation's queued sends — the user is
    // halting the exchange, not asking for the next queued turn to fire.
    const queued = this.queues.get(key) ?? [];
    this.queues.delete(key);
    for (const args of queued) {
      if (args.options.optimisticUserId) {
        db.updateMessageStatus(args.options.optimisticUserId, "failed").catch(
          () => {
            // Optimistic bubble may be Zustand-only (new conversations).
          },
        );
      }
    }
    await session.abort();
    return true;
  }

  private startSession(key: string, args: SendArgs): void {
    const session = new TurnSession(key, args, {
      onEnd: (ended) => this.handleSessionEnd(ended),
      onRekey: (oldKey, newKey) => this.rekey(oldKey, newKey),
    });
    this.sessions.set(key, session);
    if (key.startsWith(PENDING_KEY_PREFIX)) this.pendingKey = key;
    void session.start();
  }

  private rekey(oldKey: string, newKey: string): void {
    const session = this.sessions.get(oldKey);
    if (session) {
      this.sessions.delete(oldKey);
      this.sessions.set(newKey, session);
    }
    const queue = this.queues.get(oldKey);
    if (queue) {
      this.queues.delete(oldKey);
      this.queues.set(newKey, queue);
    }
    if (this.pendingKey === oldKey) this.pendingKey = null;
  }

  private handleSessionEnd(session: TurnSession): void {
    const key = session.boundConversationId ?? session.key;
    this.sessions.delete(key);
    this.sessions.delete(session.key);
    if (this.pendingKey === session.key) this.pendingKey = null;
    this.dispatchQueued(key);
  }

  private dispatchQueued(key: string): void {
    const queue = this.queues.get(key);
    if (!queue || queue.length === 0) {
      this.queues.delete(key);
      return;
    }
    const next = queue.shift();
    if (queue.length === 0) this.queues.delete(key);
    if (!next) return;

    // The held message is now actually being sent: flip its optimistic bubble
    // from "queued" (grey) to "sending", and refresh its timestamp to dispatch
    // time — messages sort by createdAt, so a queued send must order after
    // everything that streamed in while it waited, not at its typing time.
    const dispatchedAt = new Date();
    if (next.options.optimisticUserId) {
      db.updateMessage(next.options.optimisticUserId, {
        status: "sending",
        createdAt: dispatchedAt,
      }).catch((error) => {
        console.error("Failed to flip queued message to sending:", error);
      });
    }

    // Sends queued against a new conversation resolve to the id it received.
    const conversationId =
      next.options.conversationId ??
      useChatStore.getState().activeConversationId;

    streamLog("lifecycle", "send:dequeued", {
      turnKey: key,
      conversationId,
    });
    this.send({
      ...next,
      userMessage: { ...next.userMessage, date: dispatchedAt.toISOString() },
      options: { ...next.options, conversationId },
    });
  }
}

export const turnManager = new TurnManager();
