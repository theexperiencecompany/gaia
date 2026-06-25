/**
 * SSE chat streaming for the GAIA bot API.
 *
 * Extracted from {@link GaiaClient} to keep the transport/CRUD client focused.
 * Owns the streaming concern end to end: the SSE request, incremental parsing,
 * inactivity/keepalive handling, session-token capture, and transient-error
 * retry with exponential backoff.
 *
 * @module
 */
import type { Readable } from "node:stream";
import type { AxiosInstance } from "axios";
import type { BotUserContext, ChatRequest } from "../types";
import { createBotLogger, getHttpStatus } from "../utils/logger";

const logger = createBotLogger("shared", "chat-stream");

/**
 * The slice of {@link GaiaClient} the streamer needs: the HTTP client, auth
 * header builder, and session-token storage. Passed as an explicit deps object
 * so the streaming logic stays decoupled from the client's private internals.
 */
export interface ChatStreamClient {
  client: AxiosInstance;
  userHeaders(ctx: BotUserContext): Record<string, string>;
  storeSessionToken(ctx: BotUserContext, token: string): void;
  clearSessionToken(ctx: BotUserContext): void;
}

/** Exponential-backoff base delay and ceiling for stream retries. */
const RETRY_BASE_DELAY_MS = 1000;
const MAX_RETRY_DELAY_MS = 5000;

/** Errors that warrant retrying the whole stream from scratch. */
const RETRYABLE_ERRORS = [
  "ECONNRESET",
  "socket hang up",
  "ETIMEDOUT",
  "ECONNREFUSED",
  "Connection interrupted",
  "Connection lost before receiving a response",
];

/**
 * Streams a chat response via SSE, retrying transient failures with backoff.
 *
 * @returns the resolved conversation id once the stream completes.
 */
export async function streamChat(
  deps: ChatStreamClient,
  request: ChatRequest,
  onChunk: (text: string) => void | Promise<void>,
  onDone: (fullText: string, conversationId: string) => void | Promise<void>,
  onError: (error: Error) => void | Promise<void>,
  endpoint: string,
  maxRetries = 2,
): Promise<string> {
  let lastError: Error | null = null;
  let attemptedRetries = 0;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await streamChatOnce(
        deps,
        request,
        onChunk,
        onDone,
        onError,
        attempt > 0,
        endpoint,
      );
    } catch (error: unknown) {
      lastError = error instanceof Error ? error : new Error(String(error));
      const isRetryable = RETRYABLE_ERRORS.some((retryableErr) =>
        lastError?.message.includes(retryableErr),
      );

      if (!isRetryable || attempt === maxRetries) {
        await onError(lastError);
        throw lastError;
      }

      const delayMs = Math.min(
        RETRY_BASE_DELAY_MS * 2 ** attempt,
        MAX_RETRY_DELAY_MS,
      );
      attemptedRetries++;
      logger.warn("chat_stream_retrying", {
        attempt: attemptedRetries,
        max_retries: maxRetries,
        delay_ms: delayMs,
        error_message: lastError.message,
      });
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }

  const finalError = lastError || new Error("Stream failed after retries");
  await onError(finalError);
  throw finalError;
}

/** Overall connection timeout (10 min) — covers slow/cold-start operations. */
const STREAM_TIMEOUT_MS = 600_000;
/** No-data inactivity timeout (5 min). */
const INACTIVITY_TIMEOUT_MS = 300_000;

/**
 * Runs a single SSE attempt. Throws on retryable transport errors (so the
 * caller can retry) and surfaces user-facing errors via `onError`.
 */
