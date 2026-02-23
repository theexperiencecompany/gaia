/**
 * Slack bot adapter for GAIA.
 *
 * Extends {@link BaseBotAdapter} to wire unified commands and events
 * to the Slack Bolt framework. Handles Slack-specific concerns:
 *
 * - **Slash commands** via `app.command()` with immediate `ack()`
 * - **Ephemeral responses** via Bolt's `respond({ response_type: "ephemeral" })`
 * - **Rich messages** rendered as markdown (Slack has no native embed API)
 * - **App mentions** via the `app_mention` event with streaming chat
 * - **DM messages** via the `message` event with `channel_type === "im"`
 * - **Socket Mode** for real-time event delivery
 *
 * New features gained from the unified command system:
 * - `/help` command (previously Discord-only)
 * - `/settings` command (previously Discord-only)
 * - `/workflow create` subcommand (previously Discord-only)
 * - DM handling (previously missing)
 *
 * @module
 */

import {
  BaseBotAdapter,
  type BotCommand,
  convertToSlackMrkdwn,
  handleStreamingChat,
  type PlatformName,
  parseTextArgs,
  type RichMessage,
  type RichMessageTarget,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
} from "@gaia/shared";
import { App } from "@slack/bolt";

/** Bolt's respond function for slash command responses. */
type SlackRespondFn = (
  message: string | Record<string, unknown>,
) => Promise<unknown>;

/** Slack message event shape (Bolt doesn't export typed message events). */
interface SlackMessageEvent {
  text?: string;
  user?: string;
  channel?: string;
  channel_type?: string;
  subtype?: string;
}

/** Minimal Slack Web API client shape used by the adapter. */
interface SlackWebClient {
  chat: {
    postMessage: (args: {
      channel: string;
      text: string;
    }) => Promise<{ ts?: string }>;
    update: (args: {
      channel: string;
      ts: string;
      text: string;
    }) => Promise<unknown>;
    postEphemeral: (args: {
      channel: string;
      user: string;
      text: string;
    }) => Promise<unknown>;
  };
}

/**
 * Slack-specific implementation of the GAIA bot adapter.
 *
 * Manages the Slack Bolt `App` lifecycle and translates between
 * Slack's command/event APIs and the unified command system.
 */
