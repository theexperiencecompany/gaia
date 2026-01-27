/**
 * Supported bot platforms. Extensible for future platforms.
 */
export type Platform = "discord" | "slack" | "telegram" | "whatsapp" | "cli";

/**
 * Represents a chat request sent to the GAIA bot API.
 */
export interface ChatRequest {
  /** The message content to send. */
  message: string;
  /** The platform the message originated from. */
  platform: Platform;
  /** The user ID of the sender on the platform. */
  platformUserId: string;
  /** Optional channel ID where the conversation is happening. */
  channelId?: string;
}

/**
 * Represents the response from the GAIA bot API.
 */
export interface ChatResponse {
  /** The agent's response text. */
  response: string;
  /** The unique identifier for the conversation session. */
  conversationId: string;
  /** Whether the user is authenticated with GAIA. */
  authenticated: boolean;
}

/**
 * Configuration required for the bot to operate.
 */
export interface BotConfig {
  /** The base URL of the GAIA backend API. */
  gaiaApiUrl: string;
  /** The secure API key for authenticating with the backend. */
  gaiaApiKey: string;
  /** The base URL of the GAIA web app (for auth links). */
  gaiaWebUrl: string;
}

/**
 * Represents a connected integration for the user.
 */
export interface ConnectedIntegration {
  /** The unique identifier for the integration. */
  id: string;
  /** The display name of the integration. */
  name: string;
  /** URL to the integration's icon. */
  iconUrl: string | null;
}

/**
 * Represents user settings retrieved from the bot API.
 */
export interface UserSettings {
  /** Whether the user is authenticated with GAIA. */
  authenticated: boolean;
  /** The user's display name. */
  userName: string | null;
  /** URL to the user's profile image. */
  profileImageUrl: string | null;
  /** ISO timestamp of when the account was created. */
  accountCreatedAt: string | null;
  /** The name of the user's selected AI model. */
  selectedModelName: string | null;
  /** URL to the selected model's icon. */
  selectedModelIconUrl: string | null;
  /** List of connected integrations. */
  connectedIntegrations: ConnectedIntegration[];
}
