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
 * - Domain types: Workflow, Todo, Conversation (match backend API schemas)
 */

/**
 * Represents a chat request sent to the GAIA bot API.
 */
export interface ChatRequest {
  /** The message content to send. */
  message: string;
  /** The platform the message originated from. */
  platform: "discord" | "slack" | "telegram" | "whatsapp";
  /** The user ID of the sender on the platform. */
  platformUserId: string;
  /** Optional channel ID where the conversation is happening. */
  channelId?: string;
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

export interface Workflow {
  id: string;
  name: string;
  description: string;
  status: "active" | "inactive" | "draft";
  triggers?: Record<string, unknown>[];
  steps?: Record<string, unknown>[];
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowListResponse {
  workflows: Workflow[];
}

export interface WorkflowExecutionRequest {
  workflow_id: string;
  inputs?: Record<string, unknown>;
}

export interface WorkflowExecutionResponse {
  execution_id: string;
  status: string;
  result?: unknown;
}

export interface Todo {
  id: string;
  title: string;
  description?: string;
  completed: boolean;
  priority?: "low" | "medium" | "high";
  due_date?: string;
  project_id?: string;
}

export interface TodoListResponse {
  todos: Todo[];
  total: number;
}

export interface CreateTodoRequest {
  title: string;
  description?: string;
  completed?: boolean;
  priority?: "low" | "medium" | "high";
  due_date?: string;
  project_id?: string;
}

export interface Conversation {
  conversation_id: string;
  title?: string;
  description?: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface ConversationListResponse {
  conversations: Conversation[];
  total: number;
  page: number;
}

export interface BotUserContext {
  platform: "discord" | "slack" | "telegram" | "whatsapp";
  platformUserId: string;
}

export type CommandContext = BotUserContext & {
  channelId?: string;
  /** Optional platform profile info, populated by the bot adapter when available. */
  profile?: { username?: string; displayName?: string };
};

/**
 * Integration information for settings.
 */
export interface IntegrationInfo {
  name: string;
  logoUrl: string | null;
  status: "created" | "connected";
}

/**
 * User settings response when not authenticated.
 */
export interface UnauthenticatedSettingsResponse {
  authenticated: false;
}

/**
 * User settings response when authenticated.
 */
export interface AuthenticatedSettingsResponse {
  authenticated: true;
  userName: string | null;
  accountCreatedAt: string | null;
  profileImageUrl: string | null;
  selectedModelName: string | null;
  selectedModelIconUrl: string | null;
  connectedIntegrations: IntegrationInfo[];
}

/**
 * User settings response (discriminated union).
 */
export type SettingsResponse =
  | UnauthenticatedSettingsResponse
  | AuthenticatedSettingsResponse;

// ---------------------------------------------------------------------------
// Adapter pattern types - used by BaseBotAdapter and unified commands
// ---------------------------------------------------------------------------

/** Supported platform names for bot integrations. */
export type PlatformName = "discord" | "slack" | "telegram" | "whatsapp";

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
