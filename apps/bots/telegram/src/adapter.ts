/**
 * Telegram bot adapter for GAIA.
 *
 * Extends {@link BaseBotAdapter} to wire unified commands and events
 * to the grammY framework. Handles Telegram-specific concerns:
 *
 * - **Bot commands** via `bot.command()` with grammY's context
 * - **Rich messages** rendered as markdown (Telegram has no native embed)
 * - **Typing indicator** via `replyWithChatAction("typing")` with 5s refresh
 * - **Private DMs** via `message:text` handler (private chat filter)
 * - **Group @mentions** via `message:text` handler (mentions `@botUsername`)
 * - **Long polling** for message delivery
 *
 * New features gained from the unified command system:
 * - `/help` with rich content (replaces basic `/start` text)
 * - `/settings` command (previously missing)
 * - `/workflow create` subcommand (previously missing)
 * - Group @mention handling (previously missing)
 * - Typing indicator during streaming (previously missing)
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
  htmlToPlainText,
  type IncomingMedia,
  type MediaKind,
  type PlatformName,
  type RichMessage,
  type RichMessageTarget,
  renderForPlatform,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
  sanitizeErrorForLog,
} from "@gaia/shared";
import type { Message } from "@grammyjs/types";
import { Bot, type Context } from "grammy";

/**
 * Telegram-specific implementation of the GAIA bot adapter.
 *
 * Manages the grammY `Bot` lifecycle and translates between
 * Telegram's command/message APIs and the unified command system.
 */
// ---------------------------------------------------------------------------
// Exported mention helpers (extracted for testability)
// ---------------------------------------------------------------------------

/** Returns true if the message text contains a @botUsername mention. */
export function hasTelegramMention(text: string, botUsername: string): boolean {
  return text.includes(`@${botUsername}`);
}

/** Removes all @botUsername mentions from text and trims whitespace. */
export function stripTelegramMention(
  text: string,
  botUsername: string,
): string {
  return text.replaceAll(`@${botUsername}`, "").trim();
}

/** A Telegram media payload normalised for the shared media pipeline. */
export interface TelegramMedia {
  kind: MediaKind;
  isVoiceNote: boolean;
  mimeType: string;
  filename?: string;
  /** Telegram file_id, resolved to a download URL via getFile. */
  fileId: string;
}

/**
 * Maps a grammY {@link Message} onto a {@link TelegramMedia} descriptor, or
 * null when the message carries no media we recognise. Exported as a pure
 * function so the mapping is unit-testable without a live grammY context.
 *
 * Photos arrive as an ascending-size array, so the last entry is the highest
 * resolution. Voice notes (push-to-talk) are flagged separately from audio
 * files. Videos, video notes, animations (GIFs) and stickers map to the
 * unsupported kinds the shared pipeline rejects without a download.
 */
export function extractTelegramMedia(msg: Message): TelegramMedia | null {
  if (msg.photo && msg.photo.length > 0) {
    const largest = msg.photo[msg.photo.length - 1];
    return {
      kind: "image",
      isVoiceNote: false,
      mimeType: "image/jpeg",
      fileId: largest.file_id,
    };
  }
  if (msg.voice) {
    return {
      kind: "audio",
      isVoiceNote: true,
      mimeType: msg.voice.mime_type ?? "audio/ogg",
      fileId: msg.voice.file_id,
    };
  }
  if (msg.audio) {
    return {
      kind: "audio",
      isVoiceNote: false,
      mimeType: msg.audio.mime_type ?? "audio/mpeg",
      filename: msg.audio.file_name,
      fileId: msg.audio.file_id,
    };
  }
  if (msg.document) {
    return {
      kind: "document",
      isVoiceNote: false,
      mimeType: msg.document.mime_type ?? "application/octet-stream",
      filename: msg.document.file_name,
      fileId: msg.document.file_id,
    };
  }
  const video = msg.video ?? msg.video_note ?? msg.animation;
  if (video) {
    return {
      kind: "video",
      isVoiceNote: false,
      mimeType: "video/mp4",
      fileId: video.file_id,
    };
  }
  if (msg.sticker) {
    return {
      kind: "sticker",
      isVoiceNote: false,
      mimeType: "image/webp",
      fileId: msg.sticker.file_id,
    };
  }
  return null;
}

