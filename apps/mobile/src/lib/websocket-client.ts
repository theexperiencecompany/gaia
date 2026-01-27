import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { API_ORIGIN } from "./constants";

/**
 * WebSocket message types from the backend
 */
export type WebSocketMessageType =
  | "notification.delivered"
  | "notification.updated"
  | "notification.read"
  | "onboarding.complete"
  | "integration.connected"
  | "integration.disconnected"
  | string; // Allow for future message types

/**
 * Base WebSocket message structure
 */
export interface WebSocketMessage {
  type: WebSocketMessageType;
  [key: string]: unknown;
}

export interface NotificationDeliveredMessage extends WebSocketMessage {
  type: "notification.delivered";
  notification: {
    id: string;
    title: string;
    body: string;
    [key: string]: unknown;
  };
}

export interface NotificationUpdatedMessage extends WebSocketMessage {
  type: "notification.updated";
  notification_id: string;
  updates: Record<string, unknown>;
}

export interface NotificationReadMessage extends WebSocketMessage {
  type: "notification.read";
  notification_id: string;
}

export type NotificationMessage =
  | NotificationDeliveredMessage
  | NotificationUpdatedMessage
  | NotificationReadMessage;

/**
 * WebSocket connection state
 */
export type WebSocketState =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

/**
 * Callbacks for WebSocket events
 */
export interface WebSocketCallbacks {
  onMessage?: (message: WebSocketMessage) => void;
  onNotification?: (message: NotificationMessage) => void;
  onStateChange?: (state: WebSocketState) => void;
  onError?: (error: Error) => void;
}

/**
 * Configuration options for WebSocket connection
 */
export interface WebSocketConfig {
  /** Auto-reconnect on disconnect (default: true) */
  autoReconnect?: boolean;
  /** Reconnect delay in ms (default: 3000) */
  reconnectDelay?: number;
  /** Maximum reconnection attempts (default: 5) */
  maxReconnectAttempts?: number;
  /** Heartbeat interval in ms to keep connection alive (default: 30000) */
  heartbeatInterval?: number;
}

const DEFAULT_CONFIG: Required<WebSocketConfig> = {
  autoReconnect: true,
  reconnectDelay: 3000,
  maxReconnectAttempts: 5,
  heartbeatInterval: 30000,
};

/**
 * Creates and manages a WebSocket connection to the backend.
 *
 * The WebSocket sends the auth token via the Sec-WebSocket-Protocol header
 * (subprotocol) for security, preventing token exposure in logs and referrers.
 *
 * @example
 * ```ts
 * const ws = await createWebSocketConnection({
 *   onMessage: (msg) => console.log('Received:', msg),
 *   onNotification: (notification) => {
 *     // Handle notification-specific messages
 *     if (notification.type === 'notification.delivered') {
 *       showToast(notification.notification.title);
 *     }
 *   },
 *   onStateChange: (state) => console.log('State:', state),
 * });
 *
 * // Later, to disconnect:
 * ws.disconnect();
 * ```
 */
export async function createWebSocketConnection(
  callbacks: WebSocketCallbacks,
  config: WebSocketConfig = {},
): Promise<WebSocketController> {
  const finalConfig = { ...DEFAULT_CONFIG, ...config };
  const controller = new WebSocketController(callbacks, finalConfig);
  await controller.connect();
  return controller;
}

/**
 * WebSocket connection controller
 * Manages the lifecycle of a WebSocket connection with auto-reconnect,
 * heartbeat, and message handling.
 */
export class WebSocketController {
  private ws: WebSocket | null = null;
  private callbacks: WebSocketCallbacks;
  private config: Required<WebSocketConfig>;
  private state: WebSocketState = "disconnected";
  private reconnectAttempts = 0;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private heartbeatIntervalId: ReturnType<typeof setInterval> | null = null;
  private isManualDisconnect = false;

  constructor(
    callbacks: WebSocketCallbacks,
    config: Required<WebSocketConfig>,
  ) {
    this.callbacks = callbacks;
    this.config = config;
  }

