import { MediaReadTimeoutError } from "./media";
import { readStreamBytesCapped } from "./stream-bytes";

export async function readResponseBytesCapped(
  response: Response,
  maxBytes: number,
  source: string,
  timeoutMs?: number,
): Promise<Uint8Array> {
  if (!response.ok) {
    throw Object.assign(
      new Error(`${source} download failed (${response.status})`),
      { status: response.status },
    );
  }
  if (!response.body) {
    throw new Error(`${source} download returned no body`);
  }
  const { bytes, timedOut } = await readStreamBytesCapped(
    response.body,
    maxBytes,
    timeoutMs,
  );
  if (timedOut) {
    throw new MediaReadTimeoutError(`${source} download timed out`);
  }
  return bytes;
}

export async function fetchBytesCapped(
  url: string,
  maxBytes: number,
  source: string,
  timeoutMs?: number,
): Promise<Uint8Array> {
  const controller =
    timeoutMs === undefined ? undefined : new AbortController();
  const timer =
    controller === undefined
      ? undefined
      : setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(url, { signal: controller?.signal });
    } catch (err) {
      // The controller is armed solely for our own timeout (no caller-supplied
      // signal feeds it), so any abort it produces IS the timeout.
      if (controller?.signal.aborted) {
        throw new MediaReadTimeoutError(`${source} download timed out`);
      }
      throw err;
    }
    return await readResponseBytesCapped(response, maxBytes, source, timeoutMs);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
