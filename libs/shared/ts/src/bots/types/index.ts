/**
 * Represents a chat request sent to the GAIA bot API.
 */
export interface ChatRequest {
  /** The message content to send. */
  message: string;
  /** The platform the message originated from. */
  platform: "discord" | "slack" | "telegram";
  /** The user ID of the sender on the platform. */
  platformUserId: string;
  /** Optional channel ID where the conversation is happening. */
  channelId?: string;
  /** Whether this message is from a public group context (restricts personal data access). */
  publicContext?: boolean;
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
 * Represents session information for a bot conversation.
 */
export interface SessionInfo {
  /** The unique identifier for the conversation session. */
  conversationId: string;
  /** The platform associated with this session. */
  platform: string;
  /** The user ID on the platform. */
  platformUserId: string;
}

/**
 * Configuration required for the bot to operate.
 */
export interface BotConfig {
  /** The base URL of the GAIA backend API. */
  gaiaApiUrl: string;
  /** The secure API key for authenticating with the backend. */
  gaiaApiKey: string;
}

/**
 * Represents the authentication status of a user on a platform.
 */
export interface AuthStatus {
  /** Whether the user is authenticated/linked. */
  authenticated: boolean;
  /** The platform name. */
  platform: string;
  /** The user ID on the platform. */
  platformUserId: string;
}
