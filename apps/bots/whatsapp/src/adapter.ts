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
 * - **Typing indicator** refreshed every 20s via markRead to survive long responses
 *
 * @module
 */

import {
  BaseBotAdapter,
  type BotCommand,
  convertToWhatsAppMarkdown,
  createBotLogger,
  handleStreamingChat,
  hashLogIdentifier,
  type PlatformName,
  parseTextArgs,
  type RichMessage,
  type RichMessageTarget,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
  sanitizeErrorForLog,
} from "@gaia/shared";
import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import {
  extractTextBody,
  extractWaId,
  type KapsoMessageBatch,
  type KapsoMessageEvent,
  verifyKapsoSignature,
} from "./webhook";

// ─── WhatsApp-specific config ─────────────────────────────────────────────────

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

// ─── WhatsApp Adapter ─────────────────────────────────────────────────────────

export class WhatsAppAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "whatsapp";
  protected readonly defaultServerPort = 3203;

  private waClient: WhatsAppClient | null = null;
  private waConfig: WhatsAppConfig | null = null;

  /** Tracks users who have already received a welcome message this process. */
  private readonly welcomeSent = new Set<string>();
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
        const waId = extractWaId(event);
        const waIdHash = hashLogIdentifier(waId);
        const text = extractTextBody(event);
        this.adapterLogger.info("webhook_message_received", {
          wa_hash: waIdHash,
          message_type: event.message.type,
          has_text: Boolean(text),
        });
        if (text) {
          // Fire-and-forget — do not await so webhook returns 200 quickly
          this.handleIncomingMessage(waId, text, event.message.id).catch(
            (err) =>
              this.adapterLogger.error("incoming_message_processing_failed", {
                wa_hash: waIdHash,
                message_id: event.message.id,
                ...sanitizeErrorForLog(err),
              }),
          );
        } else if (event.message.type !== "text") {
          // Non-text message (image, audio, video, document, etc.)
          this.handleUnsupportedMedia(waId, event.message.type).catch((err) =>
            this.adapterLogger.error("unsupported_media_handling_failed", {
              wa_hash: waIdHash,
              message_type: event.message.type,
              ...sanitizeErrorForLog(err),
            }),
          );
        }
      }

      return c.json({ status: "ok" });
    });
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

    // Show typing indicator — mark message as read and display "typing..." bubble.
    // WhatsApp auto-dismisses after ~25s, so we refresh every 20s to keep it alive
    // for long-running responses. The interval is cleared when a reply is sent.
    const showTyping = () =>
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
            ...sanitizeErrorForLog(err),
          }),
        );

    showTyping();
    const typingInterval = setInterval(showTyping, 20_000);
    const clearTyping = () => clearInterval(typingInterval);

    // Send welcome message on first contact from this user (per-process)
    if (!this.welcomeSent.has(waId)) {
      this.welcomeSent.add(waId);
      await this.sendWelcome(waId);
      // Re-show typing — sending the welcome message dismisses the indicator
      showTyping();
    }

    const target = this.createWaTarget(waId, messageId);

    try {
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

        const args: Record<string, string | number | boolean | undefined> = {};
        if (commandName === "todo" || commandName === "workflow") {
          const parsed = parseTextArgs(rest);
          args.subcommand = parsed.subcommand;
        }

        await this.dispatchCommand(
          commandName,
          target,
          args,
          rest || undefined,
        );
        return;
      }

      // Plain text — treat as chat
      await this.handleStreamingMessage(waId, text);
    } finally {
      clearTyping();
    }
  }

  /**
   * Sends the user's message to the GAIA streaming endpoint.
   *
   * WhatsApp streaming is disabled (STREAMING_DEFAULTS.whatsapp.streaming = false),
   * so the full response is accumulated and sent as a single message.
   * The typing indicator is refreshed every 20s by handleIncomingMessage
   * and cleared when processing completes.
   */
  private async handleStreamingMessage(
    waId: string,
    text: string,
  ): Promise<void> {
    if (!text.trim()) {
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
          message: text,
          platform: "whatsapp",
          platformUserId: waId,
          channelId: waId,
        },
        // editMessage: no placeholder to edit — send as new message on first call
        async (updatedText: string) => {
          if (finalMessageSent) {
            // WhatsApp has no edit API — edit() sends a new message.
            // Guard against sending multiple new messages if streaming is
            // ever re-enabled or editMessage is called more than once.
            return;
          }
          finalMessageSent = true;
          if (lastEditFn) {
            await lastEditFn(updatedText);
          } else {
            const sent = await this.sendWhatsAppText(waId, updatedText);
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
            `To use GAIA on WhatsApp, link your account first:\n${authUrl}`,
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
   * Tracked per-process via {@link welcomeSent} Set (resets on restart).
   */
  private async sendWelcome(waId: string): Promise<void> {
    const text =
      `*Hey, I'm GAIA* 👋\n\n` +
      `Your personal AI — built to think ahead, remember everything, and get things done with you.\n\n` +
      `Here's what I can do right on WhatsApp:\n\n` +
      `*💬 Chat*\nJust type anything. Ask questions, brainstorm, think out loud.\n\n` +
      `*✅ Todos*\nUse /todo add to capture tasks.\n\n` +
      `*⚡ Workflows*\nRun automations with /workflow. Delegate entire projects.\n\n` +
      `*🔗 Link your account*\nUse /auth to connect your GAIA account for memory and personalization.\n\n` +
      `_Visit heygaia.io or read the docs at docs.heygaia.io_`;

    try {
      await this.sendWhatsAppText(waId, text);
    } catch {
      // If we can't send the welcome, continue silently (match Discord behavior)
    }
  }

  // ---------------------------------------------------------------------------
  // Unsupported media handler
  // ---------------------------------------------------------------------------

  /**
   * Replies to non-text messages (images, audio, video, documents) with a
   * helpful message explaining that only text is currently supported.
   */
  private async handleUnsupportedMedia(
    waId: string,
    messageType: string,
  ): Promise<void> {
    const typeLabelMap: Record<string, string> = {
      image: "images",
      audio: "audio messages",
      voice: "audio messages",
      video: "videos",
      document: "documents",
    };
    const typeLabel = typeLabelMap[messageType] ?? `${messageType} messages`;

    await this.sendWhatsAppText(
      waId,
      `I can't process ${typeLabel} yet — please send your message as text. Type /help for available commands.`,
    );
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
        return this.sendWhatsAppText(waId, text);
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        // WhatsApp has no ephemeral concept — send normally
        return this.sendWhatsAppText(waId, text);
      },

      sendRich: async (richMsg: RichMessage): Promise<SentMessage> => {
        const markdown = richMessageToMarkdown(richMsg, "whatsapp");
        const text = convertToWhatsAppMarkdown(markdown);
        return this.sendWhatsAppText(waId, text);
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
        });
      },
    };
  }
}
