/**
 * Shared streaming chat handler for all bot platforms.
 *
 * Each bot provides thin callbacks:
 *
 *   editMessage    - Update the "Thinking..." placeholder, and only it
 *   sendNewMessage - Post a message, returning its own edit (and delete) handle
 *   onAuthError    - Show auth URL when user isn't linked
 *   onGenericError - Show formatted error message in the placeholder
 *
 * The shared function runs the turn through the delivery state machine
 * (bubble-delivery.ts), throttles live previews to the platform's edit rate,
 * and routes errors through formatBotError.
 *
 * Usage in a bot command file:
 *   import { handleStreamingChat, STREAMING_DEFAULTS } from "@gaia/shared";
 *
 *   await handleStreamingChat(gaia, request, editMessage, onAuth, onErr,
 *     STREAMING_DEFAULTS.discord);
 */
import type { AnalyticsContext } from "../../analytics";
import type { ApprovalRequestData } from "../../chat";
import { formatApprovalAge } from "../../chat/approvals";
import type { GaiaClient } from "../api";
import { BOT_STREAM_ERROR, type ReactionHandler } from "../api/chat-stream";
import {
  createDeliveryFailureReporter,
  DELIVERY_FAILURE_KIND,
  describeErrorForAlert,
  isLostReply,
} from "../delivery-failures";
import type { ChatRequest, PlatformName } from "../types";
import {
  initialDeliveryState,
  PLACEHOLDER_SLOT,
  stepDelivery,
} from "./bubble-delivery";
import type {
  DeliveryConfig,
  DeliveryEvent,
  DeliveryOp,
  MessageSlot,
} from "./bubble-delivery.types";
import { BUBBLE_PAUSE_MS } from "./bubbles";
import { isMessageGoneError, retryAfterMs } from "./delivery-errors";
import { BOT_FAILURE_REASON, recordBotFailure } from "./failure-reasons";
import {
  buildPlanRequiredMessage,
  formatBotError,
  PLATFORM_MARKDOWN,
} from "./formatters";
import {
  createBotLogger,
  hashLogIdentifier,
  sanitizeErrorForLog,
} from "./logger";
import {
  REACTION_OUTCOME,
  REACTION_SURFACE,
  type ReactionOutcome,
  reactionDeliveredProperties,
} from "./reaction-outcome";
import { sleep } from "./timeout";
import { wideLog, withWideEvent } from "./wide-events";

const logger = createBotLogger("shared", "streaming");

/** The approval window is hours, so "360 minutes" is not a usable way to say it. */
function formatExpiry(seconds: number): string {
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return minutes === 1 ? "1 minute" : `${minutes} minutes`;
  const hours = Math.round(minutes / 60);
  return hours === 1 ? "1 hour" : `${hours} hours`;
}

/** Render a PENDING HIL approval as a yes/no prompt for a bot message. Only
 * pending approvals are surfaced out-of-band (see handleApprovalUpdate); settled
 * ones are narrated by the agent's streamed reply. */
function formatApprovalPrompt(data: ApprovalRequestData): string {
  const age =
    data.age_seconds != null ? ` (${formatApprovalAge(data.age_seconds)})` : "";
  return (
    `**Approval needed:** ${data.summary}${age}\n` +
    `Reply **yes** to approve or **no** to decline. This expires in ${formatExpiry(data.timeout_seconds)}.`
  );
}

export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: PlatformName;
}

export type MessageEditor = (text: string) => Promise<void>;
/** A message the streamer posted: editable, and deletable where the platform lets a bot unsend. */
export interface SentBubble {
  edit: MessageEditor;
  delete?: () => Promise<void>;
}
export type NewMessageSender = (text: string) => Promise<SentBubble>;
/** Clears what the adapter showed while waiting, for a turn that ended with no reply. */
export type NoReplyHandler = () => Promise<void>;

