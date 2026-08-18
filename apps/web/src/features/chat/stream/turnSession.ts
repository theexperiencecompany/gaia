import type { EventSourceMessage } from "@microsoft/fetch-event-source";
import {
  APPROVAL_REQUEST_TOOL_NAME,
  type ApprovalRequestData,
  applyStreamEvent,
  type ChatStreamEvent,
  createTurnAccumulator,
  parseChatStreamEvent,
  type TurnAccumulator,
} from "@shared/chat";
import {
  chatApi,
  DuplicateTurnError,
  RateLimitError,
} from "@/features/chat/api/chatApi";
import { relayDesktopToolRequest } from "@/features/chat/utils/desktopToolBridge";
import { loadingLabelForEvent } from "@/features/chat/utils/loadingHints";
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
  resolveTurnOutcome,
  type TurnMessageMeta,
} from "./messageRecord";
import { StallWatchdog } from "./stallWatchdog";
import type { SendArgs } from "./types";
import { isViewingConversation, markConversationUnread } from "./unread";

// Fallback for the rare case a delegated background executor never delivers its
// result message — clears the "awaiting executor result" UI so it can't stick.
const EXECUTOR_RESULT_TIMEOUT_MS = 120_000;

// Last-resort self-heal for a run paused on an approval whose resumed result
// message never arrives (denied path with no notification, dropped bg websocket,
// backend error). It waits on a HUMAN for up to the ~6h server approval window,
// so this must fire well AFTER that window — long enough that the decision (or the
// server-side expiry) and its resumed result should already have landed. Only
// then, if the session is still stranded, tear it down. 8h leaves a safe margin.
const APPROVAL_STRANDED_TIMEOUT_MS = 8 * 60 * 60 * 1000;

// Cadence for caching the in-flight turn to IndexedDB during streaming, so a
// reload's first paint shows the partial turn instead of an empty bubble. A
// cache of tape-derived state only: the event-log replay overwrites it on
// resume, so staleness (≤ one interval) never affects correctness.
const STREAM_PERSIST_INTERVAL_MS = 500;