export class TelegramAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "telegram";
  protected readonly defaultServerPort = 3202;
  private bot!: Bot;
  private token!: string;
  private botUsername: string | undefined;
  private readonly adapterLogger = createBotLogger("telegram", "adapter");

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /** Creates the grammY Bot, caches bot username, and registers the error handler. */
  protected async initialize(): Promise<void> {
    const token = process.env.TELEGRAM_BOT_TOKEN;
    if (!token) {
      throw new Error("TELEGRAM_BOT_TOKEN is required");
    }
    this.token = token;

    this.bot = new Bot(this.token);
    this.bot.catch((err) => {
      this.adapterLogger.error("bot_runtime_error", undefined, err);
    });
    // Cache the bot username upfront to avoid calling getMe() on every message
    const botInfo = await this.bot.api.getMe();
    this.botUsername = botInfo.username;
  }

  /**
   * Registers unified commands as Telegram bot command handlers.
   *
   * Maps `/start` to the help command, special-cases `/gaia` for streaming,
   * and dispatches all others through the unified command system.
   */
  protected async registerCommands(commands: BotCommand[]): Promise<void> {
    // /start → help command
    this.bot.command("start", async (ctx) => {
      const userId = ctx.from?.id.toString();
      if (!userId) return;

      const target = this.createCtxTarget(ctx, userId);
      await this.dispatchCommand("help", target);
    });

    for (const cmd of commands) {
      if (cmd.name === "gaia") {
        this.registerGaiaCommand();
        continue;
      }

      // Skip "help" as a direct command name since we map /start → help
      // But also register /help as its own command
      const commandName = cmd.name;
      this.bot.command(commandName, async (ctx) => {
        const userId = ctx.from?.id.toString();
        if (!userId) return;

        const target = this.createCtxTarget(ctx, userId);
        // ctx.match gives text after the /command prefix (grammY strips it)
        const rawText = ctx.match || "";
        const args = extractSubcommandArgs(commandName, rawText);

        await this.dispatchCommand(
          commandName,
          target,
          args,
          rawText || undefined,
        );
      });
    }

    // Register command list with Telegram so the "/" suggestion menu is populated.
    // /start is added manually since it's a Telegram convention not in allCommands.
    const telegramCommands = [
      { command: "start", description: "Get started with GAIA" },
      ...commands.map((cmd) => ({
        command: cmd.name,
        description: cmd.description,
      })),
    ];
    try {
      await this.bot.api.setMyCommands(telegramCommands);
    } catch (e) {
      this.adapterLogger.error(
        "set_my_commands_failed",
        sanitizeErrorForLog(e),
      );
    }
  }

  /**
   * Registers non-command event listeners.
   *
   * - Private chat messages → authenticated streaming chat (DMs)
   * - Group messages mentioning `@botUsername` → unauthenticated mention chat
   */
  protected async registerEvents(): Promise<void> {
    this.bot.on("message:text", async (ctx) => {
      if (ctx.message.text.startsWith("/")) return;

      const userId = ctx.from?.id.toString();
      if (!userId) return;

      const isPrivate = ctx.chat.type === "private";
      this.adapterLogger.info("message_received", {
        user_hash: hashLogIdentifier(userId),
        chat_hash: hashLogIdentifier(ctx.chat.id),
        chat_type: ctx.chat.type,
        is_private: isPrivate,
      });

      if (isPrivate) {
        await this.handleTelegramStreaming(ctx, userId, ctx.message.text);
        return;
      }

      // Group @mention handling — uses cached bot username
      if (!this.botUsername) return;
      if (!hasTelegramMention(ctx.message.text, this.botUsername)) return;

      const content = stripTelegramMention(ctx.message.text, this.botUsername);

      if (!content) {
        await ctx.reply("How can I help you?");
        return;
      }

      await this.handleTelegramStreaming(ctx, userId, content);
    });

    // Inbound media (photos, documents, voice notes, audio, …). Routed through
    // the same shared pipeline WhatsApp uses, so behaviour stays identical.
    this.bot.on(
      [
        "message:photo",
        "message:document",
        "message:voice",
        "message:audio",
        "message:video",
        "message:video_note",
        "message:animation",
        "message:sticker",
      ],
      (ctx) => this.handleTelegramMediaMessage(ctx),
    );
  }

  /** Starts long polling, retrying after 35 s on 409 Conflict. */
  protected async start(): Promise<void> {
    // Remove any webhook that may have been set during development.
    // A webhook prevents long polling and immediately returns 409.
    try {
      await this.bot.api.deleteWebhook({ drop_pending_updates: true });
    } catch (e) {
      this.adapterLogger.warn("delete_webhook_failed", sanitizeErrorForLog(e));
    }

    const runBot = async (retryDelayMs = 0): Promise<void> => {
      if (retryDelayMs > 0) {
        this.adapterLogger.info("long_poll_retry_waiting", {
          delay_ms: retryDelayMs,
        });
        await new Promise<void>((r) => setTimeout(r, retryDelayMs));
      }
      await this.bot.start({
        onStart: () => this.adapterLogger.info("long_polling_started"),
      });
    };

    const startWithRetry = (retryDelayMs = 0): void => {
      runBot(retryDelayMs).catch((err: unknown) => {
        const code = (err as { error_code?: number })?.error_code;
        if (code === 409) {
          // Another getUpdates session is still active (e.g. previous container
          // was SIGKILL'd before graceful shutdown). Wait 35 s for it to expire.
          this.adapterLogger.warn("long_poll_conflict_retrying", {
            wait_ms: 35_000,
          });
          startWithRetry(35_000);
        } else {
          this.adapterLogger.error("long_poll_fatal", undefined, err);
          void this.shutdown()
            .catch((shutdownErr) =>
              this.adapterLogger.error(
                "shutdown_failed",
                undefined,
                shutdownErr,
              ),
            )
            .finally(() => process.exit(1));
        }
      });
    };

    startWithRetry();
  }

  /** Stops the bot. */
  protected async stop(): Promise<void> {
    await this.bot.stop();
  }

  // ---------------------------------------------------------------------------
  // Send helpers — Telegram HTML with a plain-text fallback
  // ---------------------------------------------------------------------------

  /**
   * Sends a message as Telegram HTML, falling back to stripped plain text if
   * Telegram ever rejects the markup (with fully escaped output this should not
   * happen). Returns the sent message so callers can capture its id.
   */
  private async sendHtml(
    send: (
      text: string,
      opts?: { parse_mode: "HTML" },
    ) => Promise<Message.TextMessage>,
    html: string,
  ): Promise<Message.TextMessage> {
    try {
      return await send(html, { parse_mode: "HTML" });
    } catch {
      return await send(htmlToPlainText(html));
    }
  }

  protected async deliverOutbound(
    destinationId: string,
    text: string,
  ): Promise<void> {
    // grammY accepts a string chat_id; passing the id through avoids the NaN
    // that Number() would produce for any non-numeric destination.
    await this.sendHtml(
      (t, opts) => this.bot.api.sendMessage(destinationId, t, opts),
      text,
    );
  }

  /**
   * Edits a message as Telegram HTML. A "message is not modified" error (thrown
   * when the new text equals the current text) is ignored; any other failure
   * retries as stripped plain text, and a final failure is reported via
   * `onError`. Centralises the fallback every Telegram edit path needs.
   */
  private async editHtml(
    edit: (text: string, opts?: { parse_mode: "HTML" }) => Promise<unknown>,
    html: string,
    onError: (err: unknown) => void,
  ): Promise<void> {
    try {
      await edit(html, { parse_mode: "HTML" });
    } catch (e) {
      if (e instanceof Error && e.message.includes("message is not modified")) {
        return;
      }
      try {
        await edit(htmlToPlainText(html));
      } catch (err) {
        onError(err);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Gaia streaming
  // ---------------------------------------------------------------------------

  /**
   * Registers the `/gaia` command with Telegram-specific streaming.
   */
  private registerGaiaCommand(): void {
    this.bot.command("gaia", async (ctx) => {
      const message = ctx.match;
      const userId = ctx.from?.id.toString();

      if (!userId) return;

      if (!message) {
        await ctx.reply("Usage: /gaia <your message>");
        return;
      }

      this.adapterLogger.info("slash_command_received", {
        command: "gaia",
        user_hash: hashLogIdentifier(userId),
        chat_hash: hashLogIdentifier(ctx.chat?.id),
      });

      await this.handleTelegramStreaming(ctx, userId, message);
    });
  }

  /**
   * Shared streaming handler for `/gaia`, DMs, and @mentions.
   *
   * Sends an initial "Thinking..." message with a typing indicator,
   * then updates it in place as chunks arrive.
   */
  private async handleTelegramStreaming(
    ctx: Context,
    userId: string,
    message: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    const chatId = ctx.chat?.id;
    if (!chatId) return;

    this.adapterLogger.info("streaming_started", {
      user_hash: hashLogIdentifier(userId),
      chat_hash: hashLogIdentifier(chatId),
      message_length: message.length,
    });

    const loading = await ctx.reply("Thinking...");
    let currentMessageId = loading.message_id;

    // Typing indicator with 5s refresh (Telegram expires it after ~5s).
    const clearTyping = this.startTypingIndicator(
      () => ctx.api.sendChatAction(chatId, "typing"),
      5000,
    );

    try {
      await handleStreamingChat(
        this.gaia,
        {
          message,
          platform: "telegram",
          platformUserId: userId,
          channelId: chatId.toString(),
          ...(attachments.length > 0
            ? {
                fileIds: attachments.map((a) => a.fileId),
                fileData: attachments,
              }
            : {}),
        },
        async (text: string) => {
          await this.editHtml(
            (t, opts) =>
              ctx.api.editMessageText(chatId, currentMessageId, t, opts),
            text,
            (e) =>
              this.adapterLogger.error(
                "edit_message_text_failed",
                { chat_id: chatId, message_id: currentMessageId },
                e,
              ),
          );
        },
        async (text: string) => {
          const newMessage = await this.sendHtml(
            (t, opts) => ctx.reply(t, opts),
            text,
          );
          currentMessageId = newMessage.message_id;
          return async (updatedText: string) => {
            await this.editHtml(
              (t, opts) =>
                ctx.api.editMessageText(chatId, newMessage.message_id, t, opts),
              updatedText,
              (e) =>
                this.adapterLogger.error(
                  "edit_message_text_failed",
                  { chat_id: chatId, message_id: newMessage.message_id },
                  e,
                ),
            );
          };
        },
        async (authUrl: string) => {
          clearTyping();
          // Same HTML pipeline as every other send, so the auth prompt renders
          // identically to the /auth command (bold + a clickable link), not
          // literal `**`/`[ ]( )`. In groups, DM it for privacy.
          const isGroup = ctx.chat?.type !== "private";
          const authHtml = renderForPlatform(
            buildAuthLinkMessage(authUrl),
            "telegram",
          );
          try {
            if (isGroup) {
              await this.sendHtml(
                (t, opts) => ctx.api.sendMessage(Number(userId), t, opts),
                authHtml,
              );
              await ctx.api.editMessageText(
                chatId,
                currentMessageId,
                "I sent you a DM with the authentication link.",
              );
            } else {
              await this.editHtml(
                (t, opts) =>
                  ctx.api.editMessageText(chatId, currentMessageId, t, opts),
                authHtml,
                (e) =>
                  this.adapterLogger.error(
                    "auth_message_failed",
                    { chat_id: chatId, user_id: userId },
                    e,
                  ),
              );
            }
          } catch (e) {
            this.adapterLogger.error(
              "auth_message_failed",
              { chat_id: chatId, user_id: userId },
              e,
            );
            // DM failed (privacy settings) — update group message with fallback
            try {
              const fallback = this.botUsername
                ? `I couldn't send you a DM — your privacy settings may be blocking bot messages.\n\nPlease message me directly at @${this.botUsername} and use /auth to link your account.`
                : `I couldn't send you a DM — your privacy settings may be blocking bot messages.\n\nPlease message me directly and use /auth to link your account.`;
              await ctx.api.editMessageText(chatId, currentMessageId, fallback);
            } catch (fallbackErr) {
              this.adapterLogger.error(
                "auth_fallback_message_failed",
                { chat_id: chatId, user_id: userId },
                fallbackErr,
              );
            }
          }
        },
        async (errMsg: string) => {
          clearTyping();
          await this.editHtml(
            (t, opts) =>
              ctx.api.editMessageText(chatId, currentMessageId, t, opts),
            renderForPlatform(errMsg, "telegram"),
            (e) =>
              this.adapterLogger.error(
                "edit_message_text_failed",
                { chat_id: chatId, message_id: currentMessageId },
                e,
              ),
          );
        },
        STREAMING_DEFAULTS.telegram,
        this.analytics,
      );
    } finally {
      clearTyping();
    }
  }

  // ---------------------------------------------------------------------------
  // Media handling
  // ---------------------------------------------------------------------------

  /**
   * Routes an inbound media message through the shared media pipeline.
   *
   * Platform-specific concerns only: mention gating (private chats are handled
   * directly; groups require a caption @mention, mirroring the text path) and
   * mapping the grammY message onto {@link IncomingMedia}. The transcribe vs
   * upload vs reject decision lives in {@link processBotMedia} so Telegram and
   * WhatsApp stay byte-for-byte consistent.
   */
  private async handleTelegramMediaMessage(ctx: Context): Promise<void> {
    const userId = ctx.from?.id.toString();
    const msg = ctx.message;
    if (!userId || !msg) return;

    const extracted = extractTelegramMedia(msg);
    if (!extracted) return;

    const isPrivate = ctx.chat?.type === "private";
    let caption = msg.caption?.trim() || undefined;

    if (!isPrivate) {
      // Group: only engage when the caption @mentions the bot, like text.
      if (!this.botUsername || !caption) return;
      if (!hasTelegramMention(caption, this.botUsername)) return;
      caption = stripTelegramMention(caption, this.botUsername) || undefined;
    }

    this.adapterLogger.info("media_message_received", {
      user_hash: hashLogIdentifier(userId),
      chat_hash: hashLogIdentifier(ctx.chat?.id),
      media_kind: extracted.kind,
      is_voice_note: extracted.isVoiceNote,
    });

    const media: IncomingMedia = {
      kind: extracted.kind,
      isVoiceNote: extracted.isVoiceNote,
      mimeType: extracted.mimeType,
      filename: extracted.filename,
      caption,
    };
    await this.handleTelegramMedia(ctx, userId, media, extracted.fileId);
  }

  /** Downloads, routes, and replies for a single inbound media message. */
  private async handleTelegramMedia(
    ctx: Context,
    userId: string,
    media: IncomingMedia,
    fileId: string,
  ): Promise<void> {
    const chatId = ctx.chat?.id;
    if (!chatId) return;

    try {
      await ctx.api.sendChatAction(chatId, "typing");
    } catch {}

    try {
      const outcome = await this.resolveIncomingMedia(
        media,
        () => this.downloadTelegramFile(fileId),
        userId,
        chatId.toString(),
      );
      if (outcome.action === "reply") {
        await ctx.reply(outcome.text);
      } else {
        await this.handleTelegramStreaming(
          ctx,
          userId,
          outcome.text,
          outcome.attachments,
        );
      }
    } catch (err) {
      this.adapterLogger.error(
        "media_message_failed",
        { chat_id: chatId, media_kind: media.kind },
        err,
      );
      try {
        await ctx.reply(
          friendlyMediaError(media.kind, err, this.gaia.getPricingUrl()),
        );
      } catch {}
    }
  }

  /**
   * Downloads a Telegram file by id. `getFile` returns a path under the Bot API
   * file endpoint; we fetch the raw bytes from there. Telegram caps Bot API
   * downloads at 20 MB — larger files throw and surface as a friendly error.
   */
  private async downloadTelegramFile(fileId: string): Promise<Uint8Array> {
    const file = await this.bot.api.getFile(fileId);
    if (!file.file_path) {
      throw new Error("Telegram getFile returned no file_path");
    }
    const url = `https://api.telegram.org/file/bot${this.token}/${file.file_path}`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(
        `Telegram file download failed with status ${res.status}`,
      );
    }
    return new Uint8Array(await res.arrayBuffer());
  }

  // ---------------------------------------------------------------------------
  // Message target factory
  // ---------------------------------------------------------------------------

  /**
   * Creates a {@link RichMessageTarget} from a Telegram context.
   *
   * Captures the chat ID and API reference as plain values so the target
   * remains valid after the grammY context's lifecycle ends.
   *
   * @param ctx - The grammY context.
   * @param userId - The Telegram user ID as a string.
   */
  private createCtxTarget(ctx: Context, userId: string): RichMessageTarget {
    const chatId = ctx.chat?.id;
    const api = ctx.api;
    const isGroup = ctx.chat?.type !== "private";

    const displayName =
      [ctx.from?.first_name, ctx.from?.last_name].filter(Boolean).join(" ") ||
      undefined;
    const profile =
      ctx.from?.username || displayName
        ? { username: ctx.from?.username, displayName }
        : undefined;

    // Builds the SentMessage handle returned by send/sendEphemeral/sendRich:
    // the message id plus an HTML-aware edit closure bound to the chat it
    // landed in. Shared so the three senders don't each repeat it.
    const buildSent = (targetChat: number, messageId: number): SentMessage => ({
      id: messageId.toString(),
      edit: (t: string) =>
        this.editHtml(
          (edited, opts) =>
            api.editMessageText(targetChat, messageId, edited, opts),
          renderForPlatform(t, "telegram"),
          (e) =>
            this.adapterLogger.error(
              "edit_message_text_failed",
              { chat_id: targetChat, message_id: messageId },
              e,
            ),
        ),
    });

    return {
      platform: "telegram",
      userId,
      channelId: chatId?.toString(),
      profile,

      send: async (text: string): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        const msg = await this.sendHtml(
          (t, opts) => api.sendMessage(chatId, t, opts),
          renderForPlatform(text, "telegram"),
        );
        return buildSent(chatId, msg.message_id);
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        // In groups, DM the user for privacy; in private chats, send normally
        const targetChat = isGroup ? Number(userId) : chatId;
        const msg = await this.sendHtml(
          (t, opts) => api.sendMessage(targetChat, t, opts),
          renderForPlatform(text, "telegram"),
        );
        if (isGroup) {
          await api.sendMessage(chatId, "I sent you a DM with the details.");
        }
        return buildSent(targetChat, msg.message_id);
      },

      sendRich: async (richMsg: RichMessage): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        // richMessageToMarkdown renders Telegram-flavoured CommonMark; convert
        // it to HTML through the same chokepoint as every other outbound send.
        const html = renderForPlatform(
          richMessageToMarkdown(richMsg, "telegram"),
          "telegram",
        );
        // In groups, DM rich content for privacy; in private chats, send normally
        const targetChat = isGroup ? Number(userId) : chatId;
        const msg = await this.sendHtml(
          (t, opts) => api.sendMessage(targetChat, t, opts),
          html,
        );
        if (isGroup) {
          await api.sendMessage(chatId, "I sent you a DM with the details.");
        }
        return buildSent(targetChat, msg.message_id);
      },

      startTyping: async () => {
        if (!chatId) return () => {};
        return this.startTypingIndicator(
          () => api.sendChatAction(chatId, "typing"),
          5000,
        );
      },
    };
  }
}