export const STREAMING_DEFAULTS: Record<PlatformName, StreamingOptions> = {
  discord: {
    editIntervalMs: 1200,
    streaming: false,
    platform: "discord",
  },
  slack: {
    editIntervalMs: 1500,
    streaming: true,
    platform: "slack",
  },
  telegram: {
    editIntervalMs: 1000,
    streaming: true,
    platform: "telegram",
  },
  whatsapp: {
    editIntervalMs: 2000,
    streaming: false,
    platform: "whatsapp",
  },
  imessage: {
    editIntervalMs: 2000,
    streaming: false,
    platform: "imessage",
  },
};

/**
 * Internal streaming handler used by both authenticated and mention flows.
 */
async function _handleStream(
  streamFn: (
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
    deliverOutOfBand: (text: string) => Promise<void>,
    onMessageBoundary: (discarded: boolean) => Promise<void>,
    onReaction: ReactionHandler,
  ) => Promise<string>,
  request: ChatRequest,
  gaia: GaiaClient,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender,
  onAuthError: ((authUrl: string) => Promise<void>) | null,
  onGenericError: (formattedError: string) => Promise<void>,
  recordFailure: (cause: unknown) => void,
  options: StreamingOptions,
  onReaction: ReactionHandler | undefined,
  onNoReply: NoReplyHandler | undefined,
): Promise<void> {
  const { editIntervalMs, streaming, platform } = options;

  // Centralized markdown conversion: every outbound string is run through the
  // platform converter HERE, at the single chokepoint, so adapters receive
  // already-converted text and never call convertTo<Platform>Markdown inline.
  const render = PLATFORM_MARKDOWN[platform];
  const config: DeliveryConfig = { live: streaming, platform, render };
  let delivery = initialDeliveryState();
  /** Every message this turn put on screen, by slot; the placeholder's delete is the adapter's clear-up. */
  const messages = new Map<MessageSlot, SentBubble>([
    [PLACEHOLDER_SLOT, { edit: editMessage, delete: onNoReply }],
  ]);

  let lastEditTime = 0;
  let editTimer: ReturnType<typeof setTimeout> | null = null;
  let streamDone = false;
  /** True once the stream's own error handler has told the user about a failure. */
  let failureReported = false;

  // One platform call at a time, in order: concurrent edits land out of order.
  let opQueue: Promise<void> = Promise.resolve();
  const enqueue = (fn: () => Promise<void>): Promise<void> => {
    opQueue = opQueue.then(fn, fn);
    return opQueue;
  };

  const post = async (slot: MessageSlot, text: string): Promise<void> => {
    messages.set(slot, await sendNewMessage(render(text)));
    logger.info("bubble_delivered", {
      method: "new",
      slot,
      chars: text.length,
    });
  };

  /**
   * Edits a message, reacting to WHY an edit failed: only a message that is
   * genuinely gone justifies posting the text again, since re-sending on a rate
   * limit or a network blip delivered the reply twice.
   */
  const editSlot = async (slot: MessageSlot, text: string): Promise<void> => {
    const message = messages.get(slot);
    if (!message) {
      await post(slot, text);
      return;
    }
    try {
      await message.edit(render(text));
      return;
    } catch (err) {
      if (isMessageGoneError(err)) {
        logger.info("stream_edit_recovered", sanitizeErrorForLog(err));
        await post(slot, text);
        return;
      }
      const waitMs = retryAfterMs(err);
      if (waitMs !== null) await sleep(waitMs);
      try {
        await message.edit(render(text));
      } catch (retryErr) {
        logger.info("stream_edit_skipped", {
          ...sanitizeErrorForLog(retryErr),
          slot,
        });
      }
    }
  };

  const deleteSlot = async (slot: MessageSlot): Promise<void> => {
    const message = messages.get(slot);
    messages.delete(slot);
    if (!message) return;
    if (!message.delete) {
      throw new Error(
        `${platform} cannot delete a bot message, so it must not stream`,
      );
    }
    try {
      await message.delete();
    } catch (err) {
      // The retracted text stays on screen; nothing else can take it back.
      wideLog.warning("bubble_delete_failed", {
        ...sanitizeErrorForLog(err),
        slot,
      });
    }
  };

  const runOp = async (op: DeliveryOp): Promise<void> => {
    switch (op.kind) {
      case "pause":
        await sleep(BUBBLE_PAUSE_MS);
        return;
      case "send":
        await post(op.slot, op.text);
        return;
      case "edit":
        await editSlot(op.slot, op.text);
        return;
      case "delete":
        await deleteSlot(op.slot);
        return;
      default: {
        const unhandled: never = op;
        return unhandled;
      }
    }
  };

  /** Runs one stream event through the delivery machine, then its platform operations, in order. */
  const apply = (event: DeliveryEvent): Promise<void> =>
    enqueue(async () => {
      const step = stepDelivery(delivery, event, config);
      delivery = step.state;
      if (event.kind === "boundary" && event.discarded) {
        logger.info("bubble_discarded", {
          deleted: step.ops.filter((op) => op.kind === "delete").length,
        });
      }
      for (const op of step.ops) await runOp(op);
    });

  /** A live preview is best effort: the next one, or the bubble's sealing, supersedes it. */
  const preview = (): void => {
    lastEditTime = Date.now();
    apply({ kind: "tick" }).catch((err: unknown) => {
      logger.info("stream_edit_skipped", sanitizeErrorForLog(err));
    });
  };

  const clearEditTimer = (): void => {
    if (editTimer) {
      clearTimeout(editTimer);
      editTimer = null;
    }
  };

  const schedulePreview = (): void => {
    if (streamDone || !streaming) return;
    const sinceLast = Date.now() - lastEditTime;
    if (sinceLast >= editIntervalMs) {
      clearEditTimer();
      preview();
    } else if (!editTimer) {
      editTimer = setTimeout(() => {
        editTimer = null;
        if (!streamDone) preview();
      }, editIntervalMs - sinceLast);
    }
  };

  const handleMessageBoundary = (discarded: boolean): Promise<void> =>
    apply({ kind: "boundary", discarded });

  /**
   * Posts a message outside the streamed reply: the HIL approval prompt the user must
   * answer while the agent is paused, or a rate-limit notice. It lands below what has
   * streamed so far and survives the message it arrived during being retracted.
   */
  const deliverOutOfBand = (text: string): Promise<void> =>
    apply({ kind: "outOfBand", text });

  /**
   * Tells the user the turn failed: in the placeholder while it still holds nothing the
   * user needs, else as a message of its own, so no bubble they read is overwritten.
   */
  const emitGenericError = async (
    text: string,
    cause: unknown,
  ): Promise<void> => {
    recordFailure(cause);
    if (delivery.reusable?.slot === PLACEHOLDER_SLOT) {
      await onGenericError(render(text));
      return;
    }
    await deliverOutOfBand(text);
  };

  /** Hands a reaction to the adapter to attach natively, once any edit still in flight has landed. */
  const reactToTurn = async (
    emoji: string,
    replaces: string | null,
  ): Promise<ReactionOutcome> => {
    if (!onReaction) return REACTION_OUTCOME.NO_TARGET;
    // Overwritten by the queued call; enqueue rejects if it throws.
    let outcome: ReactionOutcome = REACTION_OUTCOME.NO_TARGET;
    await enqueue(async () => {
      outcome = await onReaction(emoji, replaces);
    });
    return outcome;
  };

  try {
    await streamFn(
      async (chunk) => {
        await apply({ kind: "text", chunk });
        schedulePreview();
      },
      async () => {
        streamDone = true;
        clearEditTimer();
        await apply({ kind: "end" });

        // A retracted preamble with nothing to replace it means the turn produced no reply at
        // all. The preamble stays (a blank message is worse than the agent's own words), but
        // it must still be visible that this happened.
        if (delivery.reusable?.retracted) {
          logger.info("bubble_preamble_kept", {
            slot: delivery.reusable.slot,
          });
        }

        // A hand-off or a reaction says nothing: whatever the adapter put up while
        // waiting must not outlive the turn.
        if (!delivery.spoke && onNoReply) {
          await onNoReply();
        }
      },
      async (error) => {
        streamDone = true;
        failureReported = true;
        clearEditTimer();
        if (
          error.message === BOT_STREAM_ERROR.notAuthenticated &&
          onAuthError
        ) {
          try {
            const { authUrl } = await gaia.createLinkToken(
              request.platform,
              request.platformUserId,
            );
            await onAuthError(authUrl);
          } catch (linkError) {
            await emitGenericError(
              "Failed to generate auth link. Please try /auth again.",
              linkError,
            );
          }
        } else if (error.message === BOT_STREAM_ERROR.planRequired) {
          await emitGenericError(
            buildPlanRequiredMessage(gaia.getPricingUrl()),
            error,
          );
        } else {
          await emitGenericError(formatBotError(error, platform), error);
        }
      },
      deliverOutOfBand,
      handleMessageBoundary,
      reactToTurn,
    );
  } catch (error) {
    // `streamChat` reports a non-retryable failure via `onError` and THEN rethrows, so by the
    // time it reaches here the user is already told — reporting again doubled every rate limit
    // and dead backend. This catch only nets failures that never reached `onError` (e.g. a throw from a delivery callback).
    if (failureReported) {
      // Usually the rethrow of what onError already recorded — or delivering that notice failed.
      wideLog.warning(
        "stream_error_already_reported",
        sanitizeErrorForLog(error),
      );
      return;
    }
    await emitGenericError(formatBotError(error, platform), error);
  }
}

