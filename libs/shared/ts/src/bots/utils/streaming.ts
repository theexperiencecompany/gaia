/**
 * Shared streaming chat handler for all bot platforms.
 *
 * This module eliminates ~250 lines of duplicated streaming logic across
 * Discord, Slack, Telegram, and WhatsApp bots. Each bot provides thin callbacks:
 *
 *   editMessage   - Update the "Thinking..." message with new content
 *   onAuthError   - Show auth URL when user isn't linked
 *   onGenericError - Show formatted error message
 *
 * The shared function handles: text accumulation, throttled message edits
 * (to respect platform rate limits), cursor indicator display, timer
 * cleanup, and error routing through formatBotError.
 *
 * Usage in a bot command file:
 *   import { handleStreamingChat, STREAMING_DEFAULTS } from "@gaia/shared";
 *
 *   await handleStreamingChat(gaia, request, editMessage, onAuth, onErr,
 *     STREAMING_DEFAULTS.discord);
 */
import type { AnalyticsContext } from "../../analytics";
import { BOT_EVENTS } from "../../analytics/events/bots";
import type { ApprovalRequestData } from "../../chat";
import {
  containsMessageBreakToken,
  NEW_MESSAGE_BREAK_TOKEN,
  NEW_MESSAGE_BREAK_TOKEN_LENGTH,
  normalizeMessageBreakTokens,
  stripPartialBreakToken,
} from "../../utils/messageBreakUtils";
import type { GaiaClient } from "../api";
import { BOT_STREAM_ERROR } from "../api/chat-stream";
import type { ChatRequest, PlatformName } from "../types";
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
import { chunkResponse, PLATFORM_LIMITS } from "./text";
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
  return (
    `**Approval needed:** ${data.summary}\n` +
    `Reply **yes** to approve or **no** to decline. This expires in ${formatExpiry(data.timeout_seconds)}.`
  );
}

export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: PlatformName;
}