export class SlackAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "slack";
  private app!: App;
  private token!: string;
  private signingSecret!: string;
  private appToken!: string;

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /** Creates the Slack Bolt App in Socket Mode. */
  protected async initialize(): Promise<void> {
    const token = process.env.SLACK_BOT_TOKEN;
    const signingSecret = process.env.SLACK_SIGNING_SECRET;
    const appToken = process.env.SLACK_APP_TOKEN;

    if (!token || !signingSecret || !appToken) {
      throw new Error(
        "Missing SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, or SLACK_APP_TOKEN",
      );
    }

    this.token = token;
    this.signingSecret = signingSecret;
    this.appToken = appToken;

    this.app = new App({
      token: this.token,
      signingSecret: this.signingSecret,
      socketMode: true,
      appToken: this.appToken,
    });
  }

  /**
   * Registers unified commands as Slack slash command handlers.
   *
   * Each command's handler:
   * 1. Calls `ack()` immediately (Slack's 3-second requirement)
   * 2. Special-cases `/gaia` to use streaming via `handleStreamingChat`
   * 3. All others create a {@link RichMessageTarget} and dispatch to the unified command
   */
  protected async registerCommands(commands: BotCommand[]): Promise<void> {
    for (const cmd of commands) {
      if (cmd.name === "gaia") {
        this.registerGaiaCommand();
        continue;
      }

      const commandName = cmd.name;
      this.app.command(
        `/${commandName}`,
        async ({ command, ack, respond, client }) => {
          await ack();

          const userId = command.user_id;
          const channelId = command.channel_id;
          const target = this.createCommandTarget(
            userId,
            channelId,
            client,
            respond,
            command.user_name,
          );

          // Parse text args for subcommand-style commands
          const args: Record<string, string | number | boolean | undefined> =
            {};
          const rawText = command.text || undefined;

          if (
            rawText &&
            (commandName === "todo" || commandName === "workflow")
          ) {
            const parsed = parseTextArgs(rawText);
            args.subcommand = parsed.subcommand;
          }

          await this.dispatchCommand(commandName, target, args, rawText);
        },
      );
    }
  }

  /**
   * Registers non-command event listeners.
   *
   * - `app_mention` — handles @mentions in channels with streaming chat
   * - `message` with `channel_type === "im"` — handles DMs with streaming chat
   */
  protected async registerEvents(): Promise<void> {
    // Channel @mentions
    this.app.event("app_mention", async ({ event, client, context }) => {
      const botMention = context.botUserId
        ? new RegExp(`<@${context.botUserId}>`, "g")
        : null;
      const content = botMention
        ? event.text.replace(botMention, "").trim()
        : event.text.trim();
      const userId = event.user;
      const channelId = event.channel;

      if (!userId) return;

      if (!content) {
        await client.chat.postMessage({
          channel: channelId,
          text: "How can I help you?",
        });
        return;
      }

      await this.handleSlackStreaming(client, channelId, userId, content);
    });

    // DM messages
    this.app.message(async ({ message, client }) => {
      const msg = message as SlackMessageEvent;

      if (msg.subtype) return;
      if (msg.channel_type !== "im") return;
      if (!msg.text || !msg.user || !msg.channel) return;

      await this.handleSlackStreaming(client, msg.channel, msg.user, msg.text);
    });
  }

  /** Starts the Slack Bolt app. */
  protected async start(): Promise<void> {
    await this.app.start();
    console.log("Slack bot is running");
  }

  /** Stops the Slack Bolt app. */
  protected async stop(): Promise<void> {
    await this.app.stop();
  }

  // ---------------------------------------------------------------------------
  // Gaia streaming
  // ---------------------------------------------------------------------------

  /**
   * Registers the `/gaia` slash command with Slack-specific streaming.
   *
   * Posts a public "Thinking..." message and updates it in place as
   * the streamed response arrives.
   */
  private registerGaiaCommand(): void {
    this.app.command("/gaia", async ({ command, ack, client }) => {
      await ack();

      const userId = command.user_id;
      const channelId = command.channel_id;
      const message = command.text;

      if (!message) {
        await client.chat.postEphemeral({
          channel: channelId,
          user: userId,
          text: "Please provide a message. Usage: /gaia <your message>",
        });
        return;
      }

      await this.handleSlackStreaming(client, channelId, userId, message);
    });
  }

  /**
   * Shared streaming handler for `/gaia`, @mentions, and DMs.
   *
   * Posts an initial "Thinking..." message, then updates it via
   * `chat.update` as chunks arrive from the streaming API.
   */
  private async handleSlackStreaming(
    client: SlackWebClient,
    channelId: string,
    userId: string,
    message: string,
  ): Promise<void> {
    const result = await client.chat.postMessage({
      channel: channelId,
      text: "Thinking...",
    });

    const ts = (result as { ts?: string }).ts;
    if (!ts) {
      console.warn("Slack postMessage returned no ts — sending fallback error");
      try {
        await client.chat.postEphemeral({
          channel: channelId,
          user: userId,
          text: "Something went wrong processing your message. Please try again.",
        });
      } catch (fallbackErr) {
        console.error("Slack fallback error message also failed:", fallbackErr);
      }
      return;
    }

    let currentTs = ts;

    await handleStreamingChat(
      this.gaia,
      { message, platform: "slack", platformUserId: userId, channelId },
      async (text: string) => {
        await client.chat.update({
          channel: channelId,
          ts: currentTs,
          text: convertToSlackMrkdwn(text),
        });
      },
      async (text: string) => {
        const newMessage = await client.chat.postMessage({
          channel: channelId,
          text: convertToSlackMrkdwn(text),
        });
        if ((newMessage as { ts?: string }).ts) {
          currentTs = (newMessage as { ts: string }).ts;
        }
        return async (updatedText: string) => {
          await client.chat.update({
            channel: channelId,
            ts: currentTs,
            text: convertToSlackMrkdwn(updatedText),
          });
        };
      },
      async (authUrl: string) => {
        // Send auth URL as ephemeral to avoid exposing tokens publicly
        await client.chat.update({
          channel: channelId,
          ts: currentTs,
          text: "Authentication required. Check the message below.",
        });
        await client.chat.postEphemeral({
          channel: channelId,
          user: userId,
          text: `Please authenticate first: ${authUrl}`,
        });
      },
      async (errMsg: string) => {
        await client.chat.update({
          channel: channelId,
          ts: currentTs,
          text: errMsg,
        });
      },
      STREAMING_DEFAULTS.slack,
    );
  }

  // ---------------------------------------------------------------------------
  // Message target factory
  // ---------------------------------------------------------------------------

  /**
   * Creates a {@link RichMessageTarget} for Slack slash command responses.
   *
   * Uses Bolt's `respond` function for ephemeral replies and the
   * Web API `client` for public messages. Rich messages are rendered
   * as markdown since Slack has no native embed format.
   *
   * @param userId - The Slack user ID.
   * @param channelId - The Slack channel ID.
   * @param client - The Slack Web API client.
   * @param respond - The Bolt respond function (for ephemeral replies).
   */
  private createCommandTarget(
    userId: string,
    channelId: string,
    client: SlackWebClient,
    respond: SlackRespondFn,
    userName?: string,
  ): RichMessageTarget {
    return {
      platform: "slack",
      userId,
      channelId,
      profile: userName ? { username: userName } : undefined,

      send: async (text: string): Promise<SentMessage> => {
        const result = await client.chat.postMessage({
          channel: channelId,
          text: convertToSlackMrkdwn(text),
        });
        const msgTs = (result as { ts?: string }).ts || "";
        return {
          id: msgTs,
          edit: async (t: string) => {
            await client.chat.update({
              channel: channelId,
              ts: msgTs,
              text: convertToSlackMrkdwn(t),
            });
          },
        };
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        await respond({
          text: convertToSlackMrkdwn(text),
          response_type: "ephemeral",
        });
        return {
          id: "ephemeral",
          edit: async (_t: string) => {
            // Slack ephemeral messages cannot be updated
          },
        };
      },

      sendRich: async (msg: RichMessage): Promise<SentMessage> => {
        const markdown = richMessageToMarkdown(msg, "slack");
        await respond({ text: markdown, response_type: "ephemeral" });
        return {
          id: "ephemeral",
          edit: async (_t: string) => {},
        };
      },

      startTyping: async () => {
        // Slack has no typing indicator API for bots
        return () => {};
      },
    };
  }
}
