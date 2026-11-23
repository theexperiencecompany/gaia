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
 * - **DM messages** via the `message` event with `channel_type === "im"`,
 *   including ones carrying files (subtype `file_share`)
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
  type ActiveBotConversation,
  BaseBotAdapter,
  type BotCommand,
  type BotFileData,
  buildAuthLinkMessage,
  type ConversationSurface,
  createBotLogger,
  extractSubcommandArgs,
  hashLogIdentifier,
  type IncomingAttachment,
  type MediaBatchOutcome,
  type OutboundFile,
  type PlatformName,
  REACTION_OUTCOME,
  type ReactionOutcome,
  type RichMessage,
  type RichMessageTarget,
  recordBotFailure,
  renderForPlatform,
  richMessageToMarkdown,
  type SentMessage,
  withWideEvent,
} from "@gaia/shared/bots";
import { App, type CodedError, type Context } from "@slack/bolt";
import { which } from "node-emoji";
import {
  downloadSlackFile,
  type SlackInboundFile,
  slackFileMedia,
} from "./media";

/** What Slack shows while GAIA prepares a reply: it has no typing indicator for bots. */
/** The reaction on the user's message while GAIA prepares its reply; Slack gives bots no typing indicator. */
const SLACK_TYPING_REACTION = "eyes";

