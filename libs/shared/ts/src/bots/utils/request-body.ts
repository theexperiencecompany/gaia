import { readStreamBytesCapped } from "./stream-bytes";

/** Sentinel returned when the body exceeds the cap. */
export const BODY_TOO_LARGE = Symbol("body-too-large");

/** Sentinel returned when the read deadline elapses. */
export const BODY_READ_TIMEOUT = Symbol("body-read-timeout");

/**
 * Maximum accepted size (in bytes) for a webhook request body. Platform
 * webhook payloads are small JSON events; a body larger than this is rejected
 * with HTTP 413 before it is fully read into memory, preventing a
 * memory-exhaustion DoS from an oversized request.
 */
export const WEBHOOK_MAX_BODY_BYTES = 256 * 1024;

/**
 * Wall-clock deadline (ms) for reading a webhook request body. Bounds the
 * total time a client can hold the reader open: a client that trickles bytes
 * slowly, or stalls entirely, while staying under {@link
 * WEBHOOK_MAX_BODY_BYTES} would otherwise tie up the connection indefinitely
 * (slowloris-style). Webhook payloads arrive in milliseconds, so 10s is generous.
 */
export const WEBHOOK_BODY_READ_TIMEOUT_MS = 10_000;

/**
 * Reads a request body stream into a byte array, aborting as soon as the
 * accumulated bytes exceed {@link maxBytes} so an oversized body is never fully
 * buffered ({@link BODY_TOO_LARGE}), or once {@link timeoutMs} of wall-clock
 * time elapses ({@link BODY_READ_TIMEOUT}) so a slow-trickle or stalled client
 * cannot hold the reader open indefinitely (slowloris). On timeout the reader
 * is cancelled, which resolves the in-flight `read()` and unblocks the loop.
 *
 * The bytes are returned exactly as received — a requirement for HMAC
 * signature checks and protobuf decoding downstream. One byte past the cap is
 * read so that a body sitting exactly on the limit is still accepted.
 */
export async function readBodyBytesBounded(
  request: Request,
  maxBytes: number,
  timeoutMs: number = WEBHOOK_BODY_READ_TIMEOUT_MS,
): Promise<Uint8Array | typeof BODY_TOO_LARGE | typeof BODY_READ_TIMEOUT> {
  const body = request.body;
  if (!body) return new Uint8Array(0);

  const { bytes, timedOut } = await readStreamBytesCapped(
    body,
    maxBytes + 1,
    timeoutMs,
  );
  if (bytes.byteLength > maxBytes) return BODY_TOO_LARGE;
  if (timedOut) return BODY_READ_TIMEOUT;
  return bytes;
}

/**
 * String variant of {@link readBodyBytesBounded}: decodes the bytes with a
 * strict UTF-8 {@link TextDecoder}, so the returned string re-encodes
 * byte-for-byte to the original body for JSON-body HMAC checks.
 */
export async function readBodyBounded(
  request: Request,
  maxBytes: number,
  timeoutMs: number = WEBHOOK_BODY_READ_TIMEOUT_MS,
): Promise<string | typeof BODY_TOO_LARGE | typeof BODY_READ_TIMEOUT> {
  const bytes = await readBodyBytesBounded(request, maxBytes, timeoutMs);
  if (bytes === BODY_TOO_LARGE || bytes === BODY_READ_TIMEOUT) return bytes;
  return new TextDecoder("utf-8").decode(bytes);
}
