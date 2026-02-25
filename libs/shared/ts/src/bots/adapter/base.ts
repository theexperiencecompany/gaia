/**
 * Abstract base class for all GAIA bot adapters.
 *
 * Implements the adapter pattern: platform-specific bots extend this class
 * and provide implementations for abstract lifecycle methods, while shared
 * logic (command dispatch, streaming chat, context building) lives here.
 *
 * ## Lifecycle
 *
 * ```
 * constructor()          → loadConfig(), create GaiaClient
 *       ↓
 * boot(commands)         → initialize() → registerCommands() → registerEvents() → start()
 *       ↓
 * (running – handling commands and events)
 *       ↓
 * shutdown()             → stop()
 * ```
 *
 * ## Subclass contract
 *
 * Subclasses must implement:
 * - {@link initialize} — create the platform client (Discord `Client`, Slack `App`, etc.)
 * - {@link registerCommands} — wire unified {@link BotCommand} definitions to platform handlers
 * - {@link registerEvents} — register non-command event listeners (mentions, DMs, etc.)
 * - {@link start} — connect to the platform gateway / start polling
 * - {@link stop} — gracefully disconnect
 *
 * Subclasses should use the provided helpers:
 * - {@link dispatchCommand} — look up a unified command by name and execute it
 * - {@link buildContext} — create a {@link CommandContext} for the current platform
 *
 * @module
 */
import { GaiaClient } from "../api";
import { loadConfig } from "../config";
import type {
  BotCommand,
  BotConfig,
  CommandContext,
  PlatformName,
  RichMessageTarget,
} from "../types";
import { formatBotError } from "../utils/formatters";

/**
 * Abstract base class that all platform bot adapters extend.
 *
 * Provides shared infrastructure for command dispatch, streaming chat,
 * error handling, and lifecycle management. Platform-specific behavior
 * is delegated to abstract methods that each adapter implements.
 *
 * @example
 * ```typescript
 * class DiscordAdapter extends BaseBotAdapter {
 *   platform = "discord" as const;
 *
 *   async initialize() { this.client = new Client({...}); }
 *   async registerCommands(commands) { ... }
 *   async registerEvents() { ... }
 *   async start() { await this.client.login(token); }
 *   async stop() { this.client.destroy(); }
 * }
 * ```
 */
export abstract class BaseBotAdapter {
  /**
   * The platform this adapter serves.
   * Must be set by each concrete subclass (e.g. `"discord"`, `"slack"`, `"telegram"`).
   */
  abstract readonly platform: PlatformName;

  /** GAIA API client shared across all command handlers. */
  protected gaia!: GaiaClient;

  /** Bot configuration loaded from environment variables. */
  protected config!: BotConfig;

  /** Map of registered unified commands, keyed by command name. */
  protected commands: Map<string, BotCommand> = new Map();

  // ---------------------------------------------------------------------------
  // Lifecycle — template method pattern
  // ---------------------------------------------------------------------------

  /**
   * Boots the adapter through its full lifecycle.
   *
   * This is the main entry point called from each bot's `index.ts`.
   * It runs the lifecycle steps in order:
   * 1. Store unified command definitions
   * 2. {@link initialize} — create platform client
   * 3. {@link registerCommands} — wire commands to platform handlers
   * 4. {@link registerEvents} — register event listeners
   * 5. {@link start} — connect to the platform
   *
   * @param commands - Array of unified {@link BotCommand} definitions to register.
   */
  async boot(commands: BotCommand[]): Promise<void> {
    this.config = await loadConfig();
    this.gaia = new GaiaClient(
      this.config.gaiaApiUrl,
      this.config.gaiaApiKey,
      this.config.gaiaFrontendUrl,
    );

    for (const cmd of commands) {
      this.commands.set(cmd.name, cmd);
    }
    await this.initialize();
    await this.registerCommands(commands);
    await this.registerEvents();
    await this.start();
  }

  /**
   * Gracefully shuts down the adapter.
   *
   * Called from process signal handlers (SIGINT, SIGTERM).
   * Delegates to the platform-specific {@link stop} implementation.
   */
  async shutdown(): Promise<void> {
    console.log(`Shutting down ${this.platform} bot...`);
    await this.stop();
  }

  // ---------------------------------------------------------------------------
  // Abstract methods — implemented by each platform adapter
  // ---------------------------------------------------------------------------

  /**
   * Creates and configures the platform-specific client.
   *
   * Called once during {@link boot}, before commands and events are registered.
   * Use this to create the Discord `Client`, Slack `App`, Telegram `Bot`, etc.
   */
  protected abstract initialize(): Promise<void>;

  /**
   * Registers unified command definitions with the platform.
   *
   * Each adapter maps {@link BotCommand} metadata to its platform's
   * command registration API (e.g. Discord slash commands, Slack `app.command()`,
   * Telegram `bot.command()`).
   *
   * @param commands - The unified command definitions to register.
   */
  protected abstract registerCommands(commands: BotCommand[]): Promise<void>;

  /**
   * Registers non-command event listeners (mentions, DMs, errors, etc.).
   *
   * Called after {@link registerCommands} during {@link boot}.
   */
  protected abstract registerEvents(): Promise<void>;

  /**
   * Connects to the platform gateway and begins processing events.
   *
   * Called as the final step of {@link boot}.
   */
  protected abstract start(): Promise<void>;

  /**
   * Gracefully disconnects from the platform.
   *
   * Called by {@link shutdown}. Should clean up connections, intervals, etc.
   */
  protected abstract stop(): Promise<void>;

  // ---------------------------------------------------------------------------
  // Shared helpers — used by adapter subclasses
  // ---------------------------------------------------------------------------

  /**
   * Dispatches a command by name, executing the unified handler.
   *
   * Looks up the command in the registered commands map and calls its
   * `execute` function with the provided parameters. Handles errors
   * gracefully by sending a formatted error message to the user.
   *
   * @param name - The command name (without leading slash).
   * @param target - The message target for replies.
   * @param args - Parsed arguments keyed by option name.
   * @param rawText - Optional raw text input for free-form commands.
   */
  protected async dispatchCommand(
    name: string,
    target: RichMessageTarget,
    args: Record<string, string | number | boolean | undefined> = {},
    rawText?: string,
  ): Promise<void> {
    const command = this.commands.get(name);
    if (!command) {
      await target.sendEphemeral(`Unknown command: /${name}`);
      return;
    }

    const ctx = this.buildContext(
      target.userId,
      target.channelId,
      target.profile,
    );

    try {
      await command.execute({
        gaia: this.gaia,
        target,
        ctx,
        args,
        rawText,
      });
    } catch (error) {
      console.error(`Error executing command /${name}:`, error);
      const errMsg = formatBotError(error);
      try {
        await target.sendEphemeral(errMsg);
      } catch {
        // Target may be expired (e.g. Discord interaction timeout)
      }
    }
  }

  /**
   * Builds a {@link CommandContext} for the current platform.
   *
   * Used internally by {@link dispatchCommand} and available to subclasses
   * for building context objects when handling events directly.
   *
   * @param userId - The platform-specific user ID.
   * @param channelId - The channel/conversation ID (optional).
   * @returns A {@link CommandContext} with the adapter's platform set.
   */
  protected buildContext(
    userId: string,
    channelId?: string,
    profile?: { username?: string; displayName?: string },
  ): CommandContext {
    return {
      platform: this.platform,
      platformUserId: userId,
      channelId,
      profile,
    };
  }
}
