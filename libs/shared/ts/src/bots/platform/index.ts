import type { Platform } from "../types";

/**
 * Base interface for platform-specific bot implementations.
 * Each platform (Discord, Slack, Telegram, etc.) implements this interface.
 */
export interface PlatformBot {
  /** The platform identifier */
  readonly platform: Platform;

  /** Start the bot and connect to the platform */
  start(): Promise<void>;

  /** Stop the bot gracefully */
  stop(): Promise<void>;
}
