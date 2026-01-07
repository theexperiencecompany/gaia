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
}

function getTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

export async function createSSEConnection(
  endpoint: string,
  callbacks: SSECallbacks,
  options: SSEOptions = {},
): Promise<AbortController> {
  const controller = new AbortController();
  const token = await getAuthToken();

  if (!token) {
    callbacks.onError?.(new Error("Not authenticated"));
    return controller;
  }

  const url = `${API_BASE_URL}${endpoint}`;

  const es = new EventSource(url, {
    method: "POST",
    headers: {
      Cookie: `wos_session=${token}`,
      Accept: "text/event-stream",
      "Content-Type": "application/json",
      "x-timezone": getTimezone(),
      ...options.headers,
    },
    body: options.body ? JSON.stringify(options.body) : undefined,
    pollingInterval: 0, // Disable reconnections
    timeoutBeforeConnection: 0, // Connect immediately
  });

  es.addEventListener("open", () => {
    console.log("[SSE] Connection opened");
  });

  es.addEventListener("message", (event) => {
    if (event.data) {
      callbacks.onMessage({
        data: event.data,
        id: event.lastEventId ?? undefined,
      });
    }
  });

  es.addEventListener("error", (event) => {
    console.error("[SSE] Error:", event);
    const errorMessage =
      "message" in event ? event.message : "SSE connection error";
    callbacks.onError?.(new Error(errorMessage || "SSE connection error"));
  });

  es.addEventListener("close", () => {
    console.log("[SSE] Connection closed");
    callbacks.onClose?.();
  });

  // Handle abort
  controller.signal.addEventListener("abort", () => {
    es.removeAllEventListeners();
    es.close();
    callbacks.onClose?.();
  });

  return controller;
}