export type MessageEditor = (text: string) => Promise<void>;
export type NewMessageSender = (text: string) => Promise<MessageEditor>;

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
  ) => Promise<string>,
  request: ChatRequest,
  gaia: GaiaClient,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender,
  onAuthError: ((authUrl: string) => Promise<void>) | null,
  onGenericError: (formattedError: string) => Promise<void>,
  options: StreamingOptions,
): Promise<void> {
  const { editIntervalMs, streaming, platform } = options;

  // Centralized markdown conversion: every outbound string is run through the
  // platform converter HERE, at the single chokepoint, so adapters receive
  // already-converted text and never call convertTo<Platform>Markdown inline.
  const render = PLATFORM_MARKDOWN[platform];
  const emitGenericError = (text: string) => onGenericError(render(text));
  const wrappedEditMessage: MessageEditor = (text) => editMessage(render(text));
  const wrappedSendNewMessage: NewMessageSender = async (text) => {
    const editor = await sendNewMessage(render(text));
    return (updatedText) => editor(render(updatedText));
  };

  const limit = PLATFORM_LIMITS[platform];
  /** Rendered length — the size the platform actually enforces. */
  const measure = (text: string): number => render(text).length;

  let lastEditTime = 0;
  let editTimer: ReturnType<typeof setTimeout> | null = null;
  /** Streamed text that has not been delivered as a finished bubble yet. */
  let pending = "";
  let streamDone = false;
  let currentEditor = wrappedEditMessage;
  /** What the live bubble currently shows, so no-op edits are skipped. */
  let shownText = "";
  /** True once the live bubble holds finished text and must not be rewritten. */
  let bubbleSealed = false;

  // Serialization queue to prevent concurrent Telegram API calls
  // which cause out-of-order message updates
  let opQueue: Promise<void> = Promise.resolve();
  const enqueue = (fn: () => Promise<void>): Promise<void> => {
    opQueue = opQueue.then(fn, fn);
    return opQueue;
  };

  /**
   * Delivers one finished bubble. It lands in the live bubble if that one is
   * still open, otherwise in a new message. This is the only path that emits
   * final text, and it never truncates — oversized input is chunked before it
   * gets here.
   */
  const deliverBubble = async (text: string): Promise<void> => {
    if (!text) return;
    if (bubbleSealed) {
      currentEditor = await wrappedSendNewMessage(text);
    } else if (text !== shownText) {
      try {
        await currentEditor(text);
      } catch (err) {
        // The live bubble may have been deleted or expired. This is the only
        // copy of this text the user gets, so recover onto a fresh message
        // rather than dropping it.
        logger.debug("stream_edit_recovered", sanitizeErrorForLog(err));
        currentEditor = await wrappedSendNewMessage(text);
      }
    }
    shownText = text;
    bubbleSealed = true;
  };

  /**
   * Shows in-progress text in the live bubble. Never final, so a failed edit is
   * harmless — the next preview or the finished-bubble delivery supersedes it.
   */
  const previewBubble = async (text: string): Promise<void> => {
    if (!text) return;
    if (bubbleSealed) {
      currentEditor = await wrappedSendNewMessage(text);
      shownText = text;
      bubbleSealed = false;
      return;
    }
    if (text === shownText) return;
    try {
      await currentEditor(text);
      shownText = text;
    } catch (err) {
      // Transient: the live bubble may have been deleted or the interaction
      // expired. The next edit or the final delivery recovers, so this is
      // debug, not a failure — but it is logged so a persistent edit problem
      // stays visible.
      logger.debug("stream_edit_skipped", sanitizeErrorForLog(err));
    }
  };

  /**
   * Moves every finished piece out of ``pending`` and delivers it.
   *
   * A piece is finished once nothing that arrives later can change it. Two
   * things end a piece: a ``<NEW_MESSAGE_BREAK>``, which is the model closing
   * that bubble, and reaching the platform's rendered size limit, which forces
   * a cut wherever the text happens to be. Streamed text is only ever appended,
   * so a piece taken off the front of ``pending`` is already immutable and can
   * be delivered in full — chunked across as many bubbles as it needs, never
   * truncated.
   *
   * Whatever is left in ``pending`` afterwards is the still-growing tail, which
   * only ever gets shown as a live preview.
   */
  const flushFinished = async (): Promise<void> => {
    // Take everything finished out of `pending` FIRST, then deliver it. The
    // stream callback keeps appending to `pending` while a delivery is in
    // flight, so assigning to it after an await would overwrite — and silently
    // drop — whatever arrived in the meantime.
    const finished: string[] = [];

    // Normalize first: the model emits near-miss spellings of the sentinel
    // (<NEW_LINE_BREAK>), and only the canonical token may be split on.
    pending = normalizeMessageBreakTokens(pending);

    let breakIndex = pending.indexOf(NEW_MESSAGE_BREAK_TOKEN);
    while (breakIndex !== -1) {
      const segment = pending.slice(0, breakIndex).trim();
      pending = pending.slice(breakIndex + NEW_MESSAGE_BREAK_TOKEN_LENGTH);
      finished.push(...chunkResponse(segment, platform, render));
      breakIndex = pending.indexOf(NEW_MESSAGE_BREAK_TOKEN);
    }

    if (measure(pending) > limit) {
      // Over the limit: every chunk but the last is finished. The last is still
      // growing, so it stays in `pending` as the head of the next bubble.
      const chunks = chunkResponse(pending, platform, render);
      finished.push(...chunks.slice(0, -1));
      pending = chunks.at(-1) ?? "";
    }

    for (const chunk of finished) {
      await deliverBubble(chunk);
    }
  };

  /** Delivers the tail as the last bubble, once the stream is over. */
  const flushTail = async (): Promise<void> => {
    const tail = normalizeMessageBreakTokens(pending).trim();
    pending = "";
    for (const chunk of chunkResponse(tail, platform, render)) {
      await deliverBubble(chunk);
    }
  };

  /**
   * Posts a message that is not part of the streamed reply — currently the HIL
   * approval prompt, which the user has to answer while the agent is paused.
   *
   * It has to interrupt cleanly. Everything streamed so far is finished the
   * moment the agent pauses, so it is delivered first; the prompt then goes out
   * as its own message and the bubble is sealed, so whatever streams next opens
   * a fresh one. Without that seal the streamer keeps editing "the current
   * message" — which the adapters point at the prompt when they send it — and
   * the rest of the reply overwrites the question.
   */
  const deliverOutOfBand = async (text: string): Promise<void> => {
    await enqueue(async () => {
      await flushFinished();
      await flushTail();
      await wrappedSendNewMessage(text);
      bubbleSealed = true;
    });
  };

  try {
    await streamFn(
      (chunk) => {
        pending += chunk;
        if (streamDone || !streaming) return;

        const now = Date.now();
        // A complete break token seals a bubble, so act on it immediately
        // instead of waiting out the edit interval. Overflow is handled inside
        // flushFinished — detecting it needs a render pass, which is far too
        // expensive to run per streamed token.
        if (
          containsMessageBreakToken(pending) ||
          now - lastEditTime >= editIntervalMs
        ) {
          lastEditTime = now;
          if (editTimer) {
            clearTimeout(editTimer);
            editTimer = null;
          }
          enqueue(async () => {
            await flushFinished();
            await previewBubble(
              stripPartialBreakToken(
                normalizeMessageBreakTokens(pending),
              ).trim(),
            );
          });
        } else if (!editTimer) {
          editTimer = setTimeout(
            () => {
              editTimer = null;
              if (!streamDone) {
                lastEditTime = Date.now();
                enqueue(() =>
                  previewBubble(
                    stripPartialBreakToken(
                      normalizeMessageBreakTokens(pending),
                    ).trim(),
                  ),
                );
              }
            },
            editIntervalMs - (now - lastEditTime),
          );
        }
      },
      async (finalText) => {
        streamDone = true;
        if (editTimer) {
          clearTimeout(editTimer);
          editTimer = null;
        }

        // Wait for any in-flight operations to finish before final delivery
        await opQueue;

        // Non-streaming platforms (Discord, WhatsApp, iMessage) have shown
        // nothing yet, so the whole reply is delivered here from ``finalText``.
        // Streaming platforms have been delivering each bubble as it was
        // sealed; ``pending`` already holds the only piece still undelivered.
        if (!streaming) {
          pending = finalText;
          shownText = "";
          bubbleSealed = false;
        }

        await flushFinished();
        await flushTail();
      },
      async (error) => {
        streamDone = true;
        if (editTimer) {
          clearTimeout(editTimer);
          editTimer = null;
        }
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
          } catch {
            await emitGenericError(
              "Failed to generate auth link. Please try /auth again.",
            );
          }
        } else if (error.message === BOT_STREAM_ERROR.planRequired) {
          await emitGenericError(
            buildPlanRequiredMessage(gaia.getPricingUrl()),
          );
        } else {
          await emitGenericError(formatBotError(error));
        }
      },
      deliverOutOfBand,
    );
  } catch (error) {
    await emitGenericError(formatBotError(error));
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
        channelHash,
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
  channelHash: string | undefined,
): Promise<void> {
  const startMs = Date.now();
  let responseLength = 0;
  let hadError = false;
  let firstChunkMs: number | null = null;
  let chunkCount = 0;
  let conversationId = "";

  analytics?.client.capture(analytics.distinctId, BOT_EVENTS.MESSAGE_RECEIVED, {
    interaction_type: "chat",
    message_length: request.message.length,
  });

  analytics?.client.capture(analytics.distinctId, BOT_EVENTS.CHAT_STARTED, {
    message_length: request.message.length,
    streaming_enabled: options.streaming,
  });

  const wrappedOnAuthError = async (authUrl: string) => {
    // Auth failures are terminal — skip chat_completed in the finally block.
    hadError = true;
    // A fresh auth link was minted for this user (createLinkToken in
    // _handleStream) — leave an audit trail like the backend's auth routes do.
    wideLog.audit("auth_link_issued", { user_hash: userHash });
    await onAuthError(authUrl);
  };

  const wrappedOnGenericError = async (formattedError: string) => {
    hadError = true;
    // Surface the failure with full latency context so every error is visible —
    // a real-time line plus an errors[] entry on this chat's wide event.
    wideLog.error("chat_stream_failed", {
      user_hash: userHash,
      channel_hash: channelHash,
      duration_ms: Date.now() - startMs,
      ttfb_ms: firstChunkMs,
      chunk_count: chunkCount,
      response_length: responseLength,
      context: "chat:streaming",
    });
    // Do not ship the raw error string — it can contain paths, request IDs,
    // or upstream-echoed tokens. `context` is enough to bucket failures.
    analytics?.client.capture(analytics.distinctId, BOT_EVENTS.ERROR, {
      context: "chat:streaming",
      duration_ms: Date.now() - startMs,
    });
    await onGenericError(formattedError);
  };

  const streamFn = (
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
    deliverOutOfBand: (text: string) => Promise<void>,
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
      // HIL approval prompts go out as their own message so a non-streaming
      // platform (Discord/WhatsApp, which shows nothing until the stream ends)
      // still surfaces the question while the agent is paused waiting.
      //
      // Only the PENDING question needs one — a bot has no buttons, so the user
      // answers in chat. Settled frames (an auto_approved receipt in auto mode,
      // or a resumed decision) arrive MID-STREAM and are already narrated by the
      // agent's streamed reply, so posting them would fragment it.
      async (data: ApprovalRequestData) => {
        if (data.status !== "pending") return;
        await deliverOutOfBand(formatApprovalPrompt(data));
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
      wrappedOnGenericError,
      options,
    );
  } finally {
    wideLog.set({
      ttfb_ms: firstChunkMs ?? undefined,
      chunk_count: chunkCount,
      response_length: responseLength,
      conversation_id: conversationId || undefined,
    });
    if (!hadError) {
      analytics?.client.capture(
        analytics.distinctId,
        BOT_EVENTS.CHAT_COMPLETED,
        {
          duration_ms: Date.now() - startMs,
          response_length: responseLength,
          streaming_enabled: options.streaming,
        },
      );
    }
  }
}
