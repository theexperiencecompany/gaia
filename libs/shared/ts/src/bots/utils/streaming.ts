/**
 * Shared streaming chat handler for all bot platforms.
 *
 * This module eliminates ~250 lines of duplicated streaming logic across
 * Discord, Slack, and Telegram bots. Each bot provides thin callbacks:
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
import type { GaiaClient } from "../api";
import type { ChatRequest } from "../types";
import { formatBotError } from "./formatters";
import { truncateResponse } from "./index";

export interface StreamingOptions {
  editIntervalMs: number;
  streaming: boolean;
  platform: "discord" | "slack" | "telegram" | "whatsapp";
}

export type MessageEditor = (text: string) => Promise<void>;
export type NewMessageSender = (text: string) => Promise<MessageEditor>;

export const STREAMING_DEFAULTS: Record<
  "discord" | "slack" | "telegram",
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
  let breakHandledDuringStreaming = false;

  // Serialization queue to prevent concurrent Telegram API calls
  // which cause out-of-order message updates
  let opQueue: Promise<void> = Promise.resolve();
  const enqueue = (fn: () => Promise<void>): Promise<void> => {
    opQueue = opQueue.then(fn, fn);
    return opQueue;
  };

  const updateDisplay = async (text: string) => {
    // Strip any unprocessed break tags before displaying
    const cleaned = text.replaceAll("<NEW_MESSAGE_BREAK>", "").trim();
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

    while (fullText.includes("<NEW_MESSAGE_BREAK>")) {
      const breakIndex = fullText.indexOf("<NEW_MESSAGE_BREAK>");
      const beforeBreak = fullText.slice(0, breakIndex).trim();
      const afterBreak = fullText.slice(breakIndex + 19);

      if (beforeBreak && beforeBreak !== sentText) {
        await updateDisplay(beforeBreak);
      }

      const afterTrimmed = afterBreak.trim();
      if (!afterTrimmed) {
        // Break at end of text with nothing after — just update current segment
        fullText = "";
        breakHandledDuringStreaming = true;
        return;
      }

      currentEditor = await sendNewMessage(
        afterTrimmed.replaceAll("<NEW_MESSAGE_BREAK>", "").trim() || "...",
      );
      fullText = afterTrimmed;
      sentText =
        afterTrimmed.replaceAll("<NEW_MESSAGE_BREAK>", "").trim() || "...";
      breakHandledDuringStreaming = true;
    }
  };

  try {
    await streamFn(
      (chunk) => {
        fullText += chunk;
        if (streamDone || !streaming) return;

        const now = Date.now();
        if (
          fullText.includes("<NEW_MESSAGE_BREAK>") ||
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

        if (streaming && breakHandledDuringStreaming) {
          // Breaks were already processed during streaming — just do final update
          // of the current (last) segment without re-splitting
          await updateDisplay(fullText);
        } else if (
          sendNewMessage &&
          finalText.includes("<NEW_MESSAGE_BREAK>")
        ) {
          // Handle NEW_MESSAGE_BREAK for non-streaming platforms (e.g. Discord)
          fullText = finalText;
          sentText = "";
          const parts = fullText
            .split("<NEW_MESSAGE_BREAK>")
            .map((p) => p.trim())
            .filter(Boolean);
          if (parts.length > 0) {
            await updateDisplay(parts[0]);
            for (let i = 1; i < parts.length; i++) {
              currentEditor = await sendNewMessage(parts[i]);
            }
          }
        } else {
          // For streaming, don't reset sentText — avoid re-sending already displayed content
          if (!streaming) {
            fullText = finalText;
            sentText = "";
          }
          await updateDisplay(fullText);
        }
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
): Promise<void> {
  return _handleStream(
    (onChunk, onDone, onError) =>
      gaia.chatStream(request, onChunk, onDone, onError),
    request,
    gaia,
    editMessage,
    sendNewMessage,
    onAuthError,
    onGenericError,
    options,
  );
}
