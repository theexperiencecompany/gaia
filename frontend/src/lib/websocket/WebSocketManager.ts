/**
 * Centralized WebSocket Manager
 * Single WebSocket connection for the entire application
 */

type MessageHandler = (message: any) => void;
type ConnectionHandler = () => void;
type ErrorHandler = (error: Error) => void;

interface WebSocketManagerConfig {
  url: string;
  reconnectAttempts?: number;
  reconnectDelay?: number;
}

class WebSocketManager {
  private ws: WebSocket | null = null;
  private messageHandlers: Map<string, Set<MessageHandler>> = new Map();
  private connectionHandlers: Set<ConnectionHandler> = new Set();
  private disconnectionHandlers: Set<ConnectionHandler> = new Set();
  private errorHandlers: Set<ErrorHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private baseReconnectDelay = 1000;
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private url: string = "";
  private isIntentionalClose = false;

  configure(config: WebSocketManagerConfig) {
    this.url = config.url;
    if (config.reconnectAttempts !== undefined) {
      this.maxReconnectAttempts = config.reconnectAttempts;
    }
    if (config.reconnectDelay !== undefined) {
      this.baseReconnectDelay = config.reconnectDelay;
    }
  }

  connect() {
    if (!this.url) {
      console.error("WebSocket URL not configured");
      return;
    }

    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      this.ws = new WebSocket(this.url);
      this.isIntentionalClose = false;

      this.ws.onopen = () => {
        console.log("[WebSocketManager] Connected successfully to:", this.url);
        this.reconnectAttempts = 0;
        this.connectionHandlers.forEach((handler) => handler());
      };

      this.ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);

          // Handle ping/pong
          if (message.type === "ping") {
            this.send({ type: "pong" });
            return;
          }

          console.log("[WebSocketManager] Received message:", message.type);

          // Notify all handlers for this message type
          const handlers = this.messageHandlers.get(message.type);
          if (handlers) {
            handlers.forEach((handler) => handler(message));
          }

          // Also notify wildcard handlers
          const wildcardHandlers = this.messageHandlers.get("*");
          if (wildcardHandlers) {
            wildcardHandlers.forEach((handler) => handler(message));
          }
        } catch (error) {
          console.error("[WebSocketManager] Error parsing message:", error);
          this.notifyError(error as Error);
        }
      };

      this.ws.onclose = (event) => {
        console.log(
          "[WebSocketManager] Disconnected:",
          event.code,
          event.reason,
          "intentional:",
          this.isIntentionalClose,
        );
        this.ws = null;
        this.disconnectionHandlers.forEach((handler) => handler());

        // Don't reconnect if close was intentional
        if (this.isIntentionalClose || event.code === 1000) {
          console.log(
            "[WebSocketManager] Not reconnecting (intentional close)",
          );
          return;
        }

        // Attempt reconnection
        this.attemptReconnect();
      };

      this.ws.onerror = (error) => {
        console.error("[WebSocketManager] Connection error:", error);
        this.notifyError(new Error("WebSocket connection failed"));
      };
    } catch (error) {
      console.error("[WebSocketManager] Error creating WebSocket:", error);
      this.notifyError(error as Error);
    }
  }

  disconnect() {
    this.isIntentionalClose = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close(1000, "Intentional disconnect");
      this.ws = null;
    }

    this.reconnectAttempts = 0;
  }

  send(data: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    } else {
      console.warn(
        "[WebSocketManager] Cannot send message - not connected. ReadyState:",
        this.ws?.readyState,
      );
    }
  }

  on(messageType: string, handler: MessageHandler) {
    if (!this.messageHandlers.has(messageType)) {
      this.messageHandlers.set(messageType, new Set());
    }
    this.messageHandlers.get(messageType)!.add(handler);
  }

  off(messageType: string, handler: MessageHandler) {
    const handlers = this.messageHandlers.get(messageType);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.messageHandlers.delete(messageType);
      }
    }
  }

  onConnect(handler: ConnectionHandler) {
    this.connectionHandlers.add(handler);
  }

  offConnect(handler: ConnectionHandler) {
    this.connectionHandlers.delete(handler);
  }

  onDisconnect(handler: ConnectionHandler) {
    this.disconnectionHandlers.add(handler);
  }

  offDisconnect(handler: ConnectionHandler) {
    this.disconnectionHandlers.delete(handler);
  }

  onError(handler: ErrorHandler) {
    this.errorHandlers.add(handler);
  }

  offError(handler: ErrorHandler) {
    this.errorHandlers.delete(handler);
  }

  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error(
        "[WebSocketManager] Max reconnection attempts reached:",
        this.maxReconnectAttempts,
      );
      this.notifyError(new Error("Failed to reconnect to WebSocket"));
      return;
    }

    const delay = this.baseReconnectDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;

    console.log(
      `[WebSocketManager] Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts}/${this.maxReconnectAttempts})`,
    );

    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private notifyError(error: Error) {
    this.errorHandlers.forEach((handler) => handler(error));
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();