/**
 * Handles streaming chat for authenticated users (slash commands).
 *
 * Runs inside a {@link withWideEvent} boundary: every adapter message/mention
 * flow that routes through here emits one canonical `bot_event` line carrying
 * the full chat context (latency, chunk counts, errors) — the shared
 * instrumentation chokepoint for all four platforms.
 */
export async function handleStreamingChat(
  gaia: GaiaClient,
  request: ChatRequest,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender,
  onAuthError: (authUrl: string) => Promise<void>,
  onGenericError: (formattedError: string) => Promise<void>,
  options: StreamingOptions,
  analytics?: AnalyticsContext,
  onReaction?: ReactionHandler,
  onNoReply?: NoReplyHandler,
): Promise<void> {
  // Latency + high-cardinality observability for the chat pipeline. user_hash
  // is the HMAC-hashed id (no PII). ttfb_ms = time to first streamed chunk.
  const userHash = hashLogIdentifier(request.platformUserId);
  // channelId can be a raw PII identifier (e.g. the WhatsApp phone/waId), so it
  // is hashed like user_hash before it reaches the logs.
  const channelHash = hashLogIdentifier(request.channelId);

  return withWideEvent(
    "chat",
    {
      platform: request.platform,
      component: "streaming",
      user_hash: userHash,
      channel_hash: channelHash,
      message_length: request.message.length,
      has_files: Boolean(request.fileIds?.length || request.fileData?.length),
      streaming_enabled: options.streaming,
    },
    () =>
      runStreamingChat(
        gaia,
        request,
        editMessage,
        sendNewMessage,
        onAuthError,
        onGenericError,
        options,
        analytics,
        userHash,
        onReaction,
        onNoReply,
      ),
  );
}

