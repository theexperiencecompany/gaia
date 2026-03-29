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

import type { Server } from "node:http";
import {
  BaseBotAdapter,
  type BotCommand,
  handleStreamingChat,
  type PlatformName,
  parseTextArgs,
  type RichMessage,
  type RichMessageTarget,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
} from "@gaia/shared";
import { serve } from "@hono/node-server";
import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import { Hono } from "hono";
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
  webhookPort: number;
}

function loadWhatsAppConfig(): WhatsAppConfig {
  const kapsoApiKey = process.env.KAPSO_API_KEY;
  const kapsoPhoneNumberId = process.env.KAPSO_PHONE_NUMBER_ID;
  const kapsoWebhookSecret = process.env.KAPSO_WEBHOOK_SECRET;
  const webhookPort = Number(process.env.WHATSAPP_WEBHOOK_PORT ?? "3001");

  if (!kapsoApiKey) throw new Error("KAPSO_API_KEY is required");
  if (!kapsoPhoneNumberId) throw new Error("KAPSO_PHONE_NUMBER_ID is required");
  if (!kapsoWebhookSecret) throw new Error("KAPSO_WEBHOOK_SECRET is required");

  return { kapsoApiKey, kapsoPhoneNumberId, kapsoWebhookSecret, webhookPort };
}

// ─── WhatsApp Adapter ─────────────────────────────────────────────────────────

export class WhatsAppAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "whatsapp";

  private waClient: WhatsAppClient | null = null;
  private waConfig: WhatsAppConfig | null = null;
  private httpServer: Server | null = null;

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
    console.log("WhatsApp client initialized via Kapso");
  }

  /** WhatsApp has no platform-level command registration step. */
  protected async registerCommands(_commands: BotCommand[]): Promise<void> {
    console.log("WhatsApp commands registered (text-based matching)");
  }

  /**
   * Starts a Hono HTTP server to receive Kapso webhook events.
   *
   * - GET  /health  → liveness probe
   * - POST /webhook → verifies Kapso HMAC signature, dispatches message
   */
  protected async registerEvents(): Promise<void> {
    const app = new Hono();

    app.get("/health", (c) => c.json({ status: "ok" }));

    app.post("/webhook", async (c) => {
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
        const text = extractTextBody(event);
        if (text) {
          // Fire-and-forget — do not await so webhook returns 200 quickly
          this.handleIncomingMessage(waId, text, event.message.id).catch(
            (err) => console.error("Error handling WhatsApp message:", err),
          );
        }
      }

      return c.json({ status: "ok" });
    });

    await new Promise<void>((resolve) => {
      this.httpServer = serve(
        { fetch: app.fetch, port: this.whatsAppConfig.webhookPort },
        () => {
          console.log(
            `WhatsApp webhook server listening on port ${this.whatsAppConfig.webhookPort}`,
          );
          resolve();
        },
      ) as Server;
      this.httpServer.on("error", (err) => {
        console.error("WhatsApp webhook server error:", err);
      });
    });
  }

  /** Nothing additional to start — HTTP server is already up after registerEvents. */
  protected async start(): Promise<void> {
    console.log("WhatsApp bot started and listening for messages");
  }

  /** Closes the HTTP server gracefully. */
  protected async stop(): Promise<void> {
    if (this.httpServer) {
      await new Promise<void>((resolve, reject) => {
        this.httpServer!.close((err) => {
          if (err) reject(err);
          else resolve();
        });
      });
      this.httpServer = null;
    }
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
        .catch((err) =>
          console.error("WhatsApp: failed to show typing indicator:", err),
        );

    showTyping();
    const typingInterval = setInterval(showTyping, 20_000);
    const clearTyping = () => clearInterval(typingInterval);

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
            // ever re-enabled or editMessage is called on retry.
            return;
          }
          if (lastEditFn) {
            await lastEditFn(updatedText);
          } else {
            const sent = await this.sendWhatsAppText(waId, updatedText);
            lastEditFn = sent.edit;
          }
          finalMessageSent = true;
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
      );
    } catch (err) {
      console.error("WhatsApp streaming error:", err);
      try {
        await this.sendWhatsAppText(
          waId,
          "An error occurred. Please try again.",
        );
      } catch (sendErr) {
        console.error("WhatsApp send error:", sendErr);
      }
    }
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
  private createWaTarget(waId: string, messageId: string): RichMessageTarget {
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
        const text = richMessageToMarkdown(richMsg, "whatsapp");
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
