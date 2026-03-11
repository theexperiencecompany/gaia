import { AppState, type AppStateStatus } from "react-native";
import { getAuthToken } from "@/features/auth/utils/auth-storage";
import { API_ORIGIN } from "./constants";

type MessageHandler = (data: unknown) => void;
type ConnectionHandler = () => void;
type ErrorHandler = (error: Error) => void;

interface WebSocketManagerConfig {
  url?: string;
  reconnectAttempts?: number;
  reconnectDelay?: number;
}

class WebSocketManager {
  private ws: WebSocket | null = null;
  private subscribers: Map<string, Set<MessageHandler>> = new Map();
  private connectionHandlers: Set<ConnectionHandler> = new Set();
  private disconnectionHandlers: Set<ConnectionHandler> = new Set();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private baseReconnectDelay = 1000;
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private heartbeatIntervalId: ReturnType<typeof setInterval> | null = null;
  private heartbeatInterval = 30000;
  private isIntentionalClose = false;
  private wsUrl: string = "";
  private appStateSubscription: ReturnType<
    typeof AppState.addEventListener
  > | null = null;

  configure(config: WebSocketManagerConfig): void {
    if (config.url !== undefined) {
      this.wsUrl = config.url;
    }
    if (config.reconnectAttempts !== undefined) {
      this.maxReconnectAttempts = config.reconnectAttempts;
    }
    if (config.reconnectDelay !== undefined) {
      this.baseReconnectDelay = config.reconnectDelay;
    }
  }

  async connect(url?: string): Promise<void> {
    if (url) {
      this.wsUrl = url;
    }

    if (!this.wsUrl) {
      if (
        !API_ORIGIN ||
        typeof API_ORIGIN !== "string" ||
        !API_ORIGIN.startsWith("http")
      ) {
        this.notifyError(
          new Error(
            "Missing or invalid API_ORIGIN: cannot establish WebSocket connection",
          ),
        );
        return;
      }
      const wsOrigin = API_ORIGIN.replace(/^http/, "ws");
      this.wsUrl = `${wsOrigin}/api/v1/ws/connect`;
    }

    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    const token = await getAuthToken();
    if (!token) {
      this.notifyError(new Error("Not authenticated"));
      return;
    }

    this.isIntentionalClose = false;

    try {
      // Pass token via subprotocol for security (prevents exposure in logs)
      this.ws = new WebSocket(this.wsUrl, ["Bearer", token]);
      this.setupEventHandlers();
    } catch (error) {
      this.notifyError(
        error instanceof Error ? error : new Error(String(error)),
      );
      this.scheduleReconnect();
    }
  }

  disconnect(): void {
    this.isIntentionalClose = true;

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
        this.ws.close(1000, "Intentional disconnect");
      } catch {
        // Ignore close errors
      }

