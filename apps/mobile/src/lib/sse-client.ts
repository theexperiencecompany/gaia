import EventSource from "react-native-sse";
import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { API_BASE_URL } from "./constants";

export interface SSEEvent {
  id?: string;
  event?: string;
  data: string;
}

export interface SSECallbacks {
  onMessage: (event: SSEEvent) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
}

export interface SSEOptions {
  headers?: Record<string, string>;
  body?: unknown;
  maxRetries?: number;
  initialRetryDelayMs?: number;
}

const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_INITIAL_RETRY_DELAY_MS = 1000;
const MAX_RETRY_DELAY_MS = 16000;

function getTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

function computeRetryDelay(attempt: number, initialDelayMs: number): number {
  const exponential = initialDelayMs * 2 ** attempt;
  const capped = Math.min(exponential, MAX_RETRY_DELAY_MS);
  const jitter = capped * 0.2 * Math.random();
  return Math.round(capped + jitter);
}

export async function createSSEConnection(
  endpoint: string,
  callbacks: SSECallbacks,
  options: SSEOptions = {},
): Promise<AbortController> {
  const controller = new AbortController();
  const {
    maxRetries = DEFAULT_MAX_RETRIES,
    initialRetryDelayMs = DEFAULT_INITIAL_RETRY_DELAY_MS,
  } = options;

  let retryCount = 0;
  let retryTimeoutId: ReturnType<typeof setTimeout> | null = null;
  let hasReceivedData = false;
  let isDone = false;

  const cleanup = () => {
    isDone = true;
    if (retryTimeoutId !== null) {
      clearTimeout(retryTimeoutId);
      retryTimeoutId = null;
    }
  };

  controller.signal.addEventListener("abort", cleanup);

  async function connect(): Promise<void> {
    if (controller.signal.aborted || isDone) return;

    const token = await getAuthToken();
    if (!token) {
      callbacks.onError?.(new Error("Not authenticated"));
      cleanup();
      return;
    }

    const url = `${API_BASE_URL}${endpoint}`;

    const es = new EventSource(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        "x-timezone": getTimezone(),
        ...options.headers,
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      pollingInterval: 0,
      timeoutBeforeConnection: 0,
    });

    const handleAbort = () => {
      es.removeAllEventListeners();
      es.close();
      callbacks.onClose?.();
    };

    controller.signal.addEventListener("abort", handleAbort);

    es.addEventListener("open", () => {});

    es.addEventListener("message", (event) => {
      if (controller.signal.aborted || isDone) return;
      if (event.data) {
        hasReceivedData = true;
        retryCount = 0;
        callbacks.onMessage({
          data: event.data,
          id: event.lastEventId ?? undefined,
        });
      }
    });

    es.addEventListener("error", (event) => {
      if (controller.signal.aborted || isDone) return;

      controller.signal.removeEventListener("abort", handleAbort);
      es.removeAllEventListeners();
      es.close();

      if (retryCount < maxRetries) {
        retryCount += 1;
        const delay = computeRetryDelay(retryCount - 1, initialRetryDelayMs);
        console.warn(
          `[SSE] Connection error (attempt ${retryCount}/${maxRetries}), retrying in ${delay}ms`,
          event,
        );
        retryTimeoutId = setTimeout(() => {
          retryTimeoutId = null;
          void connect();
        }, delay);
      } else {
        const errorMessage =
          "message" in event
            ? (event as { message?: string }).message
            : undefined;
        callbacks.onError?.(
          new Error(
            errorMessage || `SSE connection failed after ${maxRetries} retries`,
          ),
        );
        cleanup();
      }
    });

    es.addEventListener("close", () => {
      if (controller.signal.aborted || isDone) return;
      controller.signal.removeEventListener("abort", handleAbort);
      if (hasReceivedData || retryCount >= maxRetries) {
        callbacks.onClose?.();
        cleanup();
      } else {
        retryCount += 1;
        const delay = computeRetryDelay(retryCount - 1, initialRetryDelayMs);
        console.warn(
          `[SSE] Unexpected close (attempt ${retryCount}/${maxRetries}), retrying in ${delay}ms`,
        );
        retryTimeoutId = setTimeout(() => {
          retryTimeoutId = null;
          void connect();
        }, delay);
      }
    });
  }

  await connect();
  return controller;
}
