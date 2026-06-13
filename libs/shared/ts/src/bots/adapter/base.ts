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

import { Analytics, BOT_EVENTS } from "../../analytics";
import { GaiaClient } from "../api";
import { loadConfig } from "../config";
import type { OutboundAttachment } from "../consumer/envelope";
import { OutboundConsumer } from "../consumer/outbound-consumer";
import type {
  BotCommand,
  BotConfig,
  CommandContext,
  PlatformName,
  RichMessageTarget,
} from "../types";
import { formatBotError, renderForPlatform } from "../utils/formatters";
import {
  type BotLogger,
  createBotLogger,
  hashLogIdentifier,
  sanitizeErrorForLog,
} from "../utils/logger";
import {
  type IncomingMedia,
  type MediaOutcome,
  OUTBOUND_FILE_LIMITS,
  processBotMedia,
} from "../utils/media";
import { BotServer } from "./base-server";

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

  /**
   * Default HTTP server port for this bot.
   * Override in each subclass. Overrideable at runtime via `BOT_SERVER_PORT`.
   */
  protected abstract readonly defaultServerPort: number;

  /** GAIA API client shared across all command handlers. */
  protected gaia!: GaiaClient;

  /** Bot configuration loaded from environment variables. */
  protected config!: BotConfig;

  /** Map of registered unified commands, keyed by command name. */
  protected commands: Map<string, BotCommand> = new Map();

  /** Server-side PostHog analytics. No-op when POSTHOG_API_KEY is absent. */
  protected analytics: Analytics = new Analytics(undefined);

  /** Shared structured logger for adapter lifecycle and command execution. */
  protected logger: BotLogger = createBotLogger("shared", "base-adapter");

  private _botServer: BotServer | null = null;
  private _outboundConsumer: OutboundConsumer | null = null;

  /**
   * Shared HTTP server for this bot process.
   *
   * Always available during lifecycle methods ({@link initialize},
   * {@link registerCommands}, {@link registerEvents}, {@link start},
   * {@link stop}). Created in {@link boot} using a per-platform default port
   * (discord: 3200, slack: 3201, telegram: 3202, whatsapp: 3203). Override
   * with `BOT_SERVER_PORT`. Includes `GET /health` by default. Subclasses
   * can mount additional routes (e.g. webhook endpoints) via
   * `this.botServer.app` in their {@link registerEvents} implementation,
   * before the server starts.
   */
  protected get botServer(): BotServer {
    if (!this._botServer) {
      throw new Error("botServer accessed before boot() — call boot() first");
    }
    return this._botServer;
  }

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
    this.logger = createBotLogger(this.platform, "base-adapter");
    this.logger.info("boot_started", { command_count: commands.length });

    this.config = await loadConfig();
    this.gaia = new GaiaClient(
      this.config.gaiaApiUrl,
      this.config.gaiaApiKey,
      this.config.gaiaFrontendUrl,
    );
    this.analytics = new Analytics(this.config.posthogApiKey);

    for (const cmd of commands) {
      this.commands.set(cmd.name, cmd);
    }
    // Create the shared HTTP server before registerEvents() so subclasses
    // can mount custom routes (e.g. WhatsApp /webhook) on this.botServer.app.
    const serverPort =
      Number(process.env.BOT_SERVER_PORT) || this.defaultServerPort;
    this._botServer = new BotServer(this.platform, serverPort);

    let platformStarted = false;
    try {
      await this.initialize();
      await this.registerCommands(commands);
      await this.registerEvents();
      await this.start();
      platformStarted = true;

      // Consume backend-originated outbound messages (executor replies,
      // reminders) and deliver them via this platform's send primitive.
      this.startOutboundConsumer();

      // Start the server after registerEvents() so all routes are mounted.
      await this._botServer.start();
    } catch (error) {
      if (platformStarted) {
        await this.stop().catch(() => undefined);
      }
      await this._outboundConsumer?.stop().catch(() => undefined);
      this._outboundConsumer = null;
      await this._botServer?.stop().catch(() => undefined);
      this._botServer = null;
      throw error;
    }

    this.logger.info("boot_completed", { gaia_api_configured: true });
  }

  /**
   * Gracefully shuts down the adapter.
   *
   * Called from process signal handlers (SIGINT, SIGTERM).
   * Delegates to the platform-specific {@link stop} implementation.
   */
  async shutdown(): Promise<void> {
    this.logger.info("shutdown_started");
    if (this._outboundConsumer) {
      await this._outboundConsumer.stop();
      this._outboundConsumer = null;
    }
    await this.stop();
    if (this._botServer) {
      await this._botServer.stop();
      this._botServer = null;
    }
    await this.analytics.shutdown();
    this.logger.info("shutdown_completed");
  }

  /**
   * Starts the outbound RabbitMQ consumer for this platform, if configured.
   *
   * Fire-and-forget: the consumer connects and retries in the background so a
   * slow or unavailable broker never blocks boot. Disabled (with a warning)
   * when `RABBITMQ_URL` is unset, keeping local dev working without a broker.
   */
  private startOutboundConsumer(): void {
    const url = this.config.rabbitmqUrl;
    if (!url) {
      this.logger.warn("outbound_consumer_disabled", {
        reason: "RABBITMQ_URL not set",
      });
      return;
    }
    this._outboundConsumer = new OutboundConsumer(
      this.platform,
      url,
      (id, text) => this.deliverOutbound(id, text),
      (id, attachment) => this.deliverOutboundFile(id, attachment),
    );
    void this._outboundConsumer.start();
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

  /**
   * Sends a single already-rendered message to `destinationId` on this
   * platform. Called by the outbound RabbitMQ consumer for backend-originated
   * messages. The text has already been run through `renderForPlatform` — do
   * not convert it again; just hand it to the platform SDK.
   */
  protected abstract deliverOutbound(
    destinationId: string,
    text: string,
  ): Promise<void>;

  /**
   * Fetches an outbound artifact's bytes, enforcing this platform's file-size
   * cap. Returns the bytes, or `null` after sending a short "too large" note via
   * {@link deliverOutbound} when the artifact exceeds the limit — so an oversized
   * file tells the user instead of silently dead-lettering on a rejected upload.
   *
   * Adapter `deliverOutboundFile` overrides should fetch through this helper
   * rather than calling `gaia.downloadArtifact` directly.
   */
  protected async fetchOutboundArtifact(
    destinationId: string,
    attachment: OutboundAttachment,
  ): Promise<{ data: Buffer; contentType: string } | null> {
    const artifact = await this.gaia.downloadArtifact(
      attachment.conversation_id,
      attachment.path,
      { platform: this.platform, platformUserId: destinationId },
    );
    const limit = OUTBOUND_FILE_LIMITS[this.platform];
    if (artifact.data.length > limit) {
      this.logger.warn("outbound_file_too_large", {
        platform: this.platform,
        filename: attachment.filename,
        bytes: artifact.data.length,
        limit,
      });
      await this.deliverOutbound(
        destinationId,
        renderForPlatform(
          `I generated *${attachment.filename}*, but it's too large to send on ${this.platform} (max ${Math.floor(limit / (1024 * 1024))} MB).`,
          this.platform,
        ),
      );
      return null;
    }
    return artifact;
  }

  /**
   * Delivers a file artifact to `destinationId`. Called by the outbound consumer
   * when an envelope carries an `attachment`. The default sends a short text note
   * via {@link deliverOutbound}; platforms that support attachments (e.g.
   * WhatsApp) override this to fetch the artifact bytes and upload them.
   */
  protected async deliverOutboundFile(
    destinationId: string,
    attachment: OutboundAttachment,
  ): Promise<void> {
    this.logger.warn("outbound_file_fallback_text", {
      platform: this.platform,
      filename: attachment.filename,
    });
    await this.deliverOutbound(
      destinationId,
      `I created *${attachment.filename}*, but I can't send files on ${this.platform} yet.`,
    );
  }

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
    const distinctId = `${this.platform}:${target.userId}`;

    // No identify() — platform-handle PII (username, display_name) is
    // intentionally not shipped to PostHog. Profiles are auto-created from
    // the first capture using the distinctId.

    this.analytics.capture(distinctId, BOT_EVENTS.MESSAGE_RECEIVED, {
      interaction_type: "command",
      command: name,
      has_args: Object.keys(args).length > 0,
      has_raw_text: !!rawText,
      channel_id: target.channelId,
    });

    if (name === "auth") {
      this.analytics.capture(distinctId, BOT_EVENTS.AUTH_INITIATED, {
        channel_id: target.channelId,
      });
    }

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

    const startMs = Date.now();
    try {
      this.logger.info("command_dispatch_started", {
        command: name,
        user_hash: hashLogIdentifier(target.userId),
        channel_hash: hashLogIdentifier(target.channelId),
      });
      await command.execute({ gaia: this.gaia, target, ctx, args, rawText });
      this.analytics.capture(distinctId, BOT_EVENTS.COMMAND_EXECUTED, {
        command: name,
        duration_ms: Date.now() - startMs,
        success: true,
        channel_id: target.channelId,
      });
      this.logger.info("command_dispatch_completed", {
        command: name,
        user_hash: hashLogIdentifier(target.userId),
        channel_hash: hashLogIdentifier(target.channelId),
        duration_ms: Date.now() - startMs,
      });
    } catch (error) {
      const durationMs = Date.now() - startMs;
      const errorType = error instanceof Error ? error.name : "Unknown";
      this.logger.error("command_dispatch_failed", {
        command: name,
        user_hash: hashLogIdentifier(target.userId),
        channel_hash: hashLogIdentifier(target.channelId),
        duration_ms: durationMs,
        error_type: errorType,
        ...sanitizeErrorForLog(error),
      });
      // Capture only the error class name. Raw messages can contain file
      // paths, request IDs, or upstream-echoed tokens — never ship them.
      this.analytics.capture(distinctId, BOT_EVENTS.COMMAND_EXECUTED, {
        command: name,
        duration_ms: durationMs,
        success: false,
        error_type: errorType,
        channel_id: target.channelId,
      });
      this.analytics.capture(distinctId, BOT_EVENTS.ERROR, {
        context: `command:${name}`,
        error_type: errorType,
        channel_id: target.channelId,
      });
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

  /** Users greeted this process, so the welcome fires at most once each. */
  private readonly welcomedUsers = new Set<string>();

  /**
   * One-shot welcome gate shared by adapters that greet a user on first
   * contact (Discord DM embed, WhatsApp text). Returns true the first time it
   * sees a user this process and false thereafter, so a caller can guard its
   * platform-specific welcome with a single check instead of each adapter
   * maintaining its own `Set`.
   */
  protected shouldSendWelcome(userId: string): boolean {
    if (this.welcomedUsers.has(userId)) return false;
    this.welcomedUsers.add(userId);
    return true;
  }

  /**
   * Starts a typing indicator that refreshes until stopped.
   *
   * Platforms expire the "typing…" state after a few seconds, so it must be
   * re-sent periodically during long operations. Adapters supply the
   * platform-specific send call and the refresh cadence; this owns the
   * immediate first send, the interval, swallowing transient send failures,
   * and cleanup. Returns a `stop` function to call from a `finally`.
   */
  protected startTypingIndicator(
    sendTyping: () => Promise<unknown>,
    refreshMs: number,
  ): () => void {
    void sendTyping().catch(() => {});
    const interval = setInterval(() => {
      void sendTyping().catch(() => {});
    }, refreshMs);
    return () => clearInterval(interval);
  }

  /**
   * Routes an inbound media message to the right action — transcribe audio,
   * upload an image/document, or reject an unsupported/oversize payload —
   * returning a {@link MediaOutcome} the adapter then sends through its own
   * channel APIs.
   *
   * The platform-agnostic decision lives in {@link processBotMedia}; this base
   * method injects the shared GAIA client and builds the user context so every
   * adapter calls one inherited method and stays byte-for-byte consistent.
   * `download` is a thunk so unsupported kinds never incur a download.
   */
  protected resolveIncomingMedia(
    media: IncomingMedia,
    download: () => Promise<Uint8Array>,
    userId: string,
    channelId?: string,
  ): Promise<MediaOutcome> {
    return processBotMedia(
      this.gaia,
      media,
      download,
      this.buildContext(userId, channelId),
    );
  }
}
