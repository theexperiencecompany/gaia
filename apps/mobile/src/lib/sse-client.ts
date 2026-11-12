import EventSource from "react-native-sse";
import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { API_BASE_URL, CLIENT_TYPE_HEADERS } from "./constants";

/** The server sends a keepalive every 15 s; three missed means the connection is dead. */
export const EVENT_STREAM_STALL_MS = 45_000;

/** The stream was refused with an HTTP status (react-native-sse reports it as an error event). */
export class EventStreamHttpError extends Error {
  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`Event stream refused with HTTP ${status}`);
    this.name = "EventStreamHttpError";
  }
}

function getTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

/**
 * Read one GET event stream until it ends: resolves when the server closes it or
 * the signal aborts, rejects when it is refused, fails, or goes silent. Each
 * non-empty `data:` payload is handed over raw. Reconnecting is the caller's job.
 */
export async function readEventStream(
  endpoint: string,
  onData: (raw: string) => void,
  signal: AbortSignal,
): Promise<void> {
  const token = await getAuthToken();
  if (!token) throw new Error("Not authenticated");
  if (signal.aborted) return;

  await new Promise<void>((resolve, reject) => {
    const es = new EventSource(`${API_BASE_URL}${endpoint}`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "text/event-stream",
        "x-timezone": getTimezone(),
        ...CLIENT_TYPE_HEADERS,
      },
      pollingInterval: 0,
      timeoutBeforeConnection: 0,
    });
    let stall: ReturnType<typeof setTimeout> | null = null;

    const finish = (error: Error | null) => {
      if (stall) clearTimeout(stall);
      signal.removeEventListener("abort", onAbort);
      es.removeAllEventListeners();
      es.close();
      if (error) reject(error);
      else resolve();
    };
    const armStall = () => {
      if (stall) clearTimeout(stall);
      stall = setTimeout(
        () => finish(new Error("Event stream went silent")),
        EVENT_STREAM_STALL_MS,
      );
    };
    const onAbort = () => finish(null);

    signal.addEventListener("abort", onAbort);
    armStall();
    es.addEventListener("message", (event) => {
      armStall();
      if (event.data) onData(event.data);
    });
    es.addEventListener("error", (event) => {
      if ("xhrStatus" in event && event.xhrStatus >= 400) {
        finish(new EventStreamHttpError(event.xhrStatus, event.message));
        return;
      }
      finish(
        new Error(
          "message" in event && event.message
            ? event.message
            : "Event stream failed",
        ),
      );
    });
    es.addEventListener("close", () => finish(null));
  });
}
