/** Sentinel returned by {@link readBodyBounded} when the body exceeds the cap. */
export const BODY_TOO_LARGE = Symbol("body-too-large");

/**
 * Reads a request body stream into a UTF-8 string, aborting as soon as the
 * accumulated bytes exceed {@link maxBytes} so an oversized body is never fully
 * buffered. Returns {@link BODY_TOO_LARGE} on overflow.
 *
 * The bytes are accumulated exactly as received and decoded with a strict
 * UTF-8 {@link TextDecoder}, so the returned string re-encodes byte-for-byte to
 * the original body — a requirement for the HMAC signature check downstream.
 */
export async function readBodyBounded(
  request: Request,
  maxBytes: number,
): Promise<string | typeof BODY_TOO_LARGE> {
  const body = request.body;
  if (!body) return "";

  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
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
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8").decode(bytes);
}
