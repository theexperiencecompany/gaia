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
import type { GaiaClient } from "../api";
import { BOT_STREAM_ERROR } from "../api/chat-stream";
import type { ChatRequest, PlatformName } from "../types";
import { segmentIntoBubbles } from "./bubbles";
import { isMessageGoneError, retryAfterMs } from "./delivery-errors";
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
    onMessageBoundary: (discarded: boolean) => Promise<void>,
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
  /** Text streamed for the assistant message currently in flight. */
  let pending = "";
  let streamDone = false;
  let currentEditor = wrappedEditMessage;
  /** What the live bubble currently shows, so no-op edits are skipped. */
  let shownText = "";
  /** True once the live bubble holds finished text and must not be rewritten. */
  let bubbleSealed = false;
  /** Position of the next finished bubble in this reply, for the delivery event. */
  let bubbleIndex = 0;
  /**
   * True while the live bubble holds text the backend has since retracted (a
   * MOMENT-1 handoff preamble). It stays on screen — no platform lets us delete
   * a message — until the real reply overwrites it in place.
   */
  let bubbleProvisional = false;
  /** True once the stream's own error handler has told the user about a failure. */
  let failureReported = false;

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
  const noteDelivered = (method: "edit" | "new", chars: number): void => {
    logger.info("bubble_delivered", { method, index: bubbleIndex, chars });
  };

  /**
   * Puts finished text into the live bubble, reacting to WHY an edit failed.
   *
   * Every failure used to take the same branch — re-send the whole text as a
   * new message — which on a rate limit or a network blip left the original
   * bubble on screen and posted the reply a second time underneath it. Only a
   * message that is genuinely gone justifies a new one.
   */
  const editFinished = async (text: string): Promise<void> => {
    try {
      await currentEditor(text);
      noteDelivered("edit", text.length);
      return;
    } catch (err) {
      if (isMessageGoneError(err)) {
        // Nothing to edit any more, and this is the only copy of the text.
        logger.info("stream_edit_recovered", sanitizeErrorForLog(err));
        currentEditor = await wrappedSendNewMessage(text);
        noteDelivered("new", text.length);
        return;
      }
      const waitMs = retryAfterMs(err);
      if (waitMs !== null) {
        await new Promise((resolve) => setTimeout(resolve, waitMs));
      }
      try {
        await currentEditor(text);
        noteDelivered("edit", text.length);
      } catch (retryErr) {
        // Keep the bubble that is already there. Re-sending is what
        // double-posted the reply, and the user is not better off with two.
        logger.info("stream_edit_skipped", {
          ...sanitizeErrorForLog(retryErr),
          bubble_index: bubbleIndex,
        });
      }
    }
  };

  const deliverBubble = async (text: string): Promise<void> => {
    if (!text) return;
    if (bubbleSealed) {
      currentEditor = await wrappedSendNewMessage(text);
      noteDelivered("new", text.length);
    } else if (text !== shownText) {
      await editFinished(text);
    }
    shownText = text;
    bubbleSealed = true;
    bubbleProvisional = false;
    bubbleIndex += 1;
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
      bubbleProvisional = false;
    } catch (err) {
      // Transient: the live bubble may have been deleted or the interaction
      // expired. The next edit or the final delivery recovers — but a
      // persistent edit problem is exactly how a bot goes quiet without
      // failing, so it is a visible line, not a debug one.
      logger.info("stream_edit_skipped", sanitizeErrorForLog(err));
    }
  };

  /**
   * The messages a finished assistant message should be sent as: segmented into
   * bubbles the way a person texts, then chunked to the platform's limit.
   *
   * Segmentation is not optional politeness. The model is asked to split its
   * own replies with the sentinel and across 42 consecutive production replies
   * never once did, so "one sentinel-free reply" is the normal case, not the
   * edge case — and it arrived as a single 4,358-character Telegram message.
   */
  const bubblesFor = (message: string): string[] =>
    segmentIntoBubbles(message).flatMap((bubble) =>
      chunkResponse(bubble, platform, render),
    );

  /**
   * What the live bubble should show for the text streamed so far: the bubbles
   * this message will eventually be split into, joined back together.
   *
   * Segmenting here and throwing the split away is what keeps sentinels off the
   * screen — whole ones, half-received ones, and the near-miss spellings the
   * model emits (``<NEW_LINE_BREAK>``, ``[NEW_MESSAGE_BREAK]``) — and it makes
   * the preview a prefix of what is finally delivered rather than a different
   * rendering of it.
   *
   * Capped at the platform's rendered limit: a preview now holds a whole
   * in-flight message, so it can outgrow the limit long before the boundary
   * that splits it, and an oversized edit is rejected outright — which would
   * freeze the bubble on whatever it last showed. Nothing is lost by capping:
   * the full text is still in ``pending`` and goes out, split, at the boundary.
   */
  const previewFor = (streamed: string): string => {
    const text = segmentIntoBubbles(streamed).join("\n\n");
    if (measure(text) <= limit) return text;
    return chunkResponse(text, platform, render)[0] ?? "";
  };

  /**
   * Delivers the assistant message that just ended, as the bubbles it should be
   * split into: the first replaces the live preview, the rest are new messages.
   *
   * **Nothing is sealed before this point.** Segmentation used to run mid-stream
   * — on every sentinel, and on every overflow — which sealed bubbles while the
   * message was still in flight. A retraction can only reopen the ONE bubble
   * still being edited, so a style-guard rewrite (which retracts its draft and
   * streams a replacement) left every already-sealed draft bubble on screen and
   * delivered the reply twice. Waiting for the boundary is what makes the
   * retraction able to take back the whole message.
   */
  const flushMessage = async (): Promise<void> => {
    // Take the text out of `pending` FIRST, then deliver it. The stream
    // callback keeps appending while a delivery is in flight, so assigning to
    // it after an await would overwrite — and silently drop — whatever arrived
    // in the meantime.
    const message = pending;
    pending = "";
    for (const bubble of bubblesFor(message)) {
      await deliverBubble(bubble);
    }
  };

  /**
   * The backend has retracted the message currently on screen: its text was
   * either a preamble to a handoff ("let me get the tasks created…") or a draft
   * the style guard is about to rewrite, and the real reply is the NEXT message.
   *
   * No platform lets a bot unsend, and sending a correction would be a second
   * message about a message. So the bubble is left un-sealed instead: the reply
   * that arrives next overwrites it in place, and the user only ever sees one.
   */
  const discardCurrentMessage = (): void => {
    if (!pending && !shownText) return;
    pending = "";
    // A SEALED bubble holds something that is not the retracted text — an
    // approval prompt or a rate-limit notice, posted out of band. Reopening it
    // would hand the replacement reply that message to overwrite, and the
    // question the user still has to answer would disappear under it.
    if (bubbleSealed) {
      logger.info("bubble_discarded", { chars: 0, sealed: true });
      return;
    }
    bubbleProvisional = true;
    logger.info("bubble_discarded", { chars: shownText.length });
  };

  /**
   * One assistant message has ended, and the backend has said whether it counts.
   *
   * This is the only place streamed text becomes final, so it is also the only
   * place a retraction still has something to take back.
   */
  const handleMessageBoundary = async (discarded: boolean): Promise<void> => {
    await enqueue(async () => {
      // Non-streaming platforms (Discord, WhatsApp, iMessage) have shown
      // nothing yet: the whole reply is delivered at stream end from
      // ``finalText``, which the API already builds out of the KEPT messages
      // only. Acting on a boundary here would deliver that text a second time.
      if (!streaming) return;
      if (discarded) {
        discardCurrentMessage();
        return;
      }
      await flushMessage();
    });
  };

  /**
   * Posts a message that is not part of the streamed reply — currently the HIL
   * approval prompt, which the user has to answer while the agent is paused.
   *
   * It has to interrupt cleanly. The prompt must land BELOW the text the user
   * has already read, and the adapters point "the current message" at the
   * prompt the moment they send it — so whatever has streamed so far is
   * delivered and sealed first, and the bubble is sealed again afterwards so
   * the rest of the reply opens a fresh message instead of overwriting the
   * question.
   *
   * This is therefore the one place a message is sealed before its boundary
   * arrives, and it is deliberate: a retraction that follows finds a sealed
   * bubble and correctly leaves the prompt alone (see discardCurrentMessage).
   */
  const deliverOutOfBand = async (text: string): Promise<void> => {
    await enqueue(async () => {
      await flushMessage();
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
        if (now - lastEditTime >= editIntervalMs) {
          lastEditTime = now;
          if (editTimer) {
            clearTimeout(editTimer);
            editTimer = null;
          }
          enqueue(() => previewBubble(previewFor(pending)));
        } else if (!editTimer) {
          editTimer = setTimeout(
            () => {
              editTimer = null;
              if (!streamDone) {
                lastEditTime = Date.now();
                enqueue(() => previewBubble(previewFor(pending)));
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
        // Streaming platforms delivered each message at its boundary;
        // ``pending`` holds only a last message that never got one — a legacy
        // stream, or one cut short by an error.
        if (!streaming) {
          pending = finalText;
          shownText = "";
          bubbleSealed = false;
        }

        await flushMessage();

        // A retracted preamble with nothing to replace it means the turn
        // produced no reply at all. The preamble stays — a blank message is
        // worse than the agent's own words — but it must be visible that it
        // happened.
        if (bubbleProvisional) {
          logger.info("bubble_preamble_kept", { chars: shownText.length });
        }
      },
      async (error) => {
        streamDone = true;
        failureReported = true;
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
      handleMessageBoundary,
    );
  } catch (error) {
    // `streamChat` reports a non-retryable failure through `onError` and THEN
    // rethrows it, so by the time it reaches here the user has already been
    // told — reporting again delivered every rate limit and every dead backend
    // as two identical messages. This catch is the net for failures that never
    // reached `onError` at all, such as a throw out of a delivery callback.
    if (failureReported) {
      logger.info("stream_error_already_reported", sanitizeErrorForLog(error));
      return;
    }
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
  let discardedMessages = 0;
  let notices = 0;
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
    onMessageBoundary: (discarded: boolean) => Promise<void>,
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
      // One assistant message ended. A kept one is segmented and delivered here
      // and nowhere earlier; a discarded one (a handoff preamble, or a draft the
      // style guard rewrote) is taken back off the screen.
      async (discarded: boolean) => {
        if (discarded) discardedMessages += 1;
        await onMessageBoundary(discarded);
      },
      // A rate-limit notice is about the turn, not part of it. Out-of-band for
      // the same reason the approval prompt is: it must survive the assistant
      // message it arrived during being retracted, and it must reach a
      // non-streaming platform that renders nothing until the stream ends.
      async (text: string) => {
        notices += 1;
        await deliverOutOfBand(text);
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
      discarded_messages: discardedMessages,
      notices_delivered: notices,
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