/** Bolt's respond function for slash command responses. */
type SlackRespondFn = (
  message: string | Record<string, unknown>,
) => Promise<unknown>;

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
  protected readonly defaultServerPort = 3201;
  private app!: App;
  private token!: string;
  private signingSecret!: string;
  private appToken!: string;
  private readonly adapterLogger = createBotLogger("slack", "adapter");

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
      // Hands the handler the event's context, so the error says who hit it.
      extendedErrorHandler: true,
    });
    // Bolt's last resort for anything a listener or middleware throws: its own
    // unit of work, like Telegram's bot.catch, so it gets a failed event with a
    // reason. Resolving keeps Bolt's receiver from logging it again, unstructured.
    this.app.error(
      async ({ error, context }: { error: CodedError; context: Context }) =>
        withWideEvent(
          "bot_runtime_error",
          {
            platform: this.platform,
            component: "adapter",
            user_hash: hashLogIdentifier(context.userId),
            slack_error_code: error.code,
          },
          async () => {
            recordBotFailure("slack_runtime_error", error.original ?? error);
          },
        ),
    );
  }

  /**
   * Registers unified commands as Slack slash command handlers.
   *
   * Each command's handler:
   * 1. Calls `ack()` immediately (Slack's 3-second requirement)
   * 2. Special-cases `/gaia` to post and follow the conversation
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

          const rawText = command.text || undefined;
          const args = extractSubcommandArgs(commandName, rawText);

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
      const receivedAt = Date.now();
      const botMention = context.botUserId
        ? new RegExp(`<@${context.botUserId}>`, "g")
        : null;
      const caption = botMention
        ? event.text.replace(botMention, "").trim()
        : event.text.trim();
      const userId = event.user;
      const channelId = event.channel;

      if (!userId) return;

      const media = await this.resolveSlackFiles(
        client,
        event.files ?? [],
        caption,
        userId,
        channelId,
      );
      const content = media ? media.text : caption;
      const attachments = media?.attachments ?? [];

      if (!content && attachments.length === 0) {
        // Every file was rejected and its notice already sent.
        if (media) return;
        await client.chat.postMessage({
          channel: channelId,
          text: "How can I help you?",
        });
        return;
      }

      await this.postSlackMessage(
        client,
        channelId,
        userId,
        content,
        false,
        receivedAt,
        event.ts,
        attachments,
      );
    });

    // DM messages; one carrying files arrives with subtype file_share. Bolt's
    // ignoreSelf drops the bot's own uploads, so outbound files never loop back.
    this.app.message(async ({ message, client }) => {
      const receivedAt = Date.now();

      if (message.subtype !== undefined && message.subtype !== "file_share") {
        return;
      }
      if (message.channel_type !== "im") return;
      if (!message.user || !message.channel) return;

      const caption = message.text?.trim() ?? "";
      const media = await this.resolveSlackFiles(
        client,
        message.files ?? [],
        caption,
        message.user,
        message.channel,
      );
      const content = media ? media.text : caption;
      const attachments = media?.attachments ?? [];
      if (!content && attachments.length === 0) return;

      await this.postSlackMessage(
        client,
        message.channel,
        message.user,
        content,
        true,
        receivedAt,
        message.ts,
        attachments,
      );
    });
  }

  /** Starts the Slack Bolt app. */
  protected async start(): Promise<void> {
    await this.app.start();
  }

  /** Stops the Slack Bolt app. */
  protected async stop(): Promise<void> {
    await this.app.stop();
  }

  /**
   * Cache of resolved DM channel ids, keyed by Slack user id. conversations.open
   * is idempotent but rate-limited, so resolve each user's DM once instead of on
   * every outbound send (which could 429 under a burst and livelock requeues).
   */
  private readonly dmChannelCache = new Map<string, string>();

  /**
   * Resolves a Slack user id to its DM channel id (cached). chat.postMessage
   * and files.uploadV2 both need a channel id, and conversations.open is
   * idempotent but rate-limited, so resolve each user's DM once.
   */
  private async resolveDmChannel(destinationId: string): Promise<string> {
    const cached = this.dmChannelCache.get(destinationId);
    if (cached) return cached;
    const dm = await this.app.client.conversations.open({
      users: destinationId,
    });
    const channel = dm.channel?.id;
    if (!channel) {
      throw new Error("Slack conversations.open returned no channel id");
    }
    this.dmChannelCache.set(destinationId, channel);
    return channel;
  }

  /**
   * Runs one outbound send against the conversation's channel id: the channel
   * itself for a channel/group, else the user's resolved DM channel
   * (platform_links stores the user id).
   */
  private async sendToConversation(
    destinationId: string,
    isChannel: boolean,
    send: (channel: string) => Promise<unknown>,
  ): Promise<void> {
    const channel = isChannel
      ? destinationId
      : await this.resolveDmChannel(destinationId);
    try {
      await send(channel);
    } catch (err) {
      // A cached DM channel id can go stale (conversation archived, user
      // deactivated): drop it so the next delivery re-resolves.
      if (!isChannel) this.dmChannelCache.delete(destinationId);
      throw err;
    }
  }

  protected async deliverOutbound(
    destinationId: string,
    text: string,
    isChannel: boolean,
  ): Promise<void> {
    await this.sendToConversation(destinationId, isChannel, (channel) =>
      this.app.client.chat.postMessage({ channel, text }),
    );
  }

  /**
   * Uploads an agent-generated file artifact via files.uploadV2, with the
   * caption as the message comment: into the channel when `isChannel`, else
   * into the user's DM channel.
   */
  protected override async sendOutboundFile(
    destinationId: string,
    { data, filename, caption }: OutboundFile,
    isChannel: boolean,
  ): Promise<void> {
    await this.sendToConversation(destinationId, isChannel, (channel) =>
      this.app.client.files.uploadV2({
        channel_id: channel,
        file: data,
        filename,
        initial_comment: caption,
      }),
    );
  }

  protected override async reactToMessage(
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
    replaces: string | null,
  ): Promise<ReactionOutcome> {
    // reactions.add takes a shortcode (sweat_smile), not the emoji. An emoji
    // with no known shortcode is refused here and the caller sends it as text.
    const name = which(emoji);
    if (!name) {
      this.adapterLogger.warn("outbound_reaction_unmapped_emoji", { emoji });
      return REACTION_OUTCOME.UNMAPPED_EMOJI;
    }
    const channel = isChannel
      ? destinationId
      : await this.resolveDmChannel(destinationId);
    // Slack reactions add up, so GAIA's earlier one comes off before the new one goes on.
    const replacedName = replaces ? which(replaces) : undefined;
    if (replacedName && replacedName !== name) {
      await this.removeReaction(channel, platformMessageId, replacedName);
    }
    try {
      await this.app.client.reactions.add({
        channel,
        timestamp: platformMessageId,
        name,
      });
      return REACTION_OUTCOME.ATTACHED;
    } catch (err) {
      this.adapterLogger.warn("outbound_reaction_attach_failed", {
        channel_hash: hashLogIdentifier(channel),
        ...(err instanceof Error
          ? { error_type: err.name, error: err.message }
          : { error: String(err) }),
      });
      return REACTION_OUTCOME.ATTACH_FAILED;
    }
  }

  /** Takes GAIA's reaction off a message; a failure leaves both showing, which the log records. */
  private async removeReaction(
    channel: string,
    timestamp: string,
    name: string,
  ): Promise<void> {
    try {
      await this.app.client.reactions.remove({ channel, timestamp, name });
    } catch (err) {
      this.adapterLogger.warn("reaction_remove_failed", {
        channel_hash: hashLogIdentifier(channel),
        ...(err instanceof Error
          ? { error_type: err.name, error: err.message }
          : { error: String(err) }),
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Gaia chat
  // ---------------------------------------------------------------------------

  /**
   * Registers the `/gaia` slash command: the message is posted and its reply
   * follows in the channel.
   */
  private registerGaiaCommand(): void {
    this.app.command("/gaia", async ({ command, ack, client }) => {
      const receivedAt = Date.now();
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

      await this.postSlackMessage(
        client,
        channelId,
        userId,
        message,
        channelId.startsWith("D"),
        receivedAt,
      );
    });
  }

  /**
   * Reads the files on a Slack message through the shared pipeline and posts
   * its notice (rejections, skipped files); null when there are no files.
   */
  private async resolveSlackFiles(
    client: SlackWebClient,
    files: SlackInboundFile[],
    caption: string,
    userId: string,
    channelId: string,
  ): Promise<MediaBatchOutcome | null> {
    if (files.length === 0) return null;

    const items = files.map((file): IncomingAttachment => {
      const url = file.url_private_download;
      return {
        media: slackFileMedia(file, caption || undefined),
        // External files (Drive, Dropbox links) carry no Slack download URL.
        download: url
          ? (maxBytes) => downloadSlackFile(url, this.token, maxBytes)
          : undefined,
      };
    });

    const outcome = await this.resolveIncomingMedia(items, userId, channelId);
    if (outcome.notice) {
      await client.chat.postMessage({
        channel: channelId,
        text: outcome.notice,
      });
    }
    return outcome;
  }

  /**
   * Posts a `/gaia` message, @mention or DM and follows its conversation in this
   * channel. Returns once the message is accepted.
   */
  private async postSlackMessage(
    client: SlackWebClient,
    channelId: string,
    userId: string,
    message: string,
    isDm: boolean,
    receivedAt: number,
    inboundTs?: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    // Bolt runs handlers concurrently: a user's posts still go in arrival order.
    await this.arrivals.run(userId, () =>
      this.postAndFollow(
        {
          message,
          platform: "slack",
          platformUserId: userId,
          channelId,
          isDm,
          platformMessageId: inboundTs,
          receivedAt,
          ...(attachments.length > 0
            ? {
                fileIds: attachments.map((a) => a.fileId),
                fileData: attachments,
              }
            : {}),
        },
        this.conversationSurface(channelId),
        (authUrl) => this.sendAuthLink(client, channelId, userId, authUrl),
      ),
    );
  }

  protected async resumeSurface({
    platform_user_id: userId,
    channel_id: channelId,
    is_dm: isDm,
  }: ActiveBotConversation): Promise<ConversationSurface> {
    return this.conversationSurface(
      isDm || !channelId ? await this.resolveDmChannel(userId) : channelId,
    );
  }

  /** The channel a conversation follows into; a quoted reply is a thread reply also shown in the channel. */
  private conversationSurface(channelId: string): ConversationSurface {
    const { client } = this.app;
    const bubble = (ts: string) => ({
      id: ts,
      edit: async (updatedText: string) => {
        await client.chat.update({ channel: channelId, ts, text: updatedText });
      },
    });
    return {
      send: async (text, replyTo) => {
        const posted = await (replyTo
          ? client.chat.postMessage({
              channel: channelId,
              text,
              thread_ts: replyTo,
              reply_broadcast: true,
            })
          : client.chat.postMessage({ channel: channelId, text }));
        const sentTs = posted.ts;
        if (!sentTs) throw new Error("chat.postMessage returned no ts");
        return bubble(sentTs);
      },
      reopen: (ts) => ({
        ...bubble(ts),
        delete: async () => {
          await client.chat.delete({ channel: channelId, ts });
        },
      }),
      react: (platformMessageId, emoji, replaces) =>
        this.reactToMessage(
          channelId,
          platformMessageId,
          emoji,
          true,
          replaces,
        ),
      startTyping: (answering) => this.markAnswering(channelId, answering),
    };
  }

  /**
   * Puts eyes on the message GAIA is answering while it prepares the reply, and
   * takes them off once it stops. A reaction Slack would not add costs only the
   * indicator, so the miss is logged.
   */
  private markAnswering(
    channelId: string,
    answering: string | null,
  ): () => void {
    if (!answering) return () => undefined;
    const added = this.app.client.reactions
      .add({
        channel: channelId,
        timestamp: answering,
        name: SLACK_TYPING_REACTION,
      })
      .then(
        () => true,
        (err: unknown) => {
          this.adapterLogger.warn("typing_reaction_not_added", {
            channel_hash: hashLogIdentifier(channelId),
            ...(err instanceof Error
              ? { error_type: err.name, error: err.message }
              : { error: String(err) }),
          });
          return false;
        },
      );
    return () => {
      void added.then((wasAdded) =>
        wasAdded
          ? this.removeReaction(channelId, answering, SLACK_TYPING_REACTION)
          : undefined,
      );
    };
  }

  /**
   * Sends the account-link prompt: straight into a DM, where chat.postEphemeral is
   * unreliable and no one else can see it; as an ephemeral in a public channel.
   */
  private async sendAuthLink(
    client: SlackWebClient,
    channelId: string,
    userId: string,
    authUrl: string,
  ): Promise<void> {
    const authMessage = renderForPlatform(
      buildAuthLinkMessage(authUrl),
      "slack",
    );
    if (channelId.startsWith("D")) {
      await client.chat.postMessage({ channel: channelId, text: authMessage });
      return;
    }
    await client.chat.postEphemeral({
      channel: channelId,
      user: userId,
      text: authMessage,
    });
  }

  // ---------------------------------------------------------------------------
  // Message target factory
  // ---------------------------------------------------------------------------

  /**
   * Create a {@link RichMessageTarget} for Slack slash command responses.
   *
   * Uses Bolt's `respond` for ephemeral replies and the Web API `client` for
   * public messages; rich messages render as markdown (Slack has no embeds).
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
      isDm: channelId.startsWith("D"),
      profile: userName ? { username: userName } : undefined,

      send: async (text: string): Promise<SentMessage> => {
        const result = await client.chat.postMessage({
          channel: channelId,
          text: renderForPlatform(text, "slack"),
        });
        const msgTs = (result as { ts?: string }).ts || "";
        return {
          id: msgTs,
          edit: async (t: string) => {
            await client.chat.update({
              channel: channelId,
              ts: msgTs,
              text: renderForPlatform(t, "slack"),
            });
          },
        };
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        await respond({
          text: renderForPlatform(text, "slack"),
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
        const markdown = renderForPlatform(richMessageToMarkdown(msg), "slack");
        await respond({ text: markdown, response_type: "ephemeral" });
        return {
          id: "ephemeral",
          edit: async (_t: string) => {
            /* ephemeral messages cannot be edited */
          },
        };
      },

      startTyping: async () => {
        return () => {
          /* Slack has no typing indicator API for bots */
        };
      },
    };
  }
}
