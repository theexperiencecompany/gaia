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
import type { Analytics } from "../../analytics";
import { BOT_EVENTS } from "../../analytics/events/bots";
import {
  NEW_MESSAGE_BREAK_TOKEN,
  NEW_MESSAGE_BREAK_TOKEN_LENGTH,
} from "../../utils/messageBreakUtils";
import type { GaiaClient } from "../api";
import type { ChatRequest } from "../types";
import { formatBotError } from "./formatters";
import { chunkResponse, truncateResponse } from "./index";

export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: "discord" | "slack" | "telegram" | "whatsapp";
}

export type MessageEditor = (text: string) => Promise<void>;
export type NewMessageSender = (text: string) => Promise<MessageEditor>;

export const STREAMING_DEFAULTS: Record<
  "discord" | "slack" | "telegram" | "whatsapp",
  StreamingOptions
> = {
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
};

/**
 * Internal streaming handler used by both authenticated and mention flows.
 */
async function _handleStream(
  streamFn: (
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
  ) => Promise<string>,
  request: ChatRequest,
  gaia: GaiaClient,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender | null,
  onAuthError: ((authUrl: string) => Promise<void>) | null,
  onGenericError: (formattedError: string) => Promise<void>,
  options: StreamingOptions,
): Promise<void> {
  const { editIntervalMs, streaming, platform } = options;

  let lastEditTime = 0;
  let editTimer: ReturnType<typeof setTimeout> | null = null;
  let fullText = "";
  let streamDone = false;
  let currentEditor = editMessage;
  let sentText = "";

  // Serialization queue to prevent concurrent Telegram API calls
  // which cause out-of-order message updates
  let opQueue: Promise<void> = Promise.resolve();
  const enqueue = (fn: () => Promise<void>): Promise<void> => {
    opQueue = opQueue.then(fn, fn);
    return opQueue;
  };

  const updateDisplay = async (text: string) => {
    // Strip any unprocessed break tags before displaying
    const cleaned = text.replaceAll(NEW_MESSAGE_BREAK_TOKEN, "").trim();
    if (!cleaned) return;
    const truncated = truncateResponse(cleaned, platform);
    if (truncated === sentText) return;
    try {
      await currentEditor(truncated);
      sentText = truncated;
    } catch {
      // Message may have been deleted or interaction expired
    }
  };

  const handleNewMessageBreak = async () => {
    if (!sendNewMessage) return;

    while (fullText.includes(NEW_MESSAGE_BREAK_TOKEN)) {
      const breakIndex = fullText.indexOf(NEW_MESSAGE_BREAK_TOKEN);
      const beforeBreak = fullText.slice(0, breakIndex).trim();
      const afterBreak = fullText.slice(
        breakIndex + NEW_MESSAGE_BREAK_TOKEN_LENGTH,
      );

      if (beforeBreak && beforeBreak !== sentText) {
        await updateDisplay(beforeBreak);
      }

      const afterTrimmed = afterBreak.trim();
      if (!afterTrimmed) {
        // Break at end of text with nothing after — just update current segment
        fullText = "";
        return;
      }

      currentEditor = await sendNewMessage(
        afterTrimmed.replaceAll(NEW_MESSAGE_BREAK_TOKEN, "").trim() || "...",
      );
      fullText = afterTrimmed;
      sentText =
        afterTrimmed.replaceAll(NEW_MESSAGE_BREAK_TOKEN, "").trim() || "...";
    }
  };

  const deliverOverflowChunk = async (chunk: string): Promise<void> => {
    if (sendNewMessage) {
      currentEditor = await sendNewMessage(chunk);
      sentText = chunk;
    } else {
      // Adapter cannot post additional bubbles — best-effort fallback that
      // keeps the legacy truncation behaviour for this single bubble.
      const overflow = truncateResponse(chunk, platform);
      try {
        await currentEditor(overflow);
        sentText = overflow;
      } catch {
        // ignore
      }
    }
  };

  /**
   * Final delivery: split ``text`` on any unprocessed ``<NEW_MESSAGE_BREAK>``
   * markers, chunk each segment to the platform character limit, and deliver
   * the chunks in order — first chunk edits the current bubble, every
   * subsequent chunk is posted via ``sendNewMessage`` as a new bubble. Falls
   * back to truncation only when the adapter cannot send additional bubbles.
   *
   * Used at the end of the stream so the user always receives the full
   * response across as many bubbles as it takes, instead of a single bubble
   * with a ``... (truncated)`` suffix.
   */
  const finalizeDelivery = async (text: string): Promise<void> => {
    const segments = text
      .split(NEW_MESSAGE_BREAK_TOKEN)
      .map((s) => s.trim())
      .filter(Boolean);
    if (segments.length === 0) return;

    const allChunks = segments.flatMap((s) => chunkResponse(s, platform));
    if (allChunks.length === 0) return;

    const [firstChunk, ...remainingChunks] = allChunks;
    if (firstChunk !== sentText) {
      try {
        await currentEditor(firstChunk);
        sentText = firstChunk;
      } catch {
        // current bubble may have been deleted or expired
      }
    }

    for (const chunk of remainingChunks) {
      await deliverOverflowChunk(chunk);
    }
  };

  try {
    await streamFn(
      (chunk) => {
        fullText += chunk;
        if (streamDone || !streaming) return;

        const now = Date.now();
        if (
          fullText.includes(NEW_MESSAGE_BREAK_TOKEN) ||
          now - lastEditTime >= editIntervalMs
        ) {
          lastEditTime = now;
          if (editTimer) {
            clearTimeout(editTimer);
            editTimer = null;
          }
          enqueue(async () => {
            await handleNewMessageBreak();
            await updateDisplay(fullText);
          });
        } else if (!editTimer) {
          editTimer = setTimeout(
            () => {
              editTimer = null;
              if (!streamDone) {
                lastEditTime = Date.now();
                enqueue(() => updateDisplay(fullText));
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

        // Wait for any in-flight operations to finish before final update
        await opQueue;

        // Non-streaming platforms (Discord, WhatsApp) haven't shown anything
        // yet — adopt the full ``finalText``. Streaming platforms have been
        // live-editing one bubble (and potentially split off prior bubbles
        // via handleNewMessageBreak); ``fullText`` already holds the current
        // segment, no reset needed.
        if (!streaming) {
          fullText = finalText;
          sentText = "";
        }

        await finalizeDelivery(fullText);
      },
      async (error) => {
        streamDone = true;
        if (editTimer) {
          clearTimeout(editTimer);
          editTimer = null;
        }
        if (error.message === "not_authenticated" && onAuthError) {
          try {
            const { authUrl } = await gaia.createLinkToken(
              request.platform,
              request.platformUserId,
            );
            await onAuthError(authUrl);
          } catch {
            await onGenericError(
              "Failed to generate auth link. Please try /auth again.",
            );
          }
        } else {
          await onGenericError(formatBotError(error));
        }
      },
    );
  } catch (error) {
    await onGenericError(formatBotError(error));
  }
}

/**
 * Handles streaming chat for authenticated users (slash commands).
 */
export async function handleStreamingChat(
  gaia: GaiaClient,
  request: ChatRequest,
  editMessage: MessageEditor,
  sendNewMessage: NewMessageSender | null,
  onAuthError: (authUrl: string) => Promise<void>,
  onGenericError: (formattedError: string) => Promise<void>,
  options: StreamingOptions,
  analytics?: Analytics,
): Promise<void> {
  const distinctId = `${request.platform}:${request.platformUserId}`;
  const startMs = Date.now();
  let responseLength = 0;
  let hadError = false;

  analytics?.capture(distinctId, BOT_EVENTS.MESSAGE_RECEIVED, {
    interaction_type: "chat",
    channel_id: request.channelId,
    message_length: request.message.length,
  });

  analytics?.capture(distinctId, BOT_EVENTS.CHAT_STARTED, {
    channel_id: request.channelId,
    message_length: request.message.length,
    streaming_enabled: options.streaming,
  });

  const wrappedOnAuthError = async (authUrl: string) => {
    // Auth failures are terminal — skip chat_completed in the finally block.
    hadError = true;
    await onAuthError(authUrl);
  };

  const wrappedOnGenericError = async (formattedError: string) => {
    hadError = true;
    // Do not ship the raw error string — it can contain paths, request IDs,
    // or upstream-echoed tokens. `context` is enough to bucket failures.
    analytics?.capture(distinctId, BOT_EVENTS.ERROR, {
      context: "chat:streaming",
      channel_id: request.channelId,
      duration_ms: Date.now() - startMs,
    });
    await onGenericError(formattedError);
  };

  const streamFn = (
    onChunk: (text: string) => void | Promise<void>,
    onDone: (fullText: string, conversationId: string) => void | Promise<void>,
    onError: (error: Error) => void | Promise<void>,
  ) =>
    gaia.chatStream(
      request,
      onChunk,
      async (fullText, conversationId) => {
        responseLength = fullText.length;
        await onDone(fullText, conversationId);
      },
      onError,
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
    if (!hadError) {
      analytics?.capture(distinctId, BOT_EVENTS.CHAT_COMPLETED, {
        channel_id: request.channelId,
        duration_ms: Date.now() - startMs,
        response_length: responseLength,
        streaming_enabled: options.streaming,
      });
    }
  }
}
