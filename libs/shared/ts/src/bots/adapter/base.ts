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

import { Analytics, type AnalyticsContext, BOT_EVENTS } from "../../analytics";
import { GaiaClient } from "../api";
import { loadConfig } from "../config";
import type { OutboundAttachment } from "../consumer/envelope";
import { OutboundConsumer } from "../consumer/outbound-consumer";
import type {
  AuthStatus,
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
} from "../utils/logger";
import {
  type IncomingMedia,
  type MediaOutcome,
  OUTBOUND_FILE_LIMITS,
  processBotMedia,
} from "../utils/media";
import { wideLog, withWideEvent } from "../utils/wide-events";
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

  /**
   * Resolved PostHog distinct_id per platform user, for the life of the process.
   *
   * A cache, not a source of truth: the link state lives in MongoDB behind
   * `checkAuthStatus`. It exists because the id is needed on every event and an
   * HTTP round trip per capture would put the analytics path in the latency
   * budget of every message.
   */
  private readonly distinctIdCache = new Map<string, string>();

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
   * Emits one canonical `bot_boot` wide event covering the whole sequence, so a
   * bot that dies during startup says why — with a duration and an outcome —
   * instead of leaving a "boot_started" line and silence.
   *
   * @param commands - Array of unified {@link BotCommand} definitions to register.
   */
  async boot(commands: BotCommand[]): Promise<void> {
    this.logger = createBotLogger(this.platform, "base-adapter");

    await withWideEvent(
      "bot_boot",
      {
        platform: this.platform,
        component: "base-adapter",
        command_count: commands.length,
      },
      async () => {
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
        wideLog.set({ server_port: serverPort });

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
          wideLog.set({
            boot_stage: platformStarted ? "serving" : "connecting",
          });
          if (platformStarted) {
            await this.stop().catch(() => undefined);
          }
          await this._outboundConsumer?.stop().catch(() => undefined);
          this._outboundConsumer = null;
          await this._botServer?.stop().catch(() => undefined);
          this._botServer = null;
          throw error;
        }
      },
    );
  }

  /**
   * Gracefully shuts down the adapter.
   *
   * Called from the process signal handlers wired by `runBotProcess`, and from
   * any adapter that decides it cannot keep running. Delegates to the
   * platform-specific {@link stop} implementation and emits one canonical
   * `bot_shutdown` wide event naming what triggered it.
   *
   * @param trigger - What asked for the shutdown (`"SIGTERM"`, `"long_poll_fatal"`, …).
   */
  async shutdown(trigger: string): Promise<void> {
    await withWideEvent(
      "bot_shutdown",
      { platform: this.platform, component: "base-adapter", trigger },
      async () => {
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
      },
    );
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
    // loadConfig() already warned (config_optional_missing / RABBITMQ_URL) on
    // this same boot event — saying it twice does not make it truer.
    if (!url) return;
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
      // `platform` is already on every line's envelope — repeating it as a
      // field collides with the reserved key and lands as `ctx_platform`.
      wideLog.warning("outbound_file_too_large", {
        attachment_filename: attachment.filename,
        bytes: artifact.data.length,
        limit,
      });
      // A generated artifact the user never receives. Captured, not just
      // logged: this is a product failure with a per-platform size cause, and
      // its rate is the signal for raising a limit or chunking the output.
      this.analytics.capture(
        await this.resolveDistinctId(destinationId),
        BOT_EVENTS.FILE_DELIVERED,
        {
          success: false,
          reason: "too_large",
          bytes: artifact.data.length,
          limit,
        },
      );
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
    wideLog.warning("outbound_file_fallback_text", {
      attachment_filename: attachment.filename,
    });
    // The base implementation IS the "this platform can't send files" path —
    // platforms that can (WhatsApp) override the whole method and capture their
    // own success. Reaching here always means the user got text instead of the
    // artifact they asked for.
    this.analytics.capture(
      await this.resolveDistinctId(destinationId),
      BOT_EVENTS.FILE_DELIVERED,
      { success: false, reason: "platform_unsupported" },
    );
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
    const distinctId = await this.resolveDistinctId(target.userId);
    const userHash = hashLogIdentifier(target.userId);
    const channelHash = hashLogIdentifier(target.channelId);

    await withWideEvent(
      "command",
      {
        platform: this.platform,
        component: "base-adapter",
        command: name,
        user_hash: userHash,
        channel_hash: channelHash,
      },
      async () => {
        // No identify() — platform-handle PII (username, display_name) is
        // intentionally not shipped to PostHog. Profiles are auto-created from
        // the first capture using the distinctId.

        this.analytics.capture(distinctId, BOT_EVENTS.MESSAGE_RECEIVED, {
          interaction_type: "command",
          command: name,
          has_args: Object.keys(args).length > 0,
          has_raw_text: !!rawText,
        });

        if (name === "auth") {
          wideLog.audit("auth_link_requested", { user_hash: userHash });
          this.analytics.capture(distinctId, BOT_EVENTS.AUTH_INITIATED, {});
        }

        const command = this.commands.get(name);
        if (!command) {
          wideLog.warning("unknown_command", { command: name });
          await target.sendEphemeral(`Unknown command: /${name}`);
          return;
        }

        const ctx = this.buildContext(
          target.userId,
          target.channelId,
          target.profile,
          target.isDm,
        );

        const startMs = Date.now();
        try {
          await command.execute({
            gaia: this.gaia,
            target,
            ctx,
            args,
            rawText,
          });
          this.analytics.capture(distinctId, BOT_EVENTS.COMMAND_EXECUTED, {
            command: name,
            duration_ms: Date.now() - startMs,
            success: true,
          });
        } catch (error) {
          const durationMs = Date.now() - startMs;
          const errorType = error instanceof Error ? error.name : "Unknown";
          wideLog.error(
            "command_dispatch_failed",
            {
              command: name,
              user_hash: userHash,
              channel_hash: channelHash,
              duration_ms: durationMs,
              error_type: errorType,
            },
            error,
          );
          // Capture only the error class name. Raw messages can contain file
          // paths, request IDs, or upstream-echoed tokens — never ship them.
          this.analytics.capture(distinctId, BOT_EVENTS.COMMAND_EXECUTED, {
            command: name,
            duration_ms: durationMs,
            success: false,
            error_type: errorType,
          });
          this.analytics.capture(distinctId, BOT_EVENTS.ERROR, {
            context: `command:${name}`,
            error_type: errorType,
          });
          const errMsg = formatBotError(error);
          try {
            await target.sendEphemeral(errMsg);
          } catch {
            // Target may be expired (e.g. Discord interaction timeout).
            wideLog.warning("error_notice_send_failed", { command: name });
          }
        }
      },
    );
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
    isDm?: boolean,
  ): CommandContext {
    return {
      platform: this.platform,
      platformUserId: userId,
      channelId,
      isDm,
      profile,
    };
  }

  /** Unlinked users greeted this process, deduped so the welcome does not repeat on every message. */
  private readonly welcomedUsers = new Set<string>();

  /**
   * The PostHog distinct_id for a platform user: their stable GAIA user id once
   * the account is linked, otherwise `"<platform>:<platformUserId>"`.
   *
   * Keying on the GAIA id is what lets a person's bot activity land on the same
   * profile as their web and API activity — the backend already attributes bot
   * chat turns that way (`bot.py::chat`), so without this the same turn produced
   * two people. An unlinked user genuinely has no GAIA identity yet, so the
   * platform id stands in until they link; {@link alias} then folds that history
   * into the real profile.
   *
   * A failed lookup degrades to the platform id rather than dropping the event:
   * an event on the anonymous profile is recoverable, a missing one is not.
   */
  protected async resolveDistinctId(platformUserId: string): Promise<string> {
    const cached = this.distinctIdCache.get(platformUserId);
    if (cached) return cached;

    const platformDistinctId = `${this.platform}:${platformUserId}`;
    let status: AuthStatus;
    try {
      status = await this.gaia.checkAuthStatus(this.platform, platformUserId);
    } catch (error) {
      this.logger.error(
        "analytics_identity_resolve_failed",
        { user_hash: hashLogIdentifier(platformUserId) },
        error,
      );
      return platformDistinctId;
    }

    if (!status.user_id) return platformDistinctId;

    // First resolution for this user in this process: stitch whatever they did
    // before linking onto the GAIA profile. Cached below, so it fires once per
    // process rather than per message.
    this.analytics.alias(platformDistinctId, status.user_id);
    this.distinctIdCache.set(platformUserId, status.user_id);
    return status.user_id;
  }

  /**
   * The analytics client bound to this user's resolved identity, for handing to
   * shared helpers like {@link handleStreamingChat}.
   */
  protected async analyticsFor(
    platformUserId: string,
  ): Promise<AnalyticsContext> {
    return {
      client: this.analytics,
      distinctId: await this.resolveDistinctId(platformUserId),
    };
  }

  /**
   * Welcome gate shared by adapters that greet a user on first contact (Discord
   * DM embed, WhatsApp text).
   *
   * Greets a user ONLY while they have not linked their GAIA account. Linked
   * users never see the welcome — deterministically, because the decision is
   * driven by the persistent auth status (MongoDB), not by process memory. This
   * fixes the bug where a restart re-greeted already-linked users. For an
   * unlinked user it still fires at most once per process so the greeting does
   * not repeat on every message while they remain unlinked.
   */
  protected async shouldSendWelcome(userId: string): Promise<boolean> {
    if (this.welcomedUsers.has(userId)) return false;
    // Mark in-flight before the await so two concurrent first messages can't
    // both pass the check and send duplicate welcomes. Cleared again whenever
    // the user turns out to be authenticated or the check fails.
    this.welcomedUsers.add(userId);
    try {
      const status = await this.gaia.checkAuthStatus(this.platform, userId);
      if (status.authenticated) {
        this.welcomedUsers.delete(userId);
        return false;
      }
    } catch (error) {
      this.welcomedUsers.delete(userId);
      this.logger.error(
        "welcome_auth_check_failed",
        { user_hash: hashLogIdentifier(userId) },
        error,
      );
      return false;
    }
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
    void sendTyping().catch(() => {
      /* transient typing-indicator send failures are intentionally swallowed */
    });
    const interval = setInterval(() => {
      void sendTyping().catch(() => {
        /* transient typing-indicator send failures are intentionally swallowed */
      });
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
   *
   * Owns the media pipeline's wide-event boundary: the download, the Whisper
   * transcription and the upload all happen before any chat boundary exists, so
   * without this every attachment's latency and rejection reason was dark.
   */
  protected resolveIncomingMedia(
    media: IncomingMedia,
    download: (maxBytes: number) => Promise<Uint8Array>,
    userId: string,
    channelId?: string,
  ): Promise<MediaOutcome> {
    return withWideEvent(
      "media_intake",
      {
        platform: this.platform,
        component: "base-adapter",
        user_hash: hashLogIdentifier(userId),
        channel_hash: hashLogIdentifier(channelId),
        media_kind: media.kind,
        is_voice_note: media.isVoiceNote,
      },
      async () => {
        // Every inbound attachment on every platform funnels through here, so
        // this is the one place the upload can be counted. `outcome` separates
        // an attachment GAIA actually ingested ("chat") from one it turned away
        // as unsupported or oversize ("reply") — the rejection rate is the
        // number worth watching. No filename: it is user content.
        const outcome = await processBotMedia(
          this.gaia,
          media,
          download,
          this.buildContext(userId, channelId),
        );
        this.analytics.capture(
          await this.resolveDistinctId(userId),
          BOT_EVENTS.FILE_UPLOADED,
          {
            media_kind: media.kind,
            is_voice_note: Boolean(media.isVoiceNote),
            outcome: outcome.action === "chat" ? "ingested" : "rejected",
          },
        );
        return outcome;
      },
    );
  }
}
