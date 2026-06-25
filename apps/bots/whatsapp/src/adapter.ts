/**
 * WhatsApp bot adapter for GAIA.
 *
 * Extends {@link BaseBotAdapter} to wire unified commands and events
 * to the Kapso webhook framework. Handles WhatsApp-specific concerns:
 *
 * - **Webhook server** via Hono + @hono/node-server
 * - **Signature verification** via HMAC-SHA256 on raw body
 * - **Text commands** matched by prefix (e.g. "/gaia ...")
 * - **Rich messages** rendered as WhatsApp markdown (*bold*, _italic_)
 * - **No streaming** — full response sent once complete (streaming: false)
 * - **No message editing** — WhatsApp API does not support edits
 * - **Typing indicator** fired once per message (Meta hard-caps bubble at 25s)
 *
 * @module
 */

import {
  BaseBotAdapter,
  type BotCommand,
  type BotFileData,
  buildAuthLinkMessage,
  createBotLogger,
  extractSubcommandArgs,
  friendlyMediaError,
  handleStreamingChat,
  hashLogIdentifier,
  type IncomingMedia,
  type OutboundAttachment,
  type PlatformName,
  type RichMessage,
  type RichMessageTarget,
  renderForPlatform,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
  sanitizeErrorForLog,
  unsupportedMediaMessage,
} from "@gaia/shared";
import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import {
  NOTIFICATION_TEMPLATE_LANGUAGE,
  NOTIFICATION_TEMPLATE_NAME,
  NOTIFICATION_TEMPLATE_PARAM_NAME,
  REPLAY_WINDOW_MS,
  TEMPLATE_BODY_MAX_LENGTH,
  TYPING_REFRESH_MS,
} from "./constants";
import {
  extractMedia,
  extractTextBody,
  extractWaId,
  verifyKapsoSignature,
} from "./webhook";
import type {
  ExtractedMedia,
  KapsoMessageBatch,
  KapsoMessageEvent,
} from "./webhook.types";

// ─── WhatsApp-specific config ─────────────────────────────────────────────────

/** WhatsApp image-message byte cap; larger images are sent as documents. */
const WHATSAPP_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

interface WhatsAppConfig {
  kapsoApiKey: string;
  kapsoPhoneNumberId: string;
  kapsoWebhookSecret: string;
}

function loadWhatsAppConfig(): WhatsAppConfig {
  const kapsoApiKey = process.env.KAPSO_API_KEY;
  const kapsoPhoneNumberId = process.env.KAPSO_PHONE_NUMBER_ID;
  const kapsoWebhookSecret = process.env.KAPSO_WEBHOOK_SECRET;

  if (!kapsoApiKey) throw new Error("KAPSO_API_KEY is required");
  if (!kapsoPhoneNumberId) throw new Error("KAPSO_PHONE_NUMBER_ID is required");
  if (!kapsoWebhookSecret) throw new Error("KAPSO_WEBHOOK_SECRET is required");

  return { kapsoApiKey, kapsoPhoneNumberId, kapsoWebhookSecret };
}

/**
 * Collapses rendered notification text into a single line suitable for a
 * template body variable. Meta forbids newlines, tabs, or 4+ consecutive
 * spaces inside template parameters and caps the body length, so whitespace is
 * normalized and the result truncated.
 */
function toTemplateParameter(text: string): string {
  const collapsed = text.replace(/\s+/g, " ").trim();
  return collapsed.length > TEMPLATE_BODY_MAX_LENGTH
    ? `${collapsed.slice(0, TEMPLATE_BODY_MAX_LENGTH - 1)}…`
    : collapsed;
}

// ─── WhatsApp Adapter ─────────────────────────────────────────────────────────

