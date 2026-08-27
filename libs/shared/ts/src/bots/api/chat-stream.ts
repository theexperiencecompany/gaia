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
  done?: boolean;
  conversation_id?: string;
}

/** Maps a raw transport error message to the user-facing copy to surface. */
function toStreamErrorMessage(message: string): string {
  if (message.includes("ECONNRESET") || message.includes("socket hang up")) {
    return "Connection interrupted. Please try again.";
  }
  if (message.includes("timeout")) {
    return "Request timed out. The server may be busy - please try again.";
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
  // Text streamed since the last message boundary. It only joins `fullText`
  // once the backend confirms the message it belongs to was a real reply —
  // a handoff preamble is streamed first and retracted afterwards, and
  // `fullText` is the whole reply on platforms that render nothing until the
  // stream ends (Discord, WhatsApp, iMessage).
  let pendingText = "";
  let conversationId = "";
  let streamError: Error | null = null;

  const keepPendingText = (): void => {
    if (!pendingText) return;
    fullText = fullText
      ? `${fullText}${NEW_MESSAGE_BREAK_TOKEN}${pendingText}`
      : pendingText;
    pendingText = "";
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
          keepPendingText();
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
        if (frame.text) {
          pendingText += frame.text;
          await onChunk(frame.text);
        }
        if (frame.message_boundary) {
          const { discarded } = frame.message_boundary;
          if (discarded) {
            pendingText = "";
          } else {
            keepPendingText();
          }
          // Both halves are announced. A kept boundary is what tells a
          // streaming platform its message is final and may now be split into
          // bubbles — do it any earlier and a retraction arriving next has
          // nothing left it can take back.
          await onMessageBoundary?.(discarded);
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
          keepPendingText();
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
        if (!trimmed || !trimmed.startsWith("data: ")) return false;
        const raw = trimmed.slice(6);
        if (raw === "[DONE]") return false;

        try {
          return await handleFrame(JSON.parse(raw) as SseFrame);
        } catch (parseErr) {
          if (parseErr instanceof SyntaxError) return false;
          finish();
          await onError(
            parseErr instanceof Error
              ? parseErr
              : new Error("Stream processing failed"),
          );
          return true;
        }
      };

      // Frames already received but not yet applied. Processing a chunk is
      // async (every handler may await), so it yields — and `end` fires on the
      // very next tick when the response arrives in one piece, which is the
      // normal case for a short reply. Without something to wait on, `end`
      // flipped `finished` mid-loop and every frame after the first `await` was
      // silently dropped: an approval prompt, a rate-limit notice or a message
      // boundary sharing a TCP chunk with the text before it simply vanished.
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
        } catch {
          // Prevent unhandled rejection if a callback throws
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
            keepPendingText();
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
            keepPendingText();
            const isRetryable = RETRYABLE_ERRORS.some((retryableErr) =>
              err.message.includes(retryableErr),
            );

            if (isRetryable && !fullText) {
              // No content received yet — store for re-throw so streamChat can retry
              streamError = err;
            } else if (fullText) {
              // The connection died, but the answer is already assembled here.
              // Deliver it exactly as the `end` handler does — replacing real
              // content with an error card loses a reply the user had earned,
              // and on a non-streaming platform (Discord/WhatsApp render only
              // at onDone) it means they see nothing at all.
              await onDone(fullText, conversationId);
            } else {
              await onError(new Error(toStreamErrorMessage(err.message)));
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
