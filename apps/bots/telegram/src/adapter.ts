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
  convertToTelegramMarkdown,
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
        const args: Record<string, string | number | boolean | undefined> = {};
        // ctx.match gives text after the /command prefix (grammY strips it)
        const rawText = ctx.match || "";

        if (commandName === "todo" || commandName === "workflow") {
          const parsed = parseTextArgs(rawText);
          args.subcommand = parsed.subcommand;
        }

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
      this.adapterLogger.error("set_my_commands_failed", undefined, e);
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
  }

  /** Starts long polling. */
  protected async start(): Promise<void> {
    this.bot.start({
      onStart: () => this.adapterLogger.info("long_polling_started"),
    });
  }

  /** Stops the bot. */
  protected async stop(): Promise<void> {
    await this.bot.stop();
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

    // Typing indicator with 5s refresh
    let typingInterval: ReturnType<typeof setInterval> | null = setInterval(
      async () => {
        try {
          await ctx.api.sendChatAction(chatId, "typing");
        } catch {}
      },
      5000,
    );
    try {
      await ctx.api.sendChatAction(chatId, "typing");
    } catch {}

    const clearTyping = () => {
      if (typingInterval) {
        clearInterval(typingInterval);
        typingInterval = null;
      }
    };

    try {
      await handleStreamingChat(
        this.gaia,
        {
          message,
          platform: "telegram",
          platformUserId: userId,
          channelId: chatId.toString(),
        },
        async (text: string) => {
          const converted = convertToTelegramMarkdown(text);
          try {
            await ctx.api.editMessageText(chatId, currentMessageId, converted, {
              parse_mode: "Markdown",
            });
          } catch (e) {
            if (
              e instanceof Error &&
              e.message.includes("message is not modified")
            )
              return;
            // Markdown parse failure — retry without parse_mode so the
            // user sees the latest content instead of a stale message
            if (
              e instanceof Error &&
              e.message.includes("can't parse entities")
            ) {
              try {
                await ctx.api.editMessageText(chatId, currentMessageId, text);
              } catch {}
              return;
            }
            this.adapterLogger.error(
              "edit_message_text_failed",
              { chat_id: chatId, message_id: currentMessageId },
              e,
            );
          }
        },
        async (text: string) => {
          const converted = convertToTelegramMarkdown(text);
          let newMessage: Message.TextMessage;
          try {
            newMessage = await ctx.reply(converted, {
              parse_mode: "Markdown",
            });
          } catch {
            // Markdown parse failure — send without parse_mode
            newMessage = await ctx.reply(text);
          }
          currentMessageId = newMessage.message_id;
          return async (updatedText: string) => {
            const convertedUpdate = convertToTelegramMarkdown(updatedText);
            try {
              await ctx.api.editMessageText(
                chatId,
                newMessage.message_id,
                convertedUpdate,
                { parse_mode: "Markdown" },
              );
            } catch (e) {
              if (
                e instanceof Error &&
                e.message.includes("message is not modified")
              )
                return;
              if (
                e instanceof Error &&
                e.message.includes("can't parse entities")
              ) {
                try {
                  await ctx.api.editMessageText(
                    chatId,
                    newMessage.message_id,
                    updatedText,
                  );
                } catch {}
                return;
              }
              this.adapterLogger.error(
                "edit_message_text_failed",
                { chat_id: chatId, message_id: newMessage.message_id },
                e,
              );
            }
          };
        },
        async (authUrl: string) => {
          clearTyping();
          // Send auth URL via DM for privacy in group chats
          const isGroup = ctx.chat?.type !== "private";
          const authMsg = `Please authenticate first.\n\nOpen this link to sign in:\n${authUrl}`;
          try {
            if (isGroup) {
              await ctx.api.sendMessage(Number(userId), authMsg);
              await ctx.api.editMessageText(
                chatId,
                currentMessageId,
                "I sent you a DM with the authentication link.",
              );
            } else {
              await ctx.api.editMessageText(chatId, currentMessageId, authMsg);
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
          try {
            await ctx.api.editMessageText(chatId, currentMessageId, errMsg);
          } catch (e) {
            this.adapterLogger.error(
              "edit_message_text_failed",
              { chat_id: chatId, message_id: currentMessageId },
              e,
            );
          }
        },
        STREAMING_DEFAULTS.telegram,
        this.analytics,
      );
    } finally {
      clearTyping();
    }
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

    return {
      platform: "telegram",
      userId,
      channelId: chatId?.toString(),
      profile,

      send: async (text: string): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        const converted = convertToTelegramMarkdown(text);
        let msg: { message_id: number };
        try {
          msg = await api.sendMessage(chatId, converted, {
            parse_mode: "Markdown",
          });
        } catch {
          msg = await api.sendMessage(chatId, text);
        }
        return {
          id: msg.message_id.toString(),
          edit: async (t: string) => {
            const c = convertToTelegramMarkdown(t);
            try {
              await api.editMessageText(chatId, msg.message_id, c, {
                parse_mode: "Markdown",
              });
            } catch {
              try {
                await api.editMessageText(chatId, msg.message_id, t);
              } catch (e) {
                this.adapterLogger.error(
                  "edit_message_text_failed",
                  { chat_id: chatId, message_id: msg.message_id },
                  e,
                );
              }
            }
          },
        };
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        // In groups, DM the user for privacy; in private chats, send normally
        const targetChat = isGroup ? Number(userId) : chatId;
        const converted = convertToTelegramMarkdown(text);
        let msg: { message_id: number };
        try {
          msg = await api.sendMessage(targetChat, converted, {
            parse_mode: "Markdown",
          });
        } catch {
          msg = await api.sendMessage(targetChat, text);
        }
        if (isGroup) {
          await api.sendMessage(chatId, "I sent you a DM with the details.");
        }
        return {
          id: msg.message_id.toString(),
          edit: async (t: string) => {
            const c = convertToTelegramMarkdown(t);
            try {
              await api.editMessageText(targetChat, msg.message_id, c, {
                parse_mode: "Markdown",
              });
            } catch {
              try {
                await api.editMessageText(targetChat, msg.message_id, t);
              } catch (e) {
                this.adapterLogger.error(
                  "edit_message_text_failed",
                  { chat_id: targetChat, message_id: msg.message_id },
                  e,
                );
              }
            }
          },
        };
      },

      sendRich: async (richMsg: RichMessage): Promise<SentMessage> => {
        if (!chatId) throw new Error("No chat ID");
        const markdown = richMessageToMarkdown(richMsg, "telegram");
        // In groups, DM rich content for privacy; in private chats, send normally
        const targetChat = isGroup ? Number(userId) : chatId;
        const msg = await api.sendMessage(targetChat, markdown, {
          parse_mode: "Markdown",
        });
        if (isGroup) {
          await api.sendMessage(chatId, "I sent you a DM with the details.");
        }
        return {
          id: msg.message_id.toString(),
          edit: async (t: string) => {
            try {
              await api.editMessageText(targetChat, msg.message_id, t);
            } catch (e) {
              this.adapterLogger.error(
                "edit_message_text_failed",
                { chat_id: targetChat, message_id: msg.message_id },
                e,
              );
            }
          },
        };
      },

      startTyping: async () => {
        if (!chatId) return () => {};
        try {
          await api.sendChatAction(chatId, "typing");
        } catch {}
        const interval = setInterval(async () => {
          try {
            await api.sendChatAction(chatId, "typing");
          } catch {}
        }, 5000);
        return () => clearInterval(interval);
      },
    };
  }
}