      this.ws = null;
    }

    this.reconnectAttempts = 0;
  }

  /**
   * Subscribe to a specific event type.
   * Returns an unsubscribe function.
   */
  subscribe(eventType: string, handler: MessageHandler): () => void {
    if (!this.subscribers.has(eventType)) {
      this.subscribers.set(eventType, new Set());
    }
    this.subscribers.get(eventType)!.add(handler);

    return () => {
      const handlers = this.subscribers.get(eventType);
      if (handlers) {
        handlers.delete(handler);
        if (handlers.size === 0) {
          this.subscribers.delete(eventType);
        }
      }
    };
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn(
        "[WebSocketManager] Cannot send message - not connected. ReadyState:",
        this.ws?.readyState,
      );
    }
  }

  /**
   * Emit a typed event message to the server.
   */
  emit(eventType: string, data: unknown): void {
    this.send({ type: eventType, data });
  }

  onConnect(handler: ConnectionHandler): void {
    this.connectionHandlers.add(handler);
  }

  offConnect(handler: ConnectionHandler): void {
    this.connectionHandlers.delete(handler);
  }

  onDisconnect(handler: ConnectionHandler): void {
    this.disconnectionHandlers.add(handler);
  }

  offDisconnect(handler: ConnectionHandler): void {
    this.disconnectionHandlers.delete(handler);
  }

  onError(handler: ErrorHandler): void {
    this.errorHandlers.add(handler);
  }

  offError(handler: ErrorHandler): void {
    this.errorHandlers.delete(handler);
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Register AppState listener to pause/resume the WebSocket connection
   * based on whether the app is in the foreground or background.
   */
  registerAppStateHandler(): void {
    if (this.appStateSubscription) {
      return;
    }

    this.appStateSubscription = AppState.addEventListener(
      "change",
      (nextState: AppStateStatus) => {
        this.handleAppStateChange(nextState);
      },
    );
  }

  /**
   * Remove the AppState listener.
   */
  unregisterAppStateHandler(): void {
    if (this.appStateSubscription) {
      this.appStateSubscription.remove();
      this.appStateSubscription = null;
    }
  }

  private handleAppStateChange(state: AppStateStatus): void {
    if (state === "active") {
      // App came to foreground — reconnect if not already connected
      if (!this.isConnected && !this.isIntentionalClose) {
        console.log("[WebSocketManager] App foregrounded, reconnecting...");
        this.connect();
      }
    } else if (state === "background" || state === "inactive") {
      // App went to background — stop heartbeat to save battery/bandwidth
      // but do not close the connection; let the OS handle it
      this.stopHeartbeat();
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log("[WebSocketManager] Connected to:", this.wsUrl);
      this.reconnectAttempts = 0;
      this.startHeartbeat();
      this.connectionHandlers.forEach((handler) => handler());
    };

    this.ws.onmessage = (event: WebSocketMessageEvent) => {
      try {
        const data = typeof event.data === "string" ? event.data : "";
        const message = JSON.parse(data) as Record<string, unknown>;

        // Respond to server ping
        if (message.type === "ping") {
          this.send({ type: "pong" });
          return;
        }

        const eventType =
          typeof message.type === "string" ? message.type : null;

        if (eventType) {
          // Notify specific event handlers
          const handlers = this.subscribers.get(eventType);
          if (handlers) {
            handlers.forEach((handler) => handler(message));
          }
        }

        // Notify wildcard handlers
        const wildcardHandlers = this.subscribers.get("*");
        if (wildcardHandlers) {
          wildcardHandlers.forEach((handler) => handler(message));
        }
      } catch (error) {
        console.error("[WebSocketManager] Error parsing message:", error);
        this.notifyError(
          error instanceof Error ? error : new Error(String(error)),
        );
      }
    };

    this.ws.onerror = (event: Event) => {
      console.error("[WebSocketManager] Connection error:", event);
      this.notifyError(new Error("WebSocket connection error"));
    };

    this.ws.onclose = (event: WebSocketCloseEvent) => {
      console.log(
        "[WebSocketManager] Disconnected:",
        event.code,
        event.reason,
        "intentional:",
        this.isIntentionalClose,
      );

      this.stopHeartbeat();
      this.ws = null;
      this.disconnectionHandlers.forEach((handler) => handler());

      if (this.isIntentionalClose || event.code === 1000) {
        return;
      }

      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (
      this.isIntentionalClose ||
      this.reconnectAttempts >= this.maxReconnectAttempts
    ) {
      if (this.reconnectAttempts >= this.maxReconnectAttempts) {
        console.error(
          "[WebSocketManager] Max reconnection attempts reached:",
          this.maxReconnectAttempts,
        );
        this.notifyError(new Error("Failed to reconnect to WebSocket"));
      }
      return;
    }

    const delay = this.baseReconnectDelay * 2 ** this.reconnectAttempts;
    this.reconnectAttempts++;

    console.log(
      `[WebSocketManager] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
    );

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatIntervalId = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(JSON.stringify({ type: "ping" }));
        } catch {
          // Connection may be dead; let onclose handle recovery
        }
      }
    }, this.heartbeatInterval);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatIntervalId) {
      clearInterval(this.heartbeatIntervalId);
      this.heartbeatIntervalId = null;
    }
  }

  private notifyError(error: Error): void {
    this.errorHandlers.forEach((handler) => handler(error));
  }
}

// Singleton instance — one connection for the entire app
export const wsManager = new WebSocketManager();