/** The body of {@link handleStreamingChat}, running inside its wide-event boundary. */
async function runStreamingChat(
  gaia: GaiaClient,
  request: ChatRequest,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender,
  onAuthError: (authUrl: string) => Promise<void>,
  onGenericError: (formattedError: string) => Promise<void>,
  options: StreamingOptions,
  analytics: AnalyticsContext | undefined,
  userHash: string | undefined,
  onReaction: ReactionHandler | undefined,
  onNoReply: NoReplyHandler | undefined,
): Promise<void> {
  const startMs = Date.now();
  let responseLength = 0;
  let firstChunkMs: number | null = null;
  let chunkCount = 0;
  let discardedMessages = 0;
  let notices = 0;
  let conversationId = "";
  let reactionDelivered:
    | ReturnType<typeof reactionDeliveredProperties>
    | undefined;

  analytics?.client.capture(analytics.distinctId, "bot:message_received", {
    interaction_type: "chat",
    message_length: request.message.length,
  });

  const wrappedOnAuthError = async (authUrl: string) => {
    // A fresh auth link was minted for this user (createLinkToken in
    // _handleStream) — leave an audit trail like the backend's auth routes do.
    wideLog.audit("auth_link_issued", { user_hash: userHash });
    wideLog.fail(BOT_FAILURE_REASON.ACCOUNT_NOT_LINKED);
    await onAuthError(authUrl);
  };

  const recordStreamFailure = (cause: unknown): void => {
    // The failure with its reason and full latency context — a real-time line,
    // an errors[] entry, and outcome "failed" on this chat's wide event.
    const reason = recordBotFailure("chat_stream_failed", cause, {
      duration_ms: Date.now() - startMs,
      ttfb_ms: firstChunkMs,
      chunk_count: chunkCount,
      response_length: responseLength,
      context: "chat:streaming",
    });
    if (isLostReply(reason)) {
      createDeliveryFailureReporter(
        gaia,
        request.platform,
      )({
        kind: DELIVERY_FAILURE_KIND.REPLY_FAILED,
        reason,
        error_message: describeErrorForAlert(cause, "chat"),
        destination_id: request.platformUserId,
      });
    }
    // Do not ship the raw error string — it can contain paths, request IDs,
    // or upstream-echoed tokens. `context` is enough to bucket failures.
    analytics?.client.capture(analytics.distinctId, "bot:error", {
      context: "chat:streaming",
      duration_ms: Date.now() - startMs,
    });
  };

  const streamFn = (
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
    deliverOutOfBand: (text: string) => Promise<void>,
    onMessageBoundary: (discarded: boolean) => Promise<void>,
    reactToTurn: ReactionHandler,
  ) =>
    gaia.chatStream(
      request,
      (text) => {
        chunkCount++;
        if (firstChunkMs === null) {
          firstChunkMs = Date.now() - startMs;
        }
        return onChunk(text);
      },
      async (fullText, convId) => {
        responseLength = fullText.length;
        conversationId = convId;
        await onDone(fullText, convId);
      },
      onError,
      // HIL approval prompts go out as their own message so a non-streaming platform
      // (Discord/WhatsApp, which shows nothing until the stream ends) still surfaces the
      // question while the agent is paused waiting.

      // Only the PENDING question needs one — a bot has no buttons, so the user answers in
      // chat. Settled frames (auto-approved, or a resumed decision) arrive mid-stream and are
      // already narrated by the agent's streamed reply, so posting them would fragment it.
      async (data: ApprovalRequestData) => {
        if (data.status !== "pending") return;
        await deliverOutOfBand(formatApprovalPrompt(data));
      },
      // One assistant message ended. A kept one is segmented and delivered here
      // and nowhere earlier; a discarded one (a handoff preamble, or a draft the
      // style guard rewrote) is taken back off the screen.
      async (discarded: boolean) => {
        if (discarded) discardedMessages += 1;
        await onMessageBoundary(discarded);
      },
      // A rate-limit notice is about the turn, not part of it — out-of-band for the same
      // reason as the approval prompt: it must survive the assistant message it arrived during
      // being retracted, and still reach a non-streaming platform that renders nothing until the stream ends.
      async (text: string) => {
        notices += 1;
        await deliverOutOfBand(text);
      },
      async (emoji: string, replaces: string | null) => {
        const outcome = await reactToTurn(emoji, replaces);
        reactionDelivered = reactionDeliveredProperties(
          outcome,
          REACTION_SURFACE.LIVE,
        );
        analytics?.client.capture(
          analytics.distinctId,
          "bot:reaction_delivered",
          reactionDelivered,
        );
        return outcome;
      },
    );

  try {
    await _handleStream(
      streamFn,
      request,
      gaia,
      editMessage,
      sendNewMessage,
      wrappedOnAuthError,
      onGenericError,
      recordStreamFailure,
      options,
      onReaction,
      onNoReply,
    );
  } finally {
    wideLog.set({
      ttfb_ms: firstChunkMs ?? undefined,
      chunk_count: chunkCount,
      discarded_messages: discardedMessages,
      notices_delivered: notices,
      response_length: responseLength,
      conversation_id: conversationId || undefined,
      reaction_delivery: reactionDelivered?.delivery,
      reaction_reason: reactionDelivered?.reason,
    });
  }
}