export class WhatsAppAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "whatsapp";
  protected readonly defaultServerPort = 3203;

  private waClient: WhatsAppClient | null = null;
  private waConfig: WhatsAppConfig | null = null;

  /**
   * Tracks users whose platform_links status has been confirmed as linked this
   * process. Avoids a backend round-trip on every first-seen message after restart.
   */
  private readonly linkedUsers = new Set<string>();
  /**
   * Per-user message processing queue. Serializes handleIncomingMessage calls for
   * the same waId so rapid messages or batched webhook deliveries never run in
   * parallel — eliminates overlapping typing states and interleaved replies.
   */
  private readonly messageQueues = new Map<string, Promise<void>>();
  private readonly adapterLogger = createBotLogger("whatsapp", "adapter");

  private get whatsAppClient(): WhatsAppClient {
    if (!this.waClient) {
      throw new Error("WhatsApp client not initialized — call boot() first");
    }
    return this.waClient;
  }

  private get whatsAppConfig(): WhatsAppConfig {
    if (!this.waConfig) {
      throw new Error("WhatsApp config not initialized — call boot() first");
    }
    return this.waConfig;
  }

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /** Initializes the Kapso WhatsApp client using environment variables. */
  protected async initialize(): Promise<void> {
    this.waConfig = loadWhatsAppConfig();
    this.waClient = new WhatsAppClient({
      baseUrl: "https://api.kapso.ai/meta/whatsapp",
      kapsoApiKey: this.waConfig.kapsoApiKey,
    });
    this.adapterLogger.info("client_initialized", {
      phone_number_id: this.waConfig.kapsoPhoneNumberId,
    });
  }

  /** WhatsApp has no platform-level command registration step. */
  protected async registerCommands(_commands: BotCommand[]): Promise<void> {
    this.adapterLogger.info("commands_registered");
  }

  /**
   * Mounts the Kapso webhook handler on the shared base server.
   *
   * The base server already provides `GET /health`. This method adds:
   *
   * - POST /webhook → verifies Kapso HMAC signature, dispatches message
   */
  protected async registerEvents(): Promise<void> {
    this.botServer.app.post("/webhook", async (c) => {
      const rawBody = await c.req.text();
      const signature = c.req.header("x-webhook-signature") ?? null;

      if (
        !verifyKapsoSignature(
          rawBody,
          signature,
          this.whatsAppConfig.kapsoWebhookSecret,
        )
      ) {
        return c.json({ error: "Invalid signature" }, 401);
      }

      // Event type is in the header for Kapso webhooks, not in the body
      const eventType = c.req.header("x-webhook-event") ?? null;
      if (eventType !== "whatsapp.message.received") {
        this.adapterLogger.debug("webhook_event_ignored", {
          event_type: eventType,
        });
        return c.json({ status: "ignored" });
      }

      let body: unknown;
      try {
        body = JSON.parse(rawBody);
      } catch {
        return c.json({ error: "Invalid JSON" }, 400);
      }

      // Batched delivery wraps events in { batch: true, data: [...] }
      const isBatch = c.req.header("x-webhook-batch") === "true";
      const events: KapsoMessageEvent[] = isBatch
        ? (body as KapsoMessageBatch).data
        : [body as KapsoMessageEvent];

      for (const event of events) {
        this.handleWebhookEvent(event);
      }

      return c.json({ status: "ok" });
    });
  }

  /**
   * Validates and routes a single inbound Kapso event. Drops events with an
   * invalid, future, or replayed timestamp, then enqueues text, media, or
   * unsupported-media handling (serialized per user).
   */
  private handleWebhookEvent(event: KapsoMessageEvent): void {
    const waId = extractWaId(event);
    const waIdHash = hashLogIdentifier(waId);
    const text = extractTextBody(event);

    const timestampSec = Number(event.message.timestamp);
    if (!Number.isFinite(timestampSec)) {
      this.adapterLogger.warn("webhook_invalid_timestamp", {
        wa_hash: waIdHash,
        message_id: event.message.id,
      });
      return;
    }
    const eventAgeMs = Date.now() - timestampSec * 1000;
    if (eventAgeMs < 0) {
      this.adapterLogger.warn("webhook_future_timestamp", {
        wa_hash: waIdHash,
        message_id: event.message.id,
        age_ms: eventAgeMs,
      });
      return;
    }
    if (eventAgeMs > REPLAY_WINDOW_MS) {
      this.adapterLogger.warn("webhook_event_replayed", {
        wa_hash: waIdHash,
        message_id: event.message.id,
        age_ms: eventAgeMs,
      });
      return;
    }

    this.adapterLogger.info("webhook_message_received", {
      wa_hash: waIdHash,
      message_type: event.message.type,
      has_text: Boolean(text),
    });
    const msgId = event.message.id;

    // Enqueue per user — webhook returns 200 immediately while processing is
    // serialized: messages from the same user run one at a time, in order.
    if (text) {
      this.enqueueForUser(waId, () =>
        this.handleIncomingMessage(waId, text, msgId).catch((err) =>
          this.adapterLogger.error("incoming_message_processing_failed", {
            wa_hash: waIdHash,
            message_id: msgId,
            ...sanitizeErrorForLog(err),
          }),
        ),
      );
      return;
    }
    if (event.message.type === "text") return;

    // Non-text message — try to handle as media (image/audio/voice/doc).
    const media = extractMedia(event);
    if (!media) {
      // No usable media descriptor (sticker without id, unknown type, etc.)
      // Fall back to the friendly rejection.
      this.enqueueForUser(waId, async () => {
        try {
          await this.sendWhatsAppText(
            waId,
            unsupportedMediaMessage(event.message.type),
          );
        } catch (err) {
          this.adapterLogger.error("unsupported_media_handling_failed", {
            wa_hash: waIdHash,
            message_type: event.message.type,
            ...sanitizeErrorForLog(err),
          });
        }
      });
      return;
    }

    this.enqueueForUser(waId, () =>
      this.handleMediaMessage(waId, media, msgId).catch((err) =>
        this.adapterLogger.error("media_message_processing_failed", {
          wa_hash: waIdHash,
          message_id: msgId,
          media_kind: media.kind,
          ...sanitizeErrorForLog(err),
        }),
      ),
    );
  }

  /**
   * Shows the WhatsApp "typing…" indicator and keeps it alive for the whole
   * generation.
   *
   * The WhatsApp Cloud API typing indicator (emitted by marking the inbound
   * message read) auto-dismisses after ~25s or when the reply is sent. A single
   * emit therefore leaves the user staring at a dead chat whenever generation
   * runs long — markdown-heavy answers routinely exceed 25s. So we re-emit every
   * {@link TYPING_REFRESH_MS} (well under the 25s ceiling) until {@link stop} is
   * called from the request's `finally`. Re-emitting while the indicator is still
   * active extends the window instead of flickering it.
   *
   * `refresh` forces an immediate re-emit (used to re-show it right after an
   * interstitial message such as the welcome); `stop` cancels the keep-alive.
   */
  private startWhatsAppTyping(
    waId: string,
    messageId: string,
  ): { refresh: () => void; stop: () => void } {
    const waIdHash = hashLogIdentifier(waId);
    const startedAt = Date.now();
    let emitCount = 0;
    let stopped = false;
    const sendTyping = (): void => {
      if (stopped) return;
      emitCount += 1;
      const seq = emitCount;
      this.adapterLogger.debug("typing_indicator_emitted", {
        wa_hash: waIdHash,
        message_id: messageId,
        seq,
        elapsed_ms: Date.now() - startedAt,
      });
      this.whatsAppClient.messages
        .markRead({
          phoneNumberId: this.whatsAppConfig.kapsoPhoneNumberId,
          messageId,
          typingIndicator: { type: "text" },
        })
        .catch((err: unknown) =>
          this.adapterLogger.error("typing_indicator_failed", {
            wa_hash: waIdHash,
            message_id: messageId,
            seq,
            ...sanitizeErrorForLog(err),
          }),
        );
    };
    sendTyping();
    const keepAlive = setInterval(sendTyping, TYPING_REFRESH_MS);
    return {
      refresh: sendTyping,
      stop: () => {
        stopped = true;
        clearInterval(keepAlive);
      },
    };
  }

  /**
   * Sends the one-time welcome to an unlinked, first-time user (tracked for the
   * process lifetime). Linked users are cached and skipped. `refreshTyping` is
   * re-fired after the welcome so the indicator survives the extra message.
   */
  private async ensureWelcomed(
    waId: string,
    refreshTyping: () => void,
    authCheckTimeoutMs?: number,
  ): Promise<void> {
    // Base gate (shared with Discord): only greets unlinked users, at most once per process.
    if (!(await this.shouldSendWelcome(waId))) return;

    let isLinked = this.linkedUsers.has(waId);
    if (!isLinked) {
      isLinked = await this.isWaUserLinked(waId, authCheckTimeoutMs);
    }
    if (!isLinked) {
      await this.sendWelcome(waId);
      refreshTyping();
    }
  }

  /**
   * Resolves whether a WhatsApp user is linked to a GAIA account, caching a
   * positive result. Failures (including the optional timeout) resolve to
   * `false` so the welcome path degrades gracefully.
   */
  private async isWaUserLinked(
    waId: string,
    timeoutMs?: number,
  ): Promise<boolean> {
    try {
      const statusPromise = this.gaia.checkAuthStatus("whatsapp", waId);
      const status =
        timeoutMs === undefined
          ? await statusPromise
          : await Promise.race([
              statusPromise,
              new Promise<never>((_, reject) =>
                setTimeout(
                  () => reject(new Error("auth_check_timeout")),
                  timeoutMs,
                ),
              ),
            ]);
      if (status.authenticated) this.linkedUsers.add(waId);
      return status.authenticated;
    } catch (err) {
      this.adapterLogger.warn("welcome_auth_check_failed", {
        wa_hash: hashLogIdentifier(waId),
        ...sanitizeErrorForLog(err),
      });
      return false;
    }
  }

  /** Nothing additional to start — base server is started by BaseBotAdapter.boot(). */
  protected async start(): Promise<void> {
    this.adapterLogger.info("bot_started");
  }

  /** Nothing additional to stop — base server is stopped by BaseBotAdapter.shutdown(). */
  protected stop(): Promise<void> {
    return Promise.resolve();
  }

  // ---------------------------------------------------------------------------
  // Message handling
  // ---------------------------------------------------------------------------

  /**
   * Serializes message processing per user. Chains the new task onto the tail of
   * the existing promise for this waId so messages are always handled one at a
   * time, in order. Cleans up the map entry once the task settles.
   */
  private enqueueForUser(waId: string, fn: () => Promise<void>): void {
    const previous = this.messageQueues.get(waId) ?? Promise.resolve();
    const task = previous
      .catch(() => undefined) // previous failure must not block the queue
      .then(() => fn());
    this.messageQueues.set(waId, task);
    task.then(
      () => {
        if (this.messageQueues.get(waId) === task)
          this.messageQueues.delete(waId);
      },
      () => {
        if (this.messageQueues.get(waId) === task)
          this.messageQueues.delete(waId);
      },
    );
  }

  /**
   * Dispatches an incoming WhatsApp message to the appropriate handler.
   *
   * Shows a typing indicator immediately (mark-as-read + typing via Kapso API),
   * then routes:
   * - Messages starting with "/" are parsed as commands
   * - `/gaia <text>` invokes streaming chat
   * - Other `/command` messages invoke the unified command dispatcher
   * - Plain text messages are treated as implicit `/gaia` chat
   */
  private async handleIncomingMessage(
    waId: string,
    text: string,
    messageId: string,
  ): Promise<void> {
    const waIdHash = hashLogIdentifier(waId);
    this.adapterLogger.info("incoming_message_started", {
      wa_hash: waIdHash,
      message_id: messageId,
      text_length: text.length,
      is_command: text.startsWith("/"),
    });

    const typing = this.startWhatsAppTyping(waId, messageId);

    try {
      await this.ensureWelcomed(waId, typing.refresh, 2_000);

      const target = this.createWaTarget(waId, messageId);

      if (text.startsWith("/")) {
        const withoutSlash = text.slice(1);
        const spaceIndex = withoutSlash.indexOf(" ");
        const commandName = (
          spaceIndex === -1 ? withoutSlash : withoutSlash.slice(0, spaceIndex)
        ).toLowerCase();
        const rest =
          spaceIndex === -1 ? "" : withoutSlash.slice(spaceIndex + 1).trim();

        if (commandName === "gaia") {
          if (!rest) {
            await this.sendWhatsAppText(waId, "Usage: /gaia <your message>");
            return;
          }
          await this.handleStreamingMessage(waId, rest);
          return;
        }

        const args = extractSubcommandArgs(commandName, rest);

        await this.dispatchCommand(
          commandName,
          target,
          args,
          rest || undefined,
        );
        return;
      }

      await this.handleStreamingMessage(waId, text);
    } finally {
      typing.stop();
    }
  }

  /**
   * Sends the user's message to the GAIA streaming endpoint.
   *
   * WhatsApp streaming is disabled (STREAMING_DEFAULTS.whatsapp.streaming = false),
   * so the full response is accumulated and sent as a single message. The caller's
   * typing keep-alive (see {@link startWhatsAppTyping}) keeps "typing…" visible for
   * the whole generation and is cancelled in the caller's `finally`.
   *
   * @param attachments - Files already uploaded to GAIA's storage (via
   *   {@link GaiaClient.uploadFile}) that should accompany this message so
   *   the agent can ground its reply in their contents.
   */
  private async handleStreamingMessage(
    waId: string,
    text: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    if (!text.trim() && attachments.length === 0) {
      await this.sendWhatsAppText(
        waId,
        "Hi! Send me a message and I'll help you. Type /help for available commands.",
      );
      return;
    }

    let lastEditFn: ((t: string) => Promise<void>) | null = null;
    let finalMessageSent = false;

    try {
      await handleStreamingChat(
        this.gaia,
        {
          message: text || "Please describe the attached file.",
          platform: "whatsapp",
          platformUserId: waId,
          channelId: waId,
          ...(attachments.length > 0
            ? {
                fileIds: attachments.map((a) => a.fileId),
                fileData: attachments,
              }
            : {}),
        },
        // editMessage: no placeholder to edit — send as new message on first call.
        // ``formatted`` already ran through PLATFORM_MARKDOWN in handleStreamingChat.
        async (formatted: string) => {
          if (finalMessageSent) {
            // WhatsApp has no edit API — edit() sends a new message.
            // Guard against sending multiple new messages if streaming is
            // ever re-enabled or editMessage is called more than once.
            return;
          }
          finalMessageSent = true;
          if (lastEditFn) {
            await lastEditFn(formatted);
          } else {
            const sent = await this.sendWhatsAppText(waId, formatted);
            lastEditFn = sent.edit;
          }
        },
        // sendNewMessage: send a new message and return its edit function
        async (newText: string) => {
          const sent = await this.sendWhatsAppText(waId, newText);
          lastEditFn = sent.edit;
          return sent.edit;
        },
        // onAuthError
        async (authUrl: string) => {
          await this.sendWhatsAppText(
            waId,
            renderForPlatform(buildAuthLinkMessage(authUrl), "whatsapp"),
          );
        },
        // onGenericError
        async (errMsg: string) => {
          await this.sendWhatsAppText(waId, errMsg);
        },
        STREAMING_DEFAULTS.whatsapp,
        this.analytics,
      );
    } catch (err) {
      this.adapterLogger.error("streaming_failed", {
        wa_hash: hashLogIdentifier(waId),
        ...sanitizeErrorForLog(err),
      });
      try {
        await this.sendWhatsAppText(
          waId,
          "An error occurred. Please try again.",
        );
      } catch (sendErr) {
        this.adapterLogger.error("streaming_error_message_send_failed", {
          wa_hash: hashLogIdentifier(waId),
          ...sanitizeErrorForLog(sendErr),
        });
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Welcome message
  // ---------------------------------------------------------------------------

  /**
   * Sends a welcome message to a first-time WhatsApp user.
   *
   * Adapted from Discord's DM welcome embed — rendered as WhatsApp markdown
   * since WhatsApp has no native embed/button support.
   *
   * Gated by platform_links check via `gaia.checkAuthStatus` (2s timeout) — linked
   * users skip the welcome entirely and are cached in {@link linkedUsers} for the
   * process lifetime. Unlinked users receive it once per process restart at
   * most, gated by the shared {@link BaseBotAdapter.shouldSendWelcome}.
   */
  private async sendWelcome(waId: string): Promise<void> {
    const text =
      `*Hey, I'm GAIA* 👋\n\n` +
      `Your personal AI — I think ahead, remember what matters, and help you actually get things done.\n\n` +
      `Here's what I can do right here on WhatsApp:\n\n` +
      `*Chat*\nJust type anything — ask questions, brainstorm, think out loud.\n\n` +
      `*Todos*\nCapture tasks with /todo add.\n\n` +
      `*Workflows*\nRun automations with /workflow and delegate whole projects.\n\n` +
      `*Link your account*\nRun /auth to connect GAIA so I remember you and your context.\n\n` +
      `_Visit heygaia.io or read the docs at docs.heygaia.io_`;

    try {
      await this.sendWhatsAppText(waId, text);
    } catch (error) {
      this.adapterLogger.error(
        "welcome_send_failed",
        { wa_hash: hashLogIdentifier(waId) },
        error,
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Media handling
  // ---------------------------------------------------------------------------

  /**
   * Handles an inbound media message (image, audio, voice note, or document).
   *
   * Platform-specific responsibilities only: typing indicator, welcome gate,
   * downloading the bytes via Kapso, and mapping the Kapso descriptor onto the
   * shared {@link IncomingMedia} shape. The actual decision (transcribe vs
   * upload vs reject, size caps, prompts) lives in {@link processBotMedia} so
   * Telegram and WhatsApp behave identically. The reply path then folds back
   * into {@link handleStreamingMessage}, identical to plain text.
   */
  private async handleMediaMessage(
    waId: string,
    media: ExtractedMedia,
    messageId: string,
  ): Promise<void> {
    const waIdHash = hashLogIdentifier(waId);
    this.adapterLogger.info("media_message_started", {
      wa_hash: waIdHash,
      message_id: messageId,
      media_kind: media.kind,
      is_voice_note: media.isVoiceNote,
      mime_type: media.mimeType,
    });

    // Always show typing first — matches the text path so the UX is identical.
    const typing = this.startWhatsAppTyping(waId, messageId);

    try {
      // Welcome gate runs once per process per user — same as text path.
      await this.ensureWelcomed(waId, typing.refresh);

      const incoming: IncomingMedia = {
        kind: media.kind,
        isVoiceNote: media.isVoiceNote,
        mimeType: media.mimeType,
        filename: media.filename,
        caption: media.caption,
      };
      const outcome = await this.resolveIncomingMedia(
        incoming,
        () => this.downloadMediaBytes(media),
        waId,
        waId,
      );

      if (outcome.action === "reply") {
        await this.sendWhatsAppText(waId, outcome.text);
      } else {
        await this.handleStreamingMessage(
          waId,
          outcome.text,
          outcome.attachments,
        );
      }
    } catch (err) {
      this.adapterLogger.error("media_message_failed", {
        wa_hash: waIdHash,
        message_id: messageId,
        media_kind: media.kind,
        ...sanitizeErrorForLog(err),
      });
      try {
        await this.sendWhatsAppText(
          waId,
          friendlyMediaError(media.kind, err, this.gaia.getPricingUrl()),
        );
      } catch (sendErr) {
        this.adapterLogger.error("media_error_message_send_failed", {
          wa_hash: waIdHash,
          ...sanitizeErrorForLog(sendErr),
        });
      }
    } finally {
      typing.stop();
    }
  }

  /** Downloads the raw bytes for a media message via the Kapso SDK. */
  private async downloadMediaBytes(media: ExtractedMedia): Promise<Uint8Array> {
    const arrayBuf = (await this.whatsAppClient.media.download({
      mediaId: media.mediaId,
      phoneNumberId: this.whatsAppConfig.kapsoPhoneNumberId,
    })) as ArrayBuffer;
    return new Uint8Array(arrayBuf);
  }

  // ---------------------------------------------------------------------------
  // Message target factory
  // ---------------------------------------------------------------------------

  /**
   * Creates a {@link RichMessageTarget} for sending messages to a WhatsApp user.
   *
   * - `send` / `sendEphemeral` send a text message (no ephemeral concept in WhatsApp)
   * - `sendRich` renders {@link RichMessage} as WhatsApp markdown
   * - `edit` sends a NEW message (WhatsApp does not support editing)
   * - `startTyping` is a no-op — typing is already managed by `handleIncomingMessage`
   */
  private createWaTarget(waId: string, _messageId: string): RichMessageTarget {
    return {
      platform: "whatsapp",
      userId: waId,
      channelId: waId,

      send: async (text: string): Promise<SentMessage> => {
        return this.sendWhatsAppText(waId, renderForPlatform(text, "whatsapp"));
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        // WhatsApp has no ephemeral concept — send normally
        return this.sendWhatsAppText(waId, renderForPlatform(text, "whatsapp"));
      },

      sendRich: async (richMsg: RichMessage): Promise<SentMessage> => {
        // richMessageToMarkdown emits platform-agnostic CommonMark; convert it
        // to WhatsApp formatting through the single shared chokepoint so field
        // values that contain markdown render correctly.
        const markdown = renderForPlatform(
          richMessageToMarkdown(richMsg),
          "whatsapp",
        );
        return this.sendWhatsAppText(waId, markdown);
      },

      startTyping: async () => {
        // Typing indicator is already shown (and refreshed every 20s) by
        // handleIncomingMessage for the full duration of processing.
        // No second interval needed here.
        return () => undefined;
      },
    };
  }

  // ---------------------------------------------------------------------------
  // Internal send helper
  // ---------------------------------------------------------------------------

  /**
   * Sends a text message to a WhatsApp user via the Kapso SDK.
   *
   * Returns a {@link SentMessage} whose `edit` function sends a NEW message
   * (WhatsApp does not support editing existing messages).
   */
  private async sendWhatsAppText(
    waId: string,
    text: string,
  ): Promise<SentMessage> {
    const response = await this.whatsAppClient.messages.sendText({
      phoneNumberId: this.whatsAppConfig.kapsoPhoneNumberId,
      to: `+${waId}`,
      body: text,
      previewUrl: false,
    });

    const messageId = response.messages[0]?.id ?? "";

    return {
      id: messageId,
      edit: async (updatedText: string): Promise<void> => {
        // WhatsApp does not support message editing — send a new message instead
        await this.whatsAppClient.messages.sendText({
          phoneNumberId: this.whatsAppConfig.kapsoPhoneNumberId,
          to: `+${waId}`,
          body: updatedText,
          previewUrl: false,
        });
      },
    };
  }

  protected async deliverOutbound(
    destinationId: string,
    text: string,
  ): Promise<void> {
    try {
      await this.sendWhatsAppText(destinationId, text);
    } catch (err) {
      // Free-form send failed — most often the 24-hour window is closed. Fall
      // back to the approved template (sendable any time); if it also fails it
      // rethrows so the consumer dead-letters it. The original error is logged
      // so a non-window failure stays visible.
      this.adapterLogger.info("outbound_template_fallback", {
        wa_hash: hashLogIdentifier(destinationId),
        ...sanitizeErrorForLog(err),
      });
      await this.sendNotificationTemplate(destinationId, text);
    }
  }

  /**
   * Delivers notification text via the approved `gaia_notification` utility
   * template. Used as the re-engagement fallback when free-form delivery fails
   * because the 24-hour window is closed. The full rendered text is flattened
   * into the template's single `body` variable.
   */
  private async sendNotificationTemplate(
    waId: string,
    text: string,
  ): Promise<void> {
    await this.whatsAppClient.messages.sendTemplate({
      phoneNumberId: this.whatsAppConfig.kapsoPhoneNumberId,
      to: `+${waId}`,
      template: {
        name: NOTIFICATION_TEMPLATE_NAME,
        language: { code: NOTIFICATION_TEMPLATE_LANGUAGE },
        components: [
          {
            type: "body",
            parameters: [
              {
                type: "text",
                text: toTemplateParameter(text),
                parameterName: NOTIFICATION_TEMPLATE_PARAM_NAME,
              },
            ],
          },
        ],
      },
    });
  }

  /**
   * Delivers an agent-generated file artifact to a WhatsApp user. Fetches the
   * bytes from GAIA (bot-authenticated), uploads them to WhatsApp via the Kapso
   * media API, then sends an image or document message referencing the media id.
   */
  protected override async deliverOutboundFile(
    destinationId: string,
    attachment: OutboundAttachment,
  ): Promise<void> {
    const artifact = await this.fetchOutboundArtifact(
      destinationId,
      attachment,
    );
    if (!artifact) return; // too large — fetchOutboundArtifact already replied
    const { data, contentType } = artifact;
    const mime =
      attachment.content_type ?? contentType ?? "application/octet-stream";
    const phoneNumberId = this.whatsAppConfig.kapsoPhoneNumberId;

    const uploaded = (await this.whatsAppClient.media.upload({
      phoneNumberId,
      type: mime,
      file: new Blob([new Uint8Array(data)], { type: mime }),
      fileName: attachment.filename,
    })) as { id?: string };
    if (!uploaded.id) throw new Error("Kapso media upload returned no id");

    const to = `+${destinationId}`;
    const caption = attachment.caption ?? undefined;
    // WhatsApp image messages cap around 5 MB; deliver larger images as a
    // document so they still arrive instead of being rejected.
    if (mime.startsWith("image/") && data.length <= WHATSAPP_IMAGE_MAX_BYTES) {
      await this.whatsAppClient.messages.sendImage({
        phoneNumberId,
        to,
        image: { id: uploaded.id, caption },
      });
    } else {
      await this.whatsAppClient.messages.sendDocument({
        phoneNumberId,
        to,
        document: { id: uploaded.id, filename: attachment.filename, caption },
      });
    }
  }
}