  /**
   * Connect to the WebSocket server
   */
  async connect(): Promise<void> {
    if (this.ws && this.state === "connected") {
      return;
    }

    const token = await getAuthToken();
    if (!token) {
      this.setState("error");
      this.callbacks.onError?.(new Error("Not authenticated"));
      return;
    }

    this.isManualDisconnect = false;
    this.setState("connecting");

    // Validate API_ORIGIN before attempting connection
    if (
      !API_ORIGIN ||
      typeof API_ORIGIN !== "string" ||
      !API_ORIGIN.startsWith("http")
    ) {
      this.setState("error");
      this.callbacks.onError?.(
        new Error(
          "Missing or invalid API_ORIGIN: cannot establish WebSocket connection",
        ),
      );
      return;
    }

    try {
      // Build WebSocket URL
      // Convert http(s):// to ws(s)://
      const wsOrigin = API_ORIGIN.replace(/^http/, "ws");
      const wsUrl = `${wsOrigin}/api/v1/ws/connect`;

      // Create WebSocket connection
      // Pass token via subprotocol header instead of query string for security
      // This prevents token exposure in server logs and referrers
      // Format: ['Bearer', token] - server will extract token from Sec-WebSocket-Protocol
      this.ws = new WebSocket(wsUrl, ["Bearer", token]);

      this.setupEventHandlers();
    } catch (error) {
      this.setState("error");
      this.callbacks.onError?.(
        error instanceof Error ? error : new Error(String(error)),
      );
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from the WebSocket server
   */
  disconnect(): void {
    this.isManualDisconnect = true;
    this.cleanup();
    this.setState("disconnected");
  }

  /**
   * Get current connection state
   */
  getState(): WebSocketState {
    return this.state;
  }

  /**
   * Check if connected
   */
  isConnected(): boolean {
    return this.state === "connected";
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      this.setState("connected");
      this.reconnectAttempts = 0;
      this.startHeartbeat();
    };

    this.ws.onmessage = (event: WebSocketMessageEvent) => {
      try {
        const data = typeof event.data === "string" ? event.data : "";
        const message = JSON.parse(data) as WebSocketMessage;

        // Call general message handler
        this.callbacks.onMessage?.(message);

        // Call notification-specific handler for notification messages
        if (this.isNotificationMessage(message)) {
          this.callbacks.onNotification?.(message as NotificationMessage);
        }
      } catch (error) {
        console.error("[WebSocket] Failed to parse message:", error);
      }
    };

    this.ws.onerror = (event: Event) => {
      console.error("[WebSocket] Error:", event);
      this.callbacks.onError?.(new Error("WebSocket connection error"));
    };

    this.ws.onclose = () => {
      this.stopHeartbeat();

      if (!this.isManualDisconnect) {
        this.setState("disconnected");
        this.scheduleReconnect();
      }
    };
  }

  private isNotificationMessage(
    message: WebSocketMessage,
  ): message is NotificationMessage {
    return (
      message.type === "notification.delivered" ||
      message.type === "notification.updated" ||
      message.type === "notification.read"
    );
  }

  private setState(state: WebSocketState): void {
    if (this.state !== state) {
      this.state = state;
      this.callbacks.onStateChange?.(state);
    }
  }

  private scheduleReconnect(): void {
    if (
      this.isManualDisconnect ||
      !this.config.autoReconnect ||
      this.reconnectAttempts >= this.config.maxReconnectAttempts
    ) {
      if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
        this.setState("error");
        this.callbacks.onError?.(
          new Error(
            `Failed to reconnect after ${this.config.maxReconnectAttempts} attempts`,
          ),
        );
      }
      return;
    }

    this.reconnectAttempts++;
    const delay =
      this.config.reconnectDelay * Math.min(this.reconnectAttempts, 3);

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();

    this.heartbeatIntervalId = setInterval(() => {
      if (this.ws && this.state === "connected") {
        try {
          // Send a ping message to keep the connection alive
          this.ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          // Connection might be dead, let onclose handle it
        }
      }
    }, this.config.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatIntervalId) {
      clearInterval(this.heartbeatIntervalId);
      this.heartbeatIntervalId = null;
    }
  }

  private cleanup(): void {
    this.stopHeartbeat();

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;

      try {
        this.ws.close();
      } catch {
        // Ignore close errors
      }

      this.ws = null;
    }
  }
}

/**
 * Type guard to check if a message is a notification delivered message
 */
export function isNotificationDelivered(
  message: WebSocketMessage,
): message is NotificationDeliveredMessage {
  return message.type === "notification.delivered";
}

/**
 * Type guard to check if a message is a notification updated message
 */
export function isNotificationUpdated(
  message: WebSocketMessage,
): message is NotificationUpdatedMessage {
  return message.type === "notification.updated";
}

/**
 * Type guard to check if a message is a notification read message
 */
export function isNotificationRead(
  message: WebSocketMessage,
): message is NotificationReadMessage {
  return message.type === "notification.read";
}
