export async function readStreamBytesCapped(
  stream: ReadableStream<Uint8Array>,
  maxBytes: number,
  timeoutMs?: number,
): Promise<{ bytes: Uint8Array; timedOut: boolean }> {
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let ended = false;
  let timedOut = false;
  const timer =
    timeoutMs === undefined
      ? undefined
      : setTimeout(() => {
          timedOut = true;
          void reader.cancel();
        }, timeoutMs);

  try {
    while (total < maxBytes) {
      const { done, value } = await reader.read();
      if (done) {
        ended = true;
        break;
      }
      if (!value) continue;

      const room = maxBytes - total;
      chunks.push(room < value.byteLength ? value.subarray(0, room) : value);
      total += Math.min(room, value.byteLength);
    }
    if (!ended) await reader.cancel();
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { bytes, timedOut };
}