async function streamChatOnce(
  deps: ChatStreamClient,
  request: ChatRequest,
  onChunk: (text: string) => void | Promise<void>,
  onDone: (fullText: string, conversationId: string) => void | Promise<void>,
  onError: (error: Error) => void | Promise<void>,
  retried: boolean,
  endpoint: string,
): Promise<string> {
  let fullText = "";
  let conversationId = "";
  let streamError: Error | null = null;

  const ctx = {
    platform: request.platform,
    platformUserId: request.platformUserId,
    channelId: request.channelId,
  };

  try {
    const response = await deps.client.post(
      endpoint,
      {
        message: request.message,
        platform: request.platform,
        platform_user_id: request.platformUserId,
        channel_id: request.channelId,
        ...(request.fileIds && request.fileIds.length > 0
          ? { file_ids: request.fileIds }
          : {}),
        ...(request.fileData && request.fileData.length > 0
          ? { file_data: request.fileData }
          : {}),
      },
      {
        responseType: "stream",
        timeout: STREAM_TIMEOUT_MS,
        headers: {
          Accept: "text/event-stream",
          ...deps.userHeaders(ctx),
        },
      },
    );

    const stream = response.data as Readable;
    let buffer = "";
    let finished = false;
    let inactivityTimer: ReturnType<typeof setTimeout> | null = null;
    let receivedKeepalive = false;

    const resetInactivityTimer = (resolve: () => void) => {
      if (inactivityTimer) clearTimeout(inactivityTimer);
      inactivityTimer = setTimeout(async () => {
        if (!finished) {
          finished = true;
          stream.destroy();
          if (fullText) {
            // If we got some content, consider it a success
            await onDone(fullText, conversationId);
          } else {
            // No content after timeout - this is an error
            const errorMsg = receivedKeepalive
              ? "The AI is taking longer than expected. Please try a simpler request or try again later."
              : "Connection timeout - no response from server. Please try again.";
            await onError(new Error(errorMsg));
          }
          resolve();
        }
      }, INACTIVITY_TIMEOUT_MS);
    };

    await new Promise<void>((resolve) => {
      resetInactivityTimer(resolve);

      stream.on("data", async (rawChunk: Buffer) => {
        if (finished) return;
        try {
          resetInactivityTimer(resolve);
          buffer += rawChunk.toString();
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (finished) return;
            const trimmed = line.trim();

            if (!trimmed || !trimmed.startsWith("data: ")) continue;
            const raw = trimmed.slice(6);
            if (raw === "[DONE]") continue;

            try {
              const data = JSON.parse(raw);
              if (data.keepalive) {
                // Server keepalive ping to keep the connection alive
                receivedKeepalive = true;
                continue;
              }
              if (data.error === "not_authenticated") {
                finished = true;
                if (inactivityTimer) clearTimeout(inactivityTimer);
                await onError(new Error("not_authenticated"));
                resolve();
                return;
              }
              if (data.error) {
                finished = true;
                if (inactivityTimer) clearTimeout(inactivityTimer);
                await onError(new Error(data.error));
                resolve();
                return;
              }
              if (data.session_token) {
                deps.storeSessionToken(ctx, data.session_token);
              }
              if (data.text) {
                fullText += data.text;
                onChunk(data.text);
              }
              if (data.done) {
                finished = true;
                if (inactivityTimer) clearTimeout(inactivityTimer);
                conversationId = data.conversation_id || "";
                await onDone(fullText, conversationId);
                resolve();
                return;
              }
            } catch (parseErr) {
              if (!(parseErr instanceof SyntaxError)) {
                finished = true;
                if (inactivityTimer) clearTimeout(inactivityTimer);
                await onError(
                  parseErr instanceof Error
                    ? parseErr
                    : new Error("Stream processing failed"),
                );
                resolve();
                return;
              }
            }
          }
        } catch {
          // Prevent unhandled rejection if a callback throws
          if (!finished) {
            finished = true;
            if (inactivityTimer) clearTimeout(inactivityTimer);
            resolve();
          }
        }
      });

      stream.on("end", async () => {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        try {
          if (!finished) {
            finished = true;
            if (fullText) {
              // Got partial response - return what we have
              await onDone(fullText, conversationId);
            } else if (receivedKeepalive) {
              // Received keepalive but no content - server is working but slow
              await onError(
                new Error(
                  "The AI is processing your request but hasn't responded yet. Please try again.",
                ),
              );
            } else {
              // No keepalive, no content - connection issue
              await onError(
                new Error(
                  "Connection lost before receiving a response. Please try again.",
                ),
              );
            }
          }
        } catch {
          // Prevent unhandled rejection if a callback throws
        } finally {
          resolve();
        }
      });

      stream.on("error", async (err: Error) => {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        try {
          if (!finished) {
            finished = true;
            const isRetryable = RETRYABLE_ERRORS.some((retryableErr) =>
              err.message.includes(retryableErr),
            );

            if (isRetryable && !fullText) {
              // No content received yet — store for re-throw so streamChat can retry
              streamError = err;
            } else {
              // Has partial content or non-retryable — surface to user
              const errorMsg =
                err.message.includes("ECONNRESET") ||
                err.message.includes("socket hang up")
                  ? "Connection interrupted. Please try again."
                  : err.message.includes("timeout")
                    ? "Request timed out. The server may be busy - please try again."
                    : err.message;
              await onError(new Error(errorMsg));
            }
          }
        } catch {
          // Prevent unhandled rejection if callback throws
        } finally {
          resolve();
        }
      });
    });
  } catch (error: unknown) {
    const status = getHttpStatus(error);

    if (status === 401 && !retried) {
      deps.clearSessionToken(ctx);
      return streamChatOnce(
        deps,
        request,
        onChunk,
        onDone,
        onError,
        true,
        endpoint,
      );
    }

    // Re-throw so streamChat can classify the error and retry if appropriate
    throw error;
  }

  // Re-throw retryable mid-stream errors so streamChat can retry them.
  // These are stored rather than thrown inside the stream event handler because
  // stream errors resolve the promise (not reject it).
  if (streamError) {
    throw streamError;
  }

  return conversationId;
}
