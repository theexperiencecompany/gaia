import { WEBHOOK_BODY_READ_TIMEOUT_MS } from "./constants";

/** Sentinel returned by {@link readBodyBounded} when the body exceeds the cap. */
export const BODY_TOO_LARGE = Symbol("body-too-large");

/** Sentinel returned by {@link readBodyBounded} when the read deadline elapses. */
export const BODY_READ_TIMEOUT = Symbol("body-read-timeout");

/**
 * Reads a request body stream into a UTF-8 string, aborting as soon as the
 * accumulated bytes exceed {@link maxBytes} so an oversized body is never fully
 * buffered ({@link BODY_TOO_LARGE}), or once {@link timeoutMs} of wall-clock
 * time elapses ({@link BODY_READ_TIMEOUT}) so a slow-trickle or stalled client
 * cannot hold the reader open indefinitely (slowloris). On timeout the reader
 * is cancelled, which resolves the in-flight `read()` and unblocks the loop.
 *
 * The bytes are accumulated exactly as received and decoded with a strict
 * UTF-8 {@link TextDecoder}, so the returned string re-encodes byte-for-byte to
 * the original body — a requirement for the HMAC signature check downstream.
 */
export async function readBodyBounded(
  request: Request,
  maxBytes: number,
  timeoutMs: number = WEBHOOK_BODY_READ_TIMEOUT_MS,
): Promise<string | typeof BODY_TOO_LARGE | typeof BODY_READ_TIMEOUT> {
  const body = request.body;
  if (!body) return "";

  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    // Cancelling resolves the pending read() with done=true, unblocking the
    // loop even if the stream has stalled with no bytes arriving.
    void reader.cancel();
  }, timeoutMs);
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        return BODY_TOO_LARGE;
      }
      chunks.push(value);
    }
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }

  if (timedOut) return BODY_READ_TIMEOUT;

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8").decode(bytes);
}
