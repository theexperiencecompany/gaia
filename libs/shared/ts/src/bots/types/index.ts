/**
 * Shared types for all GAIA bot integrations.
 *
 * These interfaces define the contract between bot adapters and the
 * shared library. Bot-specific types (Discord Interaction, Slack Command, etc.)
 * live in each bot's own code - only platform-agnostic types belong here.
 *
 * Key types:
 * - ChatRequest / ChatResponse: chat API payloads
 * - CommandContext: user identity passed to all shared command handlers
 * - BotConfig: environment config loaded by config/index.ts
 *
 * Workflow and todo payloads are the generated API models
 * (`@gaia/shared/api/generated`), never a hand-written copy.
 */

import type { BotAuthStatusResponse, FileData } from "../../api/generated";

/** A file previously uploaded via {@link GaiaClient.uploadFile}, sent alongside chat requests. */
export type BotFileData = FileData;

/**
 * Represents a chat request sent to the GAIA bot API.
 */
export interface ChatRequest {
  /** The message content to send. */
  message: string;
  /** The platform the message originated from. */
  platform: PlatformName;
  /** The user ID of the sender on the platform. */
  platformUserId: string;
  /** Optional channel ID where the conversation is happening. */
  channelId?: string;
  /**
   * Whether this conversation is a direct message. Discord and Slack DM
   * channel ids differ from the user id, so the server cannot tell a DM from
   * a channel without this.
   */
  isDm?: boolean;
  /**
   * IDs of files the user has attached to this message. The agent loads each
   * file's metadata + content from MongoDB / ChromaDB and grounds its reply
   * in the file contents.
   */
  fileIds?: string[];
  /**
   * Platform-native id of the user's inbound message (WhatsApp wamid, Telegram
   * message_id, Discord id, Slack ts, iMessage id). Persisted server-side so a
   * later background reaction can anchor to the exact platform message.
   * Absent when the trigger has no message id (slash-command interactions).
   */
  platformMessageId?: string;
  /**
   * When the platform event reached the bot (epoch ms), stamped by the adapter
   * on arrival — before any per-user queue — so the chat event can report how
   * much of the reply's latency the bot itself added. Never sent to the API.
   */
  receivedAt?: number;
  /**
   * Full file metadata for the attached files. Sent alongside `fileIds` so
   * the agent can resolve URLs/filenames without an extra DB lookup, matching
   * the web app's chat payload shape.
   */
  fileData?: BotFileData[];
}

/**
 * Configuration required for the bot to operate.
 */
export interface BotConfig {
  /** The base URL of the GAIA backend API. */
  gaiaApiUrl: string;
  /** The secure API key for authenticating with the backend. */
  gaiaApiKey: string;
  /** The base URL of the GAIA frontend app. */
  gaiaFrontendUrl: string;
  /**
   * PostHog project token for bot analytics, the same POSTHOG_PROJECT_TOKEN the
   * API and voice agent read. Optional — a missing token is logged at boot and
   * disables analytics (safe for local development).
   */
  posthogProjectToken?: string;
  /**
   * RabbitMQ connection URL for consuming backend-originated outbound
   * messages. Optional — the outbound consumer is disabled when absent (safe
   * for local development without a broker).
   */
  rabbitmqUrl?: string;
}

/** Whether a platform user is linked to a GAIA account. */
export type AuthStatus = BotAuthStatusResponse;

export interface BotUserContext {
  platform: PlatformName;
  platformUserId: string;
}

export type CommandContext = BotUserContext & {
  channelId?: string;
  isDm?: boolean;
  /** Optional platform profile info, populated by the bot adapter when available. */
  profile?: { username?: string; displayName?: string };
};

// ---------------------------------------------------------------------------
// Adapter pattern types - used by BaseBotAdapter and unified commands
// ---------------------------------------------------------------------------

/** Supported platform names for bot integrations. */
export type PlatformName =
  | "discord"
  | "slack"
  | "telegram"
  | "whatsapp"
  | "imessage";

/**
 * A message that has been sent to a platform channel.
 *
 * Returned by {@link MessageTarget.send} and {@link MessageTarget.sendEphemeral}
 * so that command handlers can update a previously-sent message in place
 * (e.g. replacing "Thinking..." with the final streamed response).
 */
export interface SentMessage {
  /** Edits the content of this message in-place. */
  edit: (text: string) => Promise<void>;
  /** Platform-specific message identifier (Discord message ID, Slack `ts`, Telegram `message_id`, etc.). */
  id: string;
}

/**
 * Platform-agnostic message target that unified commands write to.
 *
 * Each bot adapter creates a `MessageTarget` (or {@link RichMessageTarget})
 * from its native context object (Discord `Interaction`, Slack `respond`, Telegram `ctx`)
 * so that command handlers never touch platform APIs directly.
 */
export interface MessageTarget {
  /** Sends a visible message to the channel/DM and returns a handle to edit it later. */
  send: (text: string) => Promise<SentMessage>;
  /** Sends an ephemeral (only-visible-to-invoker) message. Falls back to `send` on platforms without ephemeral support. */
  sendEphemeral: (text: string) => Promise<SentMessage>;
  /**
   * Begins a typing / "thinking" indicator on the channel.
   * Returns a cleanup function that stops the indicator.
   * On platforms without typing support, returns a no-op cleanup.
   */
  startTyping: () => Promise<() => void>;
  /** The platform this target belongs to. */
  platform: PlatformName;
  /** The invoking user's platform-specific ID. */
  userId: string;
  /** The channel/conversation where the command was invoked (absent for some DM contexts). */
  channelId?: string;
  /**
   * Whether this conversation is a direct message. Discord and Slack DM
   * channel ids differ from the user id, so the server cannot tell a DM from
   * a channel without this.
   */
  isDm?: boolean;
  /** Optional platform profile info (username, display name) from the bot adapter. */
  profile?: { username?: string; displayName?: string };
}

