import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import {
  applyStreamEvent,
  type ChatStreamEvent,
  createTurnAccumulator,
  parseChatStreamEvent,
  TOOL_CALLS_DATA_TOOL_NAME,
  type TurnAccumulator,
} from "@shared/chat";
import { chatApi } from "@/features/chat/api/chatApi";
import { relayDesktopToolRequest } from "@/features/chat/utils/desktopToolBridge";
import { readToolDataLoadingHints } from "@/features/chat/utils/loadingHints";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { db, type IConversation, type IMessage } from "@/lib/db/chatDb";
import { streamLog, streamLogError } from "@/lib/streamLogger";
import { toast } from "@/lib/toast";
import { syncSingleConversation } from "@/services/syncService";
import { useChatStore } from "@/stores/chatStore";
import { useComposerStore } from "@/stores/composerStore";
import { useStreamStore } from "@/stores/streamStore";
import { hasExecutorDelegation } from "./executorDelegation";
import {
  buildTurnMessageRecord,
  buildUserMessageRecord,
  type TurnMessageMeta,
} from "./messageRecord";
import type { SendArgs } from "./types";
import { isViewingConversation, markConversationUnread } from "./unread";

// Fallback for the rare case a delegated background executor never delivers its
// result message — clears the "awaiting executor result" UI so it can't stick.
const EXECUTOR_RESULT_TIMEOUT_MS = 120_000;

export interface TurnSessionCallbacks {
  /** Session finished (any terminal path). Manager dispatches the queue. */
  onEnd: (session: TurnSession) => void;
  /** New-conversation session learned its real conversation id. */
  onRekey: (oldKey: string, newKey: string) => void;
}

/**
 * Owns one assistant turn end to end: the SSE connection, the accumulator, the
 * pinned (conversation, message) identity, store/DB flushes, and every
 * lifecycle transition. All ids are captured here at start/init time, so a
 * navigation mid-stream can never reroute writes to another conversation.
 */
export class TurnSession {
  readonly key: string;
  readonly inputText: string;

  private readonly args: SendArgs;
  private readonly callbacks: TurnSessionCallbacks;
  private readonly controller = new AbortController();

  private conversationId: string | null;
  private botMessageId: string | null = null;
  private streamId: string | null = null;
  private botCreatedAt: Date | null = null;

  private acc: TurnAccumulator = createTurnAccumulator();
  private flushHandle: number | null = null;
  private closeHandled = false;
  private aborted = false;
  private readonly isNewConversation: boolean;

  constructor(key: string, args: SendArgs, callbacks: TurnSessionCallbacks) {
    this.key = key;
    this.args = args;
    this.callbacks = callbacks;
    this.conversationId = args.options.conversationId;
    this.isNewConversation = args.options.conversationId == null;
    this.inputText = args.inputText;
  }

  get isAborted(): boolean {
    return this.aborted;
  }

  /** The conversation this turn writes into (null until init for new convos). */
  get boundConversationId(): string | null {
    return this.conversationId;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  async start(): Promise<void> {
    const store = useStreamStore.getState();
    store.startSession(this.key, this.inputText);
    streamLog("lifecycle", "turn:start", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });

    trackEvent(ANALYTICS_EVENTS.CHAT_STARTED, {
      conversation_id: this.conversationId,
      is_new_conversation: this.isNewConversation,
    });

    try {
      await chatApi.fetchChatStream({
        inputText: this.inputText,
        history: this.buildHistory(),
        conversationId: this.conversationId,
        onMessage: (event) => this.handleSSEMessage(event),
        onClose: () => void this.close(),
        onError: (err) => this.fail(err),
        controller: this.controller,
        fileData: this.args.options.fileData,
        selectedTool: this.args.options.selectedTool,
        toolCategory: this.args.options.toolCategory,
        selectedWorkflow: this.args.options.selectedWorkflow,
        selectedCalendarEvent: this.args.options.selectedCalendarEvent,
        replyToMessage: this.args.options.replyToMessage,
        isOnboardingDemo: this.args.options.isOnboardingDemo,
      });
    } catch (error) {
      // fetchEventSource rejects on abort and on fatal errors; both paths have
      // already run their handlers (fail/abort). Anything else is a setup
      // failure that must still unwind the session.
      if (!this.closeHandled) {
        this.fail(error instanceof Error ? error : new Error(String(error)));
      }
    }
  }

