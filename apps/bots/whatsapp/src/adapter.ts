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
 * - **No typing indicator** — no standard WhatsApp typing API
 *
 * @module
 */

import { serve } from "@hono/node-server";
import {
  BaseBotAdapter,
  type BotCommand,
  handleStreamingChat,
  parseTextArgs,
  type PlatformName,
  type RichMessage,
  richMessageToMarkdown,
  type RichMessageTarget,
  type SentMessage,
  STREAMING_DEFAULTS,
} from "@gaia/shared";
import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import { Hono } from "hono";
import type { Server } from "node:http";
import {
  type KapsoMessageEvent,
  extractTextBody,
  extractWaId,
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

  private waClient!: WhatsAppClient;
  private waConfig!: WhatsAppConfig;
  private httpServer: Server | null = null;

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
      const signature = c.req.header("x-kapso-signature") ?? null;

      if (
        !verifyKapsoSignature(rawBody, signature, this.waConfig.kapsoWebhookSecret)
      ) {
        return c.json({ error: "Invalid signature" }, 401);
      }

      let event: KapsoMessageEvent;
      try {
        event = JSON.parse(rawBody) as KapsoMessageEvent;
      } catch {
        return c.json({ error: "Invalid JSON" }, 400);
      }

      if (event.type !== "whatsapp.message.received") {
        return c.json({ status: "ignored" });
      }

      const waId = extractWaId(event);
      const text = extractTextBody(event);

      if (text) {
        // Fire-and-forget — do not await so webhook returns 200 quickly
        this.handleIncomingMessage(waId, text).catch((err) =>
          console.error("Error handling WhatsApp message:", err),
        );
      }

      return c.json({ status: "ok" });
    });

    await new Promise<void>((resolve) => {
      this.httpServer = serve(
        { fetch: app.fetch, port: this.waConfig.webhookPort },
        () => {
          console.log(
            `WhatsApp webhook server listening on port ${this.waConfig.webhookPort}`,
          );
          resolve();
        },
      ) as Server;
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
   * - Messages starting with "/" are parsed as commands
   * - `/gaia <text>` invokes streaming chat
   * - Other `/command` messages invoke the unified command dispatcher
   * - Plain text messages are treated as implicit `/gaia` chat
   */
  private async handleIncomingMessage(waId: string, text: string): Promise<void> {
    const target = this.createWaTarget(waId);

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

      await this.dispatchCommand(commandName, target, args, rest || undefined);
      return;
    }

    // Plain text — treat as chat
    await this.handleStreamingMessage(waId, text);
  }

  /**
   * Sends the user's message to the GAIA streaming endpoint.
   *
   * WhatsApp streaming is disabled (STREAMING_DEFAULTS.whatsapp.streaming = false),
   * so the full response is accumulated and sent as a single message.
   * A "Thinking..." message is sent first while the response is generated.
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

    const thinkingMsg = await this.sendWhatsAppText(waId, "Thinking...");

    let lastEditFn: ((t: string) => Promise<void>) | null = null;

    try {
      await handleStreamingChat(
        this.gaia,
        {
          message: text,
          platform: "whatsapp",
          platformUserId: waId,
          channelId: waId,
        },
        // editMessage: update the last sent message (send new for WhatsApp)
        async (updatedText: string) => {
          if (lastEditFn) {
            await lastEditFn(updatedText);
          } else {
            await thinkingMsg.edit(updatedText);
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
      );
    } catch (err) {
      console.error("WhatsApp streaming error:", err);
      try {
        await thinkingMsg.edit("An error occurred. Please try again.");
      } catch (editErr) {
        console.error("WhatsApp edit error:", editErr);
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
   * - `startTyping` is a no-op (no standard typing API)
   */
  private createWaTarget(waId: string): RichMessageTarget {
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
        // WhatsApp has no standard typing indicator API
        return () => {};
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
  private async sendWhatsAppText(waId: string, text: string): Promise<SentMessage> {
    const response = await this.waClient.messages.sendText({
      phoneNumberId: this.waConfig.kapsoPhoneNumberId,
      to: `+${waId}`,
      body: text,
    });

    const messageId = response.messages[0]?.id ?? "";

    return {
      id: messageId,
      edit: async (updatedText: string): Promise<void> => {
        // WhatsApp does not support message editing — send a new message instead
        await this.waClient.messages.sendText({
          phoneNumberId: this.waConfig.kapsoPhoneNumberId,
          to: `+${waId}`,
          body: updatedText,
        });
      },
    };
  }
}