// How long a live stream may go completely silent before the turn is declared
// dead. The backend emits a keepalive whenever its event log is idle (see
// StreamManager.subscribe_stream), so silence this long means the connection or
// the background task is gone, not that the model is thinking. Comfortably
// above the server's keepalive cadence so a slow tool call can never trip it.
const STREAM_STALL_TIMEOUT_MS = 90_000;

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
  private lastPartialPersistAt = 0;
  private closeHandled = false;
  /** Approval ids currently pending a user decision. The turn is "awaiting
   *  approval" while non-empty; a set (not a bool) so multiple gated tools
   *  resolve independently without prematurely clearing the state. */
  private readonly pendingApprovalIds = new Set<string>();
  private aborted = false;
  private readonly isNewConversation: boolean;
  /** The comms agent delivered its answer. A connection that drops after this
   *  lost only the executor tail, so the turn is complete, not truncated. */
  private sawMainResponseComplete = false;
  private readonly stallWatchdog = new StallWatchdog(
    STREAM_STALL_TIMEOUT_MS,
    () => this.handleStall(),
  );

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

  /** The store key the live session lives under. `bindNewConversation()` rekeys
   *  it from the pending `this.key` to the real conversation id, so every store
   *  read/write must resolve through here to survive that move. */
  private get sessionKey(): string {
    return this.conversationId ?? this.key;
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  async start(): Promise<void> {
    const store = useStreamStore.getState();
    store.startSession(this.key, this.inputText);
    streamLog("lifecycle", "turn:start", {
      turnKey: this.key,
      conversationId: this.conversationId,
      // Carried so an on-disk recording is self-describing: the reader can see
      // which prompt produced the frames that follow.
      detail: { prompt: this.inputText },
    });

    trackEvent(ANALYTICS_EVENTS.CHAT_STARTED, {
      conversation_id: this.conversationId,
      is_new_conversation: this.isNewConversation,
    });

    this.stallWatchdog.arm();
    try {
      if (this.args.options.resumeStreamId) {
        await this.attachToStream(this.args.options.resumeStreamId);
        return;
      }
      await chatApi.fetchChatStream({
        inputText: this.inputText,
        history: this.buildHistory(),
        conversationId: this.conversationId,
        // The optimistic id doubles as the idempotency key: it's minted once
        // per SEND and survives queueing/dispatch, so a retried POST of the
        // same send is rejected server-side instead of duplicating the turn.
        turnId: this.args.options.optimisticUserId,
        onMessage: (event) => this.handleSSEMessage(event),
        onClose: (sawDone) => void this.close(sawDone),
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

  /**
   * Re-attach to an already-running turn's event log (reload-mid-stream).
   * The log replays from the beginning, so the same event pipeline rebuilds
   * the turn — identity frame binds ids, the accumulator rebuilds content,
   * and the turn keeps streaming live from where the backend actually is.
   */
  private async attachToStream(streamId: string): Promise<void> {
    this.streamId = streamId;
    await chatApi.subscribeToExecutorStream(
      streamId,
      (event) => {
        void this.handleSSEMessage(event).then((haltError) => {
          if (haltError && !this.closeHandled) {
            this.fail(new Error(haltError));
            this.controller.abort();
          }
        });
      },
      (sawDone) => void this.close(sawDone),
      (err) => this.fail(err),
      this.controller.signal,
    );
  }

  /** The stream went silent past even the server's keepalive cadence. */
  private handleStall(): void {
    streamLogError("sse", "stream-stalled", {
      turnKey: this.key,
      conversationId: this.conversationId,
      detail: { idleMs: STREAM_STALL_TIMEOUT_MS },
    });
    // Fail BEFORE aborting: aborting first lets the transport's AbortError
    // reach fail() and claim the turn, which suppresses the user-facing toast.
    this.fail(
      new Error("The connection went quiet, so this response was stopped."),
    );
    this.controller.abort();
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

    this.stallWatchdog.disarm();
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
    // Any frame — keepalives included — proves the connection is still alive.
    this.stallWatchdog.kick();
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
        // No toast here — fail() owns the user-facing message for every
        // failure path, and toasting both places double-reports one error.
        return event.error;

      case "model_fallback":
        // Primary model failed and the backup answered. Reassure the user the
        // result is complete; do NOT return an error string (the turn is fine).
        toast.info("Answered with backup model", {
          description:
            "The primary model was unavailable, so a backup handled your request. Your answer is complete.",
        });
        return undefined;

      case "main_response_complete":
        this.handleMainResponseComplete();
        return undefined;

      case "progress": {
        this.setSpinner(true);
        this.applyLoadingLabel(event);
        return undefined;
      }

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
      this.applyLoadingLabel(event);
      if (event.entry.tool_name === APPROVAL_REQUEST_TOOL_NAME) {
        this.handleApprovalFrame(
          event.entry.data as ApprovalRequestData | null,
        );
      }
    }

    if (event.type === "unknown") this.applyLoadingLabel(event);

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
    user_message_content?: string;
    bot_message_id?: string;
    stream_id?: string;
  }): Promise<void> {
    // The backend replays the identity frame for late subscribers, so it can
    // arrive twice (replay + live copy) — bind exactly once.
    if (this.botMessageId) return;
    if (event.stream_id) this.streamId = event.stream_id;

    // A resumed session's local userMessage is an empty stub — adopt the text
    // from the replayed frame so the record can be rebuilt from the log alone.
    if (event.user_message_content && !this.args.userMessage.response) {
      this.args.userMessage = {
        ...this.args.userMessage,
        response: event.user_message_content,
      };
    }

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

    // Single identity: the client's send id IS the server's user_message_id,
    // so the optimistic record already carries the final key — confirm it in
    // place. IndexedDB is the durability check (the Zustand store is per-tab
    // and must not gate a shared-DB write): only when the record is missing
    // there (a reload beat the fire-and-forget write) is it rebuilt from the
    // replayed identity frame — and only if the frame gave it content to
    // show; a file-only turn is unreconstructable from the log and arrives
    // via sync instead.
    try {
      const confirmed = await db.updateMessage(userMessageId, {
        status: "sent",
        optimistic: false,
      });
      if (!confirmed && this.args.userMessage.response) {
        const userRecord = buildUserMessageRecord(
          userMessageId,
          this.conversationId,
          this.args.userMessage,
          userCreatedAt,
        );
        useChatStore.getState().addOrUpdateMessage(userRecord);
        await db.putMessage(userRecord);
      }
    } catch (error) {
      console.error("Failed to confirm user message delivery:", error);
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
    this.sawMainResponseComplete = true;
    const store = useStreamStore.getState();
    // The comms agent acked — unlock the composer so the user can queue.
    store.updateSession(this.sessionKey, { composerLocked: false });

    // A delegated turn isn't done: the executor streams over this same SSE
    // moments later. Dropping the spinner here would leave a dead frame until
    // the first executor event re-arms it.
    if (hasExecutorDelegation(this.acc.toolData)) return;

    this.setSpinner(false);
    store.resetSessionLoadingText(this.sessionKey);
    this.scheduleFlush();
  }

  private setSpinner(active: boolean): void {
    const store = useStreamStore.getState();
    const session = store.sessions[this.sessionKey];
    if (!session || session.spinnerActive === active) return;
    store.updateSession(this.sessionKey, {
      spinnerActive: active,
      phase: "streaming",
    });
  }

  private setAwaitingApproval(active: boolean): void {
    const store = useStreamStore.getState();
    const session = store.sessions[this.sessionKey];
    if (!session || session.awaitingApproval === active) return;
    store.updateSession(this.sessionKey, { awaitingApproval: active });
  }

  /** Drive the awaiting-approval UI from an approval_request tool frame. */
  private handleApprovalFrame(approval: ApprovalRequestData | null): void {
    const approvalId = approval?.approval_id;
    if (!approval || !approvalId) return;

    if (approval.status !== "pending") {
      // Resolved (approved / denied / timeout): clear this approval and only
      // leave the awaiting state if another gated tool is still open.
      this.pendingApprovalIds.delete(approvalId);
      this.setAwaitingApproval(this.pendingApprovalIds.size > 0);
      return;
    }

    // The agent is idle waiting on the user. Swap the streaming spinner for the
    // distinct "awaiting approval" indicator (any later event re-arms the
    // spinner). Surface unread when the user isn't looking so they know a
    // decision is waiting.
    this.pendingApprovalIds.add(approvalId);
    this.setSpinner(false);
    this.setAwaitingApproval(true);
    if (this.conversationId && !isViewingConversation(this.conversationId)) {
      markConversationUnread(this.conversationId);
    }
  }

  /** Set the loading label if this event carries one. Shared with the executor
   *  stream so both paths label a run the same way. */
  private applyLoadingLabel(event: ChatStreamEvent): void {
    const label = loadingLabelForEvent(event);
    if (!label) return;
    useStreamStore
      .getState()
      .setSessionLoadingText(this.sessionKey, label.text, label.toolInfo);
  }

  // ── Store / DB flushes ─────────────────────────────────────────────────────

  private buildRecord(
    status: IMessage["status"],
    error: string | null = null,
  ): ReturnType<typeof buildTurnMessageRecord> | null {
    if (!this.conversationId || !this.botMessageId) return null;
    const meta: TurnMessageMeta = {
      conversationId: this.conversationId,
      botMessageId: this.botMessageId,
      createdAt: this.botCreatedAt ?? new Date(),
      options: this.args.options,
    };
    return buildTurnMessageRecord(meta, this.acc, status, error);
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
    this.persistPartialTurn(record);
    streamLog("store", "flush", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
  }

  /** Throttled IndexedDB cache of the streaming record (see
   *  STREAM_PERSIST_INTERVAL_MS). Store flushes stay per-frame; only the
   *  durable copy is rate-limited. */
  private persistPartialTurn(record: IMessage): void {
    const now = Date.now();
    if (now - this.lastPartialPersistAt < STREAM_PERSIST_INTERVAL_MS) return;
    this.lastPartialPersistAt = now;
    db.putMessage(record).catch((error) => {
      console.error("Failed to cache streaming turn:", error);
    });
  }

  // ── Terminal paths ─────────────────────────────────────────────────────────

  private async close(sawDone: boolean): Promise<void> {
    if (this.closeHandled) return;
    this.closeHandled = true;
    this.cancelFlush();
    this.stallWatchdog.disarm();
    streamLog("lifecycle", "turn:close", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });

    try {
      if (!this.conversationId || !this.botMessageId) {
        this.recoverGhostTurn();
        return;
      }

      // A connection that ended without [DONE] and without the comms answer is
      // a truncated turn — persisting it as "sent" makes a dead stream
      // indistinguishable from a finished one.
      const outcome = resolveTurnOutcome(
        sawDone || this.sawMainResponseComplete,
      );
      if (outcome.status === "failed") {
        streamLogError("lifecycle", "turn:truncated", {
          turnKey: this.key,
          conversationId: this.conversationId,
        });
      }

      const record = this.buildRecord(outcome.status, outcome.error);
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

      // Only a turn that actually completed can be waiting on an executor tail.
      // The normal delegation flow acks (main_response_complete) long before the
      // executor streams, so a truncated turn here died before the hand-off was
      // confirmed — park it as failed and retryable rather than spinning on a
      // result that may never come.
      if (
        outcome.status === "sent" &&
        hasExecutorDelegation(this.acc.toolData)
      ) {
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
    const key = this.sessionKey;
    streamLog("lifecycle", "turn:awaiting-executor", {
      turnKey: this.key,
      conversationId: this.conversationId,
    });
    const store = useStreamStore.getState();
    // A paused-on-approval turn also closes its stream and lands here; clearing
    // the flag would swap "Waiting for your approval" for a generic executor
    // spinner for the whole (user-blocked) wait. Preserve it.
    const wasAwaitingApproval = store.sessions[key]?.awaitingApproval ?? false;
    store.updateSession(key, {
      phase: "awaiting_executor",
      spinnerActive: false,
      awaitingApproval: wasAwaitingApproval,
      composerLocked: false,
    });
    // The session's transport work is over — release it so new sends in this
    // conversation start immediately. The awaiting UI state is ended by the
    // result message (useBgMessageWebSocket), executor cancel, or this timeout.
    //
    // A run paused on an approval waits on a HUMAN, not a late executor: its window
    // is hours, so it gets a much longer horizon than a normal executor tail — the
    // short timeout must never drop the "Waiting for your approval" indicator mid
    // -wait. But it still gets ONE: if the resumed result never arrives (dropped bg
    // message, backend error), the session would otherwise stick forever.
    const timeoutMs = wasAwaitingApproval
      ? APPROVAL_STRANDED_TIMEOUT_MS
      : EXECUTOR_RESULT_TIMEOUT_MS;
    setTimeout(() => {
      const state = useStreamStore.getState();
      const session = state.sessions[key];
      if (session?.phase === "awaiting_executor") {
        state.endSession(key);
      }
    }, timeoutMs);
    this.callbacks.onEnd(this);
  }

  private fail(error: Error): void {
    if (this.closeHandled) return;
    this.closeHandled = true;
    this.cancelFlush();
    this.stallWatchdog.disarm();
    streamLogError("lifecycle", "turn:error", {
      turnKey: this.key,
      conversationId: this.conversationId,
      detail: { name: error.name, message: error.message },
    });

    // A duplicate-turn rejection means the ORIGINAL send is being processed —
    // this attempt must vanish quietly and the conversation reconcile from the
    // server, not surface as a failure.
    if (error instanceof DuplicateTurnError) {
      const conversationId = this.conversationId;
      useChatStore.getState().clearOptimisticMessage();
      this.end();
      if (conversationId) void syncSingleConversation(conversationId);
      return;
    }

    const reason =
      error.message || "An error occurred while processing your message";

    if (error.name !== "AbortError") {
      // A usage-wall rejection already showed the rate-limit upsell toast at
      // the stream layer — a second generic toast would bury it.
      if (!(error instanceof RateLimitError)) {
        toast.error(reason);
      }
      // Give the user their prompt back to retry.
      useComposerStore.getState().setInputText(this.inputText);
    }

    // Content already flushed with status "sending" must still land in a
    // terminal state — mirror abort()'s finalization, with "failed" status.
    // The reason rides ON the record: the toast is transient, so without it a
    // reload shows an empty bubble and the failure disappears entirely.
    if (this.conversationId && this.botMessageId) {
      const record = this.buildRecord("failed", reason);
      if (record) {
        useChatStore.getState().addOrUpdateMessage(record);
        db.putMessage(record).catch((persistError) => {
          console.error(
            "[TurnSession] Failed to persist on fail:",
            persistError,
          );
        });
      }
    }

    this.markUserMessageFailed();
    // A turn that never learned its conversation id persisted nothing, anywhere:
    // the optimistic bubble is the only record of what the user sent, so clearing
    // it erases the message from the thread and leaves just a fading toast. Mark
    // it undelivered instead. Once ids exist the real rows are in IndexedDB and
    // the optimistic copy is a duplicate that must go.
    if (this.conversationId) {
      useChatStore.getState().clearOptimisticMessage();
    } else {
      useChatStore.getState().markOptimisticMessageFailed();
    }
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
    useChatStore.getState().markOptimisticMessageFailed();
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