  /** User pressed Stop: persist what streamed so far, then cancel everywhere. */
  async abort(): Promise<void> {
    if (this.closeHandled) return;
    this.closeHandled = true;
    this.aborted = true;
    streamLog("lifecycle", "turn:abort", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });

    useStreamStore.getState().beginPendingSave();
    try {
      this.cancelFlush();
      if (this.conversationId && this.botMessageId) {
        const record = this.buildRecord("sent");
        if (record) {
          useChatStore.getState().addOrUpdateMessage(record);
          await db.putMessage(record);
        }
      }
    } catch (error) {
      console.error("[TurnSession] Failed to persist on abort:", error);
    } finally {
      useStreamStore.getState().endPendingSave();
    }

    this.controller.abort();
    if (this.streamId) {
      cancelStreamOnBackend(this.streamId);
    }
    // Reconcile with the backend's cancel-save, which can land seconds later.
    if (this.conversationId) {
      void syncConversationWithRetry(this.conversationId);
    }
    this.end();
  }

  // ── SSE handling ───────────────────────────────────────────────────────────

  private async handleSSEMessage(
    event: EventSourceMessage,
  ): Promise<string | undefined> {
    if (this.aborted) return "Stream was aborted";
    if (!event.data) return undefined; // SSE comments dispatch empty events

    try {
      for (const parsed of parseChatStreamEvent(event.data)) {
        const haltError = await this.dispatchEvent(parsed);
        if (haltError !== undefined) return haltError;
      }
      return undefined;
    } catch (error) {
      streamLogError("sse", "event-handling-failed", {
        turnKey: this.key,
        conversationId: this.conversationId,
        detail: { error: String(error), data: event.data },
      });
      const message = error instanceof Error ? error.message : "Unknown error";
      return `Error processing stream data: ${message}`;
    }
  }

  private async dispatchEvent(
    event: ChatStreamEvent,
  ): Promise<string | undefined> {
    streamLog("sse", `event:${event.type}`, {
      turnKey: this.key,
      conversationId: this.conversationId,
    });

    switch (event.type) {
      case "done":
      case "keepalive":
      case "token_usage":
        return undefined;

      case "parse_error":
        streamLogError("sse", "malformed-frame", {
          turnKey: this.key,
          conversationId: this.conversationId,
          detail: event.raw,
        });
        toast.error("Received a malformed response from the server");
        return "Malformed stream frame";

      case "error":
        toast.error(event.error);
        return event.error;

      case "main_response_complete":
        this.handleMainResponseComplete();
        return undefined;

      case "progress":
        this.setSpinner(true);
        this.setLoadingText(event.message, {
          toolName: event.tool_name,
          toolCategory: event.tool_category,
        });
        return undefined;

      case "conversation_initialized":
        await this.handleConversationInitialized(event);
        return undefined;

      case "conversation_description":
        this.handleConversationDescription(event.description);
        return undefined;

      case "desktop_tool_request":
        // Fire-and-forget: the desktop executes while the stream stays live.
        void relayDesktopToolRequest(event.request);
        return undefined;

      case "response":
      case "tool_data":
      case "tool_output":
      case "reasoning":
      case "subagent_start":
      case "subagent_end":
      case "todo_progress":
      case "follow_up_actions":
      case "unknown":
        this.accumulate(event);
        return undefined;

      default: {
        const unhandled: never = event;
        return unhandled;
      }
    }
  }

  private accumulate(event: ChatStreamEvent): void {
    // Executor/tool activity after main_response_complete means the turn is
    // still working — re-arm the loading indicator it may have cleared.
    if (event.type !== "response" && event.type !== "follow_up_actions") {
      this.setSpinner(true);
    }

    if (event.type === "tool_data") {
      trackEvent(ANALYTICS_EVENTS.TOOL_USED, {
        tool_name: event.entry.tool_name,
        tool_category: event.entry.tool_category || "unknown",
        timestamp: event.entry.timestamp || new Date().toISOString(),
      });
      if (event.entry.tool_name === TOOL_CALLS_DATA_TOOL_NAME) {
        const hints = readToolDataLoadingHints(event.entry.data);
        if (hints) {
          const { message, ...toolInfo } = hints;
          this.setLoadingText(message, toolInfo);
        }
      }
    }

    if (
      event.type === "unknown" &&
      event.payload.status === "generating_image"
    ) {
      this.setLoadingText("Generating image...");
    }

    this.acc = applyStreamEvent(this.acc, event);
    streamLog("accumulator", `applied:${event.type}`, {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
    this.scheduleFlush();
  }

  // ── Conversation identity ──────────────────────────────────────────────────

  private async handleConversationInitialized(event: {
    conversation_id?: string;
    conversation_description?: string | null;
    user_message_id?: string;
    bot_message_id?: string;
    stream_id?: string;
  }): Promise<void> {
    if (event.stream_id) this.streamId = event.stream_id;

    if (event.conversation_id) {
      await this.bindNewConversation(
        event.conversation_id,
        event.conversation_description ?? null,
        event.user_message_id,
        event.bot_message_id,
      );
      return;
    }

    if (event.user_message_id && event.bot_message_id && this.conversationId) {
      await this.bindExistingConversationIds(
        event.user_message_id,
        event.bot_message_id,
      );
    }
  }

  private async bindNewConversation(
    conversationId: string,
    description: string | null,
    userMessageId?: string,
    botMessageId?: string,
  ): Promise<void> {
    this.conversationId = conversationId;
    streamLog("lifecycle", "turn:bound-new-conversation", {
      turnKey: this.key,
      conversationId,
    });

    const chatStore = useChatStore.getState();

    if (!chatStore.conversations.some((c) => c.id === conversationId)) {
      const finalDescription = description || "New Chat";
      const conversation: IConversation = {
        id: conversationId,
        title: finalDescription,
        description: finalDescription,
        starred: false,
        isSystemGenerated: false,
        createdAt: new Date(),
        updatedAt: new Date(),
      };
      try {
        await db.putConversation(conversation);
        trackEvent(ANALYTICS_EVENTS.CHAT_CONVERSATION_CREATED, {
          conversationId,
          source: "chat",
        });
      } catch (error) {
        console.error("Failed to save conversation to IndexedDB:", error);
      }
    }

    const userCreatedAt = this.args.userMessage.date
      ? new Date(this.args.userMessage.date)
      : new Date();
    // Bot message sorts directly after the user message.
    this.botCreatedAt = new Date(userCreatedAt.getTime() + 1);

    const userRecord = userMessageId
      ? buildUserMessageRecord(
          userMessageId,
          conversationId,
          this.args.userMessage,
          userCreatedAt,
        )
      : null;

    let botRecord: IMessage | null = null;
    if (botMessageId) {
      this.botMessageId = botMessageId;
      botRecord = this.buildRecord("sending");
    }

    // Store updates are synchronous so subsequent events render immediately;
    // IndexedDB persistence follows in the background.
    if (userRecord) chatStore.addOrUpdateMessage(userRecord);
    if (botRecord) chatStore.addOrUpdateMessage(botRecord);
    chatStore.clearOptimisticMessage();

    // Only sync the URL when already on a conversation route (not onboarding).
    if (/^\/c(\/|$)/.test(globalThis.location.pathname)) {
      globalThis.history.replaceState({}, "", `/c/${conversationId}`);
    }
    chatStore.setActiveConversationId(conversationId);

    this.callbacks.onRekey(this.key, conversationId);
    useStreamStore.getState().rekeySession(this.key, conversationId);

    db.persistMessagePair(userRecord, botRecord).catch((error) => {
      console.error("Failed to persist message pair:", error);
    });
  }

  private async bindExistingConversationIds(
    userMessageId: string,
    botMessageId: string,
  ): Promise<void> {
    if (!this.conversationId) return;
    this.botMessageId = botMessageId;

    const userCreatedAt = this.args.userMessage.date
      ? new Date(this.args.userMessage.date)
      : new Date();
    this.botCreatedAt = new Date(userCreatedAt.getTime() + 1);

    if (this.args.options.optimisticUserId) {
      try {
        await db.replaceOptimisticMessage(
          this.args.options.optimisticUserId,
          userMessageId,
        );
        await db.updateMessageStatus(userMessageId, "sent");
      } catch (error) {
        console.error("Failed to replace optimistic message:", error);
      }
    }

    const botRecord = this.buildRecord("sending");
    if (botRecord) {
      useChatStore.getState().addOrUpdateMessage(botRecord);
      try {
        await db.putMessage(botRecord);
      } catch (error) {
        console.error("Failed to persist initial bot message:", error);
      }
    }
  }

  private handleConversationDescription(description: string): void {
    // Late title generation only applies to conversations this turn created.
    if (!this.isNewConversation || !this.conversationId) return;
    db.updateConversationFields(this.conversationId, {
      description,
      title: description,
    }).catch((error) => {
      console.error("Failed to update conversation description:", error);
    });
  }

  // ── Loading / composer UI ──────────────────────────────────────────────────

  private handleMainResponseComplete(): void {
    const store = useStreamStore.getState();
    // The comms agent acked — unlock the composer so the user can queue.
    store.updateSession(this.key, { composerLocked: false });

    // A delegated turn isn't done: the executor streams over this same SSE
    // moments later. Dropping the spinner here would leave a dead frame until
    // the first executor event re-arms it.
    if (hasExecutorDelegation(this.acc.toolData)) return;

    this.setSpinner(false);
    store.resetSessionLoadingText(this.key);
    this.scheduleFlush();
  }

  private setSpinner(active: boolean): void {
    const store = useStreamStore.getState();
    const session = store.sessions[this.key];
    if (!session || session.spinnerActive === active) return;
    store.updateSession(this.key, {
      spinnerActive: active,
      phase: "streaming",
    });
  }

  private setLoadingText(
    text: string,
    toolInfo?: {
      toolName?: string;
      toolCategory?: string;
      integrationName?: string;
      iconUrl?: string;
      showCategory?: boolean;
    },
  ): void {
    useStreamStore.getState().setSessionLoadingText(this.key, text, toolInfo);
  }

  // ── Store / DB flushes ─────────────────────────────────────────────────────

  private buildRecord(
    status: "sending" | "sent",
  ): ReturnType<typeof buildTurnMessageRecord> | null {
    if (!this.conversationId || !this.botMessageId) return null;
    const meta: TurnMessageMeta = {
      conversationId: this.conversationId,
      botMessageId: this.botMessageId,
      createdAt: this.botCreatedAt ?? new Date(),
      options: this.args.options,
    };
    return buildTurnMessageRecord(meta, this.acc, status);
  }

  /** Batch accumulator flushes to one store write per animation frame. */
  private scheduleFlush(): void {
    if (this.flushHandle !== null) return;
    this.flushHandle = requestAnimationFrame(() => {
      this.flushHandle = null;
      this.flush();
    });
  }

  private cancelFlush(): void {
    if (this.flushHandle === null) return;
    cancelAnimationFrame(this.flushHandle);
    this.flushHandle = null;
  }

  private flush(): void {
    const record = this.buildRecord("sending");
    if (!record) return;
    useChatStore.getState().updateMessageInPlace(record);
    streamLog("store", "flush", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
  }

  // ── Terminal paths ─────────────────────────────────────────────────────────

  private async close(): Promise<void> {
    if (this.closeHandled) return;
    this.closeHandled = true;
    this.cancelFlush();
    streamLog("lifecycle", "turn:close", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });

    try {
      if (!this.conversationId || !this.botMessageId) {
        this.recoverGhostTurn();
        return;
      }

      const record = this.buildRecord("sent");
      if (record) {
        useChatStore.getState().addOrUpdateMessage(record);
        try {
          await db.putMessage(record);
          await db.updateConversationFields(this.conversationId, {
            updatedAt: new Date(),
          });
        } catch (error) {
          console.error("Failed to persist final message:", error);
        }
      }

      // A completed turn in a conversation the user isn't viewing surfaces as
      // unread in the sidebar (cleared by ChatPage's mark-as-read on open).
      // View detection uses location.pathname, not the chat store's active id —
      // the pathname changes synchronously with navigation, while the store
      // only updates in a ChatPage effect and can lag a close that races it.
      if (
        !isViewingConversation(this.conversationId) &&
        this.acc.responseText.length > 0
      ) {
        markConversationUnread(this.conversationId);
      }

      if (hasExecutorDelegation(this.acc.toolData)) {
        this.enterAwaitingExecutor();
        return;
      }

      this.end();
    } catch (error) {
      console.error("Error handling stream close:", error);
      this.end();
    }
  }

  /** SSE is done but a background executor still owes its result message. */
  private enterAwaitingExecutor(): void {
    const key = this.conversationId ?? this.key;
    streamLog("lifecycle", "turn:awaiting-executor", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
    useStreamStore.getState().updateSession(key, {
      phase: "awaiting_executor",
      spinnerActive: false,
      composerLocked: false,
    });
    // The session's transport work is over — release it so new sends in this
    // conversation start immediately. The awaiting UI state is ended by the
    // result message (useBgMessageWebSocket), executor cancel, or this timeout.
    setTimeout(() => {
      const state = useStreamStore.getState();
      if (state.sessions[key]?.phase === "awaiting_executor") {
        state.endSession(key);
      }
    }, EXECUTOR_RESULT_TIMEOUT_MS);
    this.callbacks.onEnd(this);
  }

  private fail(error: Error): void {
    if (this.closeHandled) return;
    this.closeHandled = true;
    this.cancelFlush();
    streamLogError("lifecycle", "turn:error", {
      turnKey: this.key,
      conversationId: this.conversationId,
      detail: { name: error.name, message: error.message },
    });

    if (error.name !== "AbortError") {
      toast.error(
        error.message || "An error occurred while processing your message",
      );
      // Give the user their prompt back to retry.
      useComposerStore.getState().setInputText(this.inputText);
    }

    this.markUserMessageFailed();
    useChatStore.getState().clearOptimisticMessage();
    this.end();
  }

  /**
   * The stream closed without ever delivering its identity frame. For an
   * existing conversation this is the backend's pub/sub init race (the turn IS
   * persisted server-side — the frame was published before the SSE subscriber
   * attached, and pub/sub has no replay): reconcile from the server, which
   * inserts the real message pair and sweeps the orphaned optimistic bubble.
   * A new conversation has nothing server-side to reconcile — surface failure.
   */
  private recoverGhostTurn(): void {
    streamLogError("lifecycle", "turn:ghost-close", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
    if (this.conversationId) {
      const conversationId = this.conversationId;
      this.end();
      void syncSingleConversation(conversationId);
      return;
    }
    this.markUserMessageFailed();
    this.end();
  }

  /** The turn never bound backend ids or errored — flip the optimistic user
   *  bubble to failed so the message doesn't sit "sending" forever. */
  private markUserMessageFailed(): void {
    const optimisticId = this.args.options.optimisticUserId;
    if (!optimisticId || this.botMessageId) return;
    db.updateMessageStatus(optimisticId, "failed").catch(() => {
      // New-conversation sends are Zustand-only — nothing persisted to flip.
    });
  }

  private end(): void {
    useStreamStore.getState().endSession(this.conversationId ?? this.key);
    // Also clear under the original pending key if init never rekeyed it.
    if (this.conversationId && this.conversationId !== this.key) {
      useStreamStore.getState().endSession(this.key);
    }
    streamLog("lifecycle", "turn:end", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
    this.callbacks.onEnd(this);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  /** Conversation history for the request body, excluding this turn's own
   *  optimistic user message (appended explicitly, exactly once). */
  private buildHistory(): { role: "user" | "assistant"; content: string }[] {
    const optimisticId = this.args.options.optimisticUserId;
    const stored = this.conversationId
      ? (useChatStore.getState().messagesByConversation[this.conversationId] ??
        [])
      : [];

    const history = stored
      .filter(
        (message) =>
          message.role !== "system" &&
          message.id !== optimisticId &&
          message.content.trim().length > 0,
      )
      .map((message) => ({
        role: message.role as "user" | "assistant",
        content: message.content,
      }));

    if (this.args.userMessage.response.trim().length > 0) {
      history.push({ role: "user", content: this.args.userMessage.response });
    }
    return history;
  }
}

/** Notify the backend to stop generating. Fire-and-forget. */
async function cancelStreamOnBackend(streamId: string): Promise<void> {
  try {
    await fetch(
      `${process.env.NEXT_PUBLIC_API_BASE_URL}cancel-stream/${streamId}`,
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
      },
    );
  } catch (error) {
    // The stream may already be done — nothing to recover.
    console.debug("Cancel stream request failed:", error);
  }
}

/**
 * After a user-initiated stop, the backend's finally-block save can take a few
 * seconds under load. Retry the sync with backoff so IndexedDB converges on the
 * complete persisted response.
 */
async function syncConversationWithRetry(
  conversationId: string,
  maxRetries = 3,
  baseDelayMs = 3000,
): Promise<void> {
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    const delay = baseDelayMs * 2 ** attempt;
    await new Promise((resolve) => setTimeout(resolve, delay));
    try {
      await syncSingleConversation(conversationId);
      return;
    } catch (error) {
      console.debug(
        `[syncConversationWithRetry] Attempt ${attempt + 1}/${maxRetries} failed:`,
        error,
      );
    }
  }
  console.warn(
    `[syncConversationWithRetry] All ${maxRetries} attempts failed for ${conversationId}`,
  );
}
