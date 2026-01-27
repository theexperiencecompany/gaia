import type { GaiaClient } from "../api";
import type { Platform } from "../types";

/**
 * Option definition for bot commands.
 */
export interface CommandOption {
  /** Option name */
  name: string;
  /** Human-readable description */
  description: string;
  /** Whether the option is required */
  required?: boolean;
  /** Option type */
  type: "string" | "number" | "boolean";
}

/**
 * Unified command definition that works across all platforms.
 */
export interface BotCommand {
  /** Command name (e.g., "chat", "settings", "help") */
  name: string;
  /** Human-readable description */
  description: string;
  /** Command options/arguments */
  options?: CommandOption[];
  /** Execute the command */
  execute: (context: CommandContext) => Promise<void>;
  /** Optional autocomplete handler */
  autocomplete?: (context: AutocompleteContext) => Promise<void>;
}

/**
 * Platform-agnostic command execution context.
 * Abstracts away platform-specific interaction details.
 */
export interface CommandContext {
  /** The GAIA API client */
  gaia: GaiaClient;
  /** The platform this command is running on */
  platform: Platform;
  /** The user's platform-specific ID */
  userId: string;
  /** User's display name (if available) */
  userName?: string;
  /** Optional channel/thread ID */
  channelId?: string;
  /** Command arguments as key-value pairs */
  args: Record<string, string | number | boolean>;
  /** Reply to the user */
  reply: (content: string, options?: ReplyOptions) => Promise<void>;
  /** Defer the response (for long-running operations) */
  defer: (options?: DeferOptions) => Promise<void>;
  /** Edit a deferred response */
  editReply: (content: string) => Promise<void>;
  /** Send a follow-up message */
  followUp?: (content: string) => Promise<void>;
}

/**
 * Context for autocomplete handlers.
 */
export interface AutocompleteContext {
  /** The platform this is running on */
  platform: Platform;
  /** The user's platform-specific ID */
  userId: string;
  /** The option being autocompleted */
  focusedOption: string;
  /** Current value of the option */
  focusedValue: string;
  /** All current argument values */
  args: Record<string, string | number | boolean>;
  /** Respond with choices */
  respond: (choices: AutocompleteChoice[]) => Promise<void>;
}

export interface AutocompleteChoice {
  name: string;
  value: string;
}

export interface ReplyOptions {
  /** Make the reply visible only to the user (ephemeral) */
  ephemeral?: boolean;
}

export interface DeferOptions {
  /** Make the deferred reply ephemeral */
  ephemeral?: boolean;
}

/**
 * Base interface for platform-specific bot implementations.
 * Each platform (Discord, Slack, Telegram, etc.) implements this interface.
 */
export interface PlatformBot {
  /** The platform identifier */
  readonly platform: Platform;

  /** Register commands with the platform */
  registerCommands(commands: BotCommand[]): void;

  /** Start the bot and connect to the platform */
  start(): Promise<void>;

  /** Stop the bot gracefully */
  stop(): Promise<void>;
}

/**
 * Factory function type for creating platform bots.
 */
export type PlatformBotFactory = (gaia: GaiaClient) => Promise<PlatformBot>;

/**
 * Message context for handling direct messages or mentions.
 */
export interface MessageContext {
  /** The GAIA API client */
  gaia: GaiaClient;
  /** The platform this message is from */
  platform: Platform;
  /** The user's platform-specific ID */
  userId: string;
  /** User's display name (if available) */
  userName?: string;
  /** The message content */
  content: string;
  /** Channel/thread ID where the message was sent */
  channelId?: string;
  /** Reply to the message */
  reply: (content: string) => Promise<void>;
}

/**
 * Handler for direct messages or mentions.
 */
export type MessageHandler = (context: MessageContext) => Promise<void>;
