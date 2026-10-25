/**
 * Reads of a running instance's HTTP endpoints, shared by `gaia doctor` and
 * `gaia up`'s finish summary.
 * @module lib/setup-endpoints
 */

const HTTP_TIMEOUT_MS = 5000;

export async function fetchWithTimeout(
  url: string,
  init?: RequestInit,
  timeoutMs: number = HTTP_TIMEOUT_MS,
): Promise<Response> {
  return fetch(url, { ...init, signal: AbortSignal.timeout(timeoutMs) });
}

/** A public setup endpoint's JSON body, or why it could not be read. */
export async function readSetupEndpoint<T>(
  apiUrl: string,
  endpoint: "status" | "catalog",
  timeoutMs: number = HTTP_TIMEOUT_MS,
): Promise<{ data: T } | { detail: string }> {
  try {
    const res = await fetchWithTimeout(
      `${apiUrl}/setup/${endpoint}`,
      undefined,
      timeoutMs,
    );
    if (!res.ok) {
      return { detail: `HTTP ${res.status} from /api/v1/setup/${endpoint}` };
    }
    return { data: (await res.json()) as T };
  } catch {
    return { detail: `Could not read setup ${endpoint}` };
  }
}