/**
 * Extended {@link MessageTarget} that can send rich / structured content.
 *
 * Adapters for platforms with native rich content (e.g. Discord embeds) implement
 * `sendRich` to convert {@link RichMessage} into the platform's native format.
 * For platforms without native support (Slack, Telegram), `sendRich` falls back
 * to rendering the rich message as formatted markdown via `richMessageToMarkdown`.
 */
export interface RichMessageTarget extends MessageTarget {
  /** Sends a structured rich message, rendered using the platform's native format. */
  sendRich: (message: RichMessage) => Promise<SentMessage>;
}

/**
 * Platform-agnostic rich content payload.
 *
 * Adapters convert this into their platform's native format:
 * - Discord → `EmbedBuilder`
 * - Slack / Telegram → Markdown string (via `richMessageToMarkdown`)
 *
 * Used by commands like `/help` and `/settings` that need structured layouts.
 */
export interface RichMessage {
  /** The content type. Currently only `"embed"` is supported. */
  type: "embed";
  /** Bold title displayed at the top. */
  title: string;
  /** Optional description paragraph below the title. */
  description?: string;
  /** Sidebar color as a 24-bit integer (e.g. `0x7c3aed`). */
  color?: number;
  /** Structured key-value fields displayed in the body. */
  fields: Array<{ name: string; value: string; inline?: boolean }>;
  /** Small text displayed at the bottom. */
  footer?: string;
  /** URL for a thumbnail image displayed alongside the content. */
  thumbnailUrl?: string;
  /** Display name shown in the author line. */
  authorName?: string;
  /** Small icon URL displayed next to the author name. */
  authorIconUrl?: string;
  /** Whether to display a timestamp (current time) at the footer. */
  timestamp?: boolean;
  /** Clickable links displayed at the bottom of the message. */
  links?: Array<{ label: string; url: string }>;
}

/**
 * A single option for a {@link BotCommand}.
 *
 * Maps to Discord's `addStringOption` / `addIntegerOption`, and is used by
 * text-based platforms (Slack, Telegram) for generating usage strings.
 */
export interface BotCommandOption {
  /** The option's name (used as the key in `args`). */
  name: string;
  /** Human-readable description shown in help text and Discord's UI. */
  description: string;
  /** Whether the option must be provided. */
  required?: boolean;
  /** The option's value type. Defaults to `"string"`. */
  type?: "string" | "integer" | "boolean";
  /** Predefined choices the user can pick from (e.g. priority levels). */
  choices?: Array<{ name: string; value: string }>;
}

/**
 * A subcommand within a {@link BotCommand} (e.g. `/todo add`, `/workflow get`).
 */
export interface BotSubcommand {
  /** The subcommand name (e.g. `"add"`, `"list"`). */
  name: string;
  /** Human-readable description. */
  description: string;
  /** Options specific to this subcommand. */
  options?: BotCommandOption[];
}

/**
 * Parameters passed to a unified command's `execute` function.
 *
 * Built by the adapter from platform-native context and handed to the
 * command so it can interact with the GAIA API and reply to the user
 * without knowing which platform it's running on.
 */
export interface CommandExecuteParams {
  /** The GAIA API client instance. */
  gaia: GaiaClient;
  /** The message target to send replies to. */
  target: RichMessageTarget;
  /** User identity and channel context. */
  ctx: CommandContext;
  /** Parsed command arguments keyed by option name. */
  args: Record<string, string | number | boolean | undefined>;
  /** Raw text input (for free-form commands like `/gaia`). */
  rawText?: string;
}

/**
 * A platform-agnostic command definition.
 *
 * Defined once in `libs/shared/ts/src/bots/commands/` and consumed by every
 * bot adapter. The adapter converts platform-native events into
 * {@link CommandExecuteParams} and calls `execute`.
 *
 * For commands that need streaming (e.g. `/gaia`), the adapter special-cases
 * them and routes to its own `handleChat()` method instead.
 */
export interface BotCommand {
  /** The command name without the leading slash (e.g. `"todo"`). */
  name: string;
  /** Short description shown in help text and slash-command UIs. */
  description: string;
  /** Top-level options (mutually exclusive with `subcommands`). */
  options?: BotCommandOption[];
  /** Subcommands (e.g. `list`, `add`, `complete` under `/todo`). */
  subcommands?: BotSubcommand[];
  /**
   * Executes the command.
   *
   * Receives platform-agnostic params so the same function works on
   * Discord, Slack, and Telegram. Replies are sent via `target.send` /
   * `target.sendRich`.
   */
  execute: (params: CommandExecuteParams) => Promise<void>;
}

// Re-export GaiaClient type for use in CommandExecuteParams
// (avoids circular imports - consumers import GaiaClient from @gaia/shared directly)
import type { GaiaClient } from "../api";

/**
 * For a platform that only lets a business message a user freely inside a window
 * (WhatsApp: 24h after the user last wrote). Outside it, a message must go out as
 * the platform's approved notification template, or the platform drops it.
 */
export interface OutboundNotifications {
  /** Whether a free-form message to `destinationId` would be refused right now. */
  windowClosed(destinationId: string, isChannel: boolean): Promise<boolean>;
  /** Sends one whole message, already rendered, as the notification template. */
  deliver(destinationId: string, text: string): Promise<void>;
}
