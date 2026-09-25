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
import type { ApprovalRequestData } from "../../chat";
import { NEW_MESSAGE_BREAK_TOKEN } from "../../utils/messageBreakUtils";
import type { ChatRequest } from "../types";
import { getHttpStatus } from "../utils/logger";
import { couldBecomeReactDirective } from "../utils/react-directive";
import { wideLog } from "../utils/wide-events";
import type {
  ApprovalUpdateHandler,
  ChatStreamClient,
  MessageBoundary,
  MessageBoundaryHandler,
  NoticeHandler,
} from "./chat-stream.types";

export type {
  ApprovalUpdateHandler,
  ChatStreamClient,
  MessageBoundaryHandler,
  NoticeHandler,
} from "./chat-stream.types";

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
  onApprovalUpdate?: ApprovalUpdateHandler,
  onMessageBoundary?: MessageBoundaryHandler,
  onNotice?: NoticeHandler,
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
        onApprovalUpdate,
        onMessageBoundary,
        onNotice,
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
      wideLog.warning("chat_stream_retrying", {
        attempt: attemptedRetries,
        max_retries: maxRetries,
        delay_ms: delayMs,
        error: lastError.message,
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

export const BOT_STREAM_ERROR = {
  notAuthenticated: "not_authenticated",
  planRequired: "plan_required",
} as const;

/** The subset of an SSE `data:` frame the streamer acts on. */
interface SseFrame {
  keepalive?: boolean;
  error?: string;
  session_token?: string;
  approval?: ApprovalRequestData;
  notice?: { text: string };
  text?: string;
  message_boundary?: MessageBoundary;
  emoji_ack?: { emoji: string; reacts_to_message_id?: string };
  done?: boolean;
  conversation_id?: string;
}

/** Maps a raw transport error message to the user-facing copy to surface. */
function toStreamErrorMessage(message: string): string {
  if (message.includes("ECONNRESET") || message.includes("socket hang up")) {
    return "Connection interrupted. Please try again.";
  }
  if (message.includes("timeout")) {
    return "Request timed out. The server might be busy, so try again.";
  }
  return message;
}

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
  onApprovalUpdate?: ApprovalUpdateHandler,
  onMessageBoundary?: MessageBoundaryHandler,
  onNotice?: NoticeHandler,
): Promise<string> {
  let fullText = "";
  // Text streamed since the last message boundary; joins `fullText` only once the backend
  // confirms the message was a real reply (a handoff preamble streams first and can be
  // retracted). `fullText` is the whole reply on render-at-end platforms (Discord/WhatsApp/iMessage).
  let pendingText = "";
  // How much of `pendingText` has already been forwarded via `onChunk`. Text
  // held back as a possible REACT directive lags the buffered whole.
  let forwardedLength = 0;
  // Held text from already-kept messages, still owed to `onChunk` unless an
  // `emoji_ack` replaces the turn.
  let heldKeptText = "";
  let conversationId = "";
  let streamError: Error | null = null;

  /** The turn as the backend's complete_message sees it: kept messages plus the one in flight. */
  const joinTurn = (kept: string, inFlight: string): string =>
    kept ? `${kept}${NEW_MESSAGE_BREAK_TOKEN}${inFlight}` : inFlight;

  const keepPendingText = (): void => {
    heldKeptText += pendingText.slice(forwardedLength);
    if (pendingText) fullText = joinTurn(fullText, pendingText);
    pendingText = "";
    forwardedLength = 0;
  };

  /** Forward every held-back chunk — the turn is proven not to be a REACT directive. */
  const releaseHeldText = async (): Promise<void> => {
    const held = heldKeptText + pendingText.slice(forwardedLength);
    heldKeptText = "";
    forwardedLength = pendingText.length;
    if (held) await onChunk(held);
  };

  /** End of turn with no `emoji_ack`: whatever was held is an ordinary reply. */
  const settleTurnText = async (): Promise<void> => {
    await releaseHeldText();
    keepPendingText();
  };

  // Held while the turn could still be the REACT control line, so per-chunk
  // adapters never paint the directive; a lookalike (`Real…`) flushes whole
  // once the next frame disambiguates it.
  const applyText = async (text: string): Promise<void> => {
    pendingText += text;
    if (!couldBecomeReactDirective(joinTurn(fullText, pendingText))) {
      await releaseHeldText();
    }
  };

  // The `REACT: <emoji>` ack: the delivered message is the bare emoji, not the
  // raw directive, which was never forwarded — so the emoji is the turn's one
  // chunk, or streaming platforms (rendering from onChunk) would show nothing.
  const applyEmojiAck = async (emoji: string): Promise<void> => {
    pendingText = "";
    forwardedLength = 0;
    heldKeptText = "";
    fullText = emoji;
    if (fullText) await onChunk(fullText);
  };

  const applyMessageBoundary = async (discarded: boolean): Promise<void> => {
    if (discarded) {
      pendingText = "";
      forwardedLength = 0;
    } else {
      keepPendingText();
      // Whatever follows joins after a break, so this decides it now.
      if (!couldBecomeReactDirective(joinTurn(fullText, ""))) {
        await releaseHeldText();
      }
    }
    // A kept boundary tells a streaming platform its message is final and may now be
    // split into bubbles — announcing any earlier would leave nothing for a retraction
    // arriving next to take back.
    await onMessageBoundary?.(discarded);
  };

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
        is_dm: request.isDm ?? false,
        ...(request.platformMessageId
          ? { platform_message_id: request.platformMessageId }
          : {}),
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
          await settleTurnText();
          if (fullText) {
            // If we got some content, consider it a success
            await onDone(fullText, conversationId);
          } else {
            // No content after timeout - this is an error
            const errorMsg = receivedKeepalive
              ? "The AI is taking longer than expected. Please try a simpler request or try again later."
              : "Connection timed out with no response from the server. Try again.";
            await onError(new Error(errorMsg));
          }
          resolve();
        }
      }, INACTIVITY_TIMEOUT_MS);
    };

    await new Promise<void>((resolve) => {
      resetInactivityTimer(resolve);

      const finish = (): void => {
        finished = true;
        if (inactivityTimer) clearTimeout(inactivityTimer);
      };

      // The frames that carry content: none of them ends the stream, so they
      // are applied in order and the caller keeps reading. Kept apart from the
      // terminal frames below so each half stays readable as it grows.
      const applyFrameUpdate = async (frame: SseFrame): Promise<void> => {
        if (frame.session_token) {
          deps.storeSessionToken(ctx, frame.session_token);
        }
        if (frame.approval) {
          await onApprovalUpdate?.(frame.approval);
        }
        if (frame.notice) {
          await onNotice?.(frame.notice.text);
        }
        if (frame.text) await applyText(frame.text);
        if (frame.emoji_ack) await applyEmojiAck(frame.emoji_ack.emoji);
        if (frame.message_boundary) {
          await applyMessageBoundary(frame.message_boundary.discarded);
        }
      };

      // Applies one parsed SSE frame's side effects. Returns true once the
      // stream is complete (done or error), signalling the caller to resolve.
      const handleFrame = async (frame: SseFrame): Promise<boolean> => {
        if (frame.keepalive) {
          // Server keepalive ping to keep the connection alive
          receivedKeepalive = true;
          return false;
        }
        if (frame.error === BOT_STREAM_ERROR.notAuthenticated) {
          finish();
          await onError(new Error(BOT_STREAM_ERROR.notAuthenticated));
          return true;
        }
        if (frame.error) {
          finish();
          await onError(new Error(frame.error));
          return true;
        }
        await applyFrameUpdate(frame);
        if (frame.done) {
          finish();
          await settleTurnText();
          conversationId = frame.conversation_id || "";
          await onDone(fullText, conversationId);
          return true;
        }
        return false;
      };

      // Processes one raw SSE line. Returns true once the stream is complete,
      // signalling the caller to resolve and stop reading.
      const processLine = async (line: string): Promise<boolean> => {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) return false;
        const raw = trimmed.slice(6);
        if (raw === "[DONE]") return false;

        try {
          return await handleFrame(JSON.parse(raw) as SseFrame);
        } catch (parseErr) {
          if (parseErr instanceof SyntaxError) {
            wideLog.warning("chat_stream_frame_unparseable", {
              bytes: raw.length,
            });
            return false;
          }
          finish();
          await onError(
            parseErr instanceof Error
              ? parseErr
              : new Error("Stream processing failed"),
          );
          return true;
        }
      };

      // Frames already received but not yet applied. Chunk processing is async (handlers may
      // await), so `end` can fire on the next tick before it finishes — without something to
      // wait on, `finished` flipped mid-loop and every frame after the first `await` was dropped.
      let draining: Promise<void> = Promise.resolve();

      const drainChunk = async (rawChunk: Buffer): Promise<void> => {
        if (finished) return;
        try {
          resetInactivityTimer(resolve);
          buffer += rawChunk.toString();
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (finished) return;
            if (await processLine(line)) {
              resolve();
              return;
            }
          }
        } catch (callbackError) {
          // A throwing callback must not become an unhandled rejection — but it is recorded.
          wideLog.error(
            "chat_stream_callback_failed",
            undefined,
            callbackError,
          );
          if (!finished) {
            finish();
            resolve();
          }
        }
      };

      stream.on("data", (rawChunk: Buffer) => {
        draining = draining.then(() => drainChunk(rawChunk));
      });

      stream.on("end", async () => {
        await draining;
        if (inactivityTimer) clearTimeout(inactivityTimer);
        try {
          if (!finished) {
            finished = true;
            await settleTurnText();
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
        } catch (callbackError) {
          // A throwing callback must not become an unhandled rejection — but it is recorded.
          wideLog.error(
            "chat_stream_callback_failed",
            undefined,
            callbackError,
          );
        } finally {
          resolve();
        }
      });

      stream.on("error", async (err: Error) => {
        if (inactivityTimer) clearTimeout(inactivityTimer);
        try {
          if (!finished) {
            finished = true;
            await settleTurnText();
            const isRetryable = RETRYABLE_ERRORS.some((retryableErr) =>
              err.message.includes(retryableErr),
            );

            if (isRetryable && !fullText) {
              // No content received yet — store for re-throw so streamChat can retry
              streamError = err;
            } else if (fullText) {
              // The connection died but the answer is already assembled — deliver it exactly as
              // the `end` handler does. An error card here would lose an earned reply, and on a
              // non-streaming platform (Discord/WhatsApp render only at onDone) show nothing at all.
              await onDone(fullText, conversationId);
            } else {
              await onError(new Error(toStreamErrorMessage(err.message)));
            }
          }
        } catch (callbackError) {
          // A throwing callback must not become an unhandled rejection — but it is recorded.
          wideLog.error(
            "chat_stream_callback_failed",
            undefined,
            callbackError,
          );
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
        onApprovalUpdate,
        onMessageBoundary,
        // Dropped here until now: a stale session token cost the retried
        // attempt every rate-limit notice it produced.
        onNotice,
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
