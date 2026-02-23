/**
 * Discord bot adapter for GAIA.
 *
 * Extends {@link BaseBotAdapter} to wire unified commands and events
 * to Discord.js APIs. Handles Discord-specific concerns:
 *
 * - **Slash commands** via `InteractionCreate` events
 * - **Rich embeds** via Discord's native `EmbedBuilder`
 * - **Ephemeral replies** via `MessageFlags.Ephemeral`
 * - **3-second interaction deadline** via auto-deferral
 * - **Typing indicators** via `sendTyping()` with 8s refresh
 * - **DM and @mention** handling via `MessageCreate` events
 * - **Rotating presence** cycling fun statuses every 3 minutes
 * - **DM welcome embed** sent to first-time DM users
 * - **Context menu commands** for Summarize and Add as Todo
 *
 * @module
 */

import {
  BaseBotAdapter,
  type BotCommand,
  formatBotError,
  handleStreamingChat,
  type PlatformName,
  type RichMessage,
  type RichMessageTarget,
  type SentMessage,
  STREAMING_DEFAULTS,
} from "@gaia/shared";
import {
  ActionRowBuilder,
  ActivityType,
  ButtonBuilder,
  ButtonStyle,
  type ChatInputCommandInteraction,
  Client,
  EmbedBuilder,
  Events,
  GatewayIntentBits,
  type Message,
  type MessageContextMenuCommandInteraction,
  MessageFlags,
  Partials,
} from "discord.js";

// ---------------------------------------------------------------------------
// Rotating presence statuses
// ---------------------------------------------------------------------------

const ROTATING_STATUSES: { type: ActivityType; name: string }[] = [
  { type: ActivityType.Watching, name: "over your goals" },
  { type: ActivityType.Listening, name: "to your inner procrastinator" },
  { type: ActivityType.Playing, name: "personal assistant to legends" },
  { type: ActivityType.Competing, name: "in the productivity Olympics" },
  { type: ActivityType.Watching, name: "your productivity soar" },
  { type: ActivityType.Listening, name: "to the sound of getting things done" },
  { type: ActivityType.Playing, name: "life admin simulator" },
  { type: ActivityType.Competing, name: "against your past self" },
  { type: ActivityType.Watching, name: "for tasks worth automating" },
  { type: ActivityType.Listening, name: "to great ideas happen" },
  { type: ActivityType.Playing, name: "the long game with you" },
  { type: ActivityType.Competing, name: "for the title of most helpful AI" },
  { type: ActivityType.Watching, name: "your potential unfold" },
  { type: ActivityType.Listening, name: "to your todo list grow" },
  { type: ActivityType.Playing, name: "chess with your calendar" },
  { type: ActivityType.Competing, name: "in the task completion marathon" },
  { type: ActivityType.Watching, name: "the chaos become clarity" },
  { type: ActivityType.Listening, name: "to your ambitions" },
  { type: ActivityType.Playing, name: "catch-up with your goals" },
  { type: ActivityType.Watching, name: "your habits build momentum" },
  { type: ActivityType.Listening, name: "to your 3am ideas" },
  { type: ActivityType.Playing, name: "scheduler extraordinaire" },
  { type: ActivityType.Competing, name: "with yesterday's you" },
  { type: ActivityType.Watching, name: "your dreams take shape" },
  { type: ActivityType.Listening, name: "to the rhythm of your workflow" },
  { type: ActivityType.Playing, name: "productivity coach unlocked" },
  { type: ActivityType.Watching, name: "out for your deadlines" },
  { type: ActivityType.Listening, name: "to your best ideas yet" },
  { type: ActivityType.Playing, name: "your favorite AI companion" },
  { type: ActivityType.Competing, name: "for best personal assistant 2025" },
  { type: ActivityType.Watching, name: "you crush it today" },
  {
    type: ActivityType.Listening,
    name: "for 'I should write that down' moments",
  },
  { type: ActivityType.Playing, name: "executive assistant" },
  { type: ActivityType.Watching, name: "your workflow evolve" },
  { type: ActivityType.Listening, name: "to a todo list that never quits" },
  { type: ActivityType.Playing, name: "the AI you didn't know you needed" },
  { type: ActivityType.Watching, name: "your future unfold" },
  { type: ActivityType.Listening, name: "to your daily wins" },
  { type: ActivityType.Playing, name: "personal concierge since 2024" },
  { type: ActivityType.Competing, name: "with every other AI (and winning)" },
  { type: ActivityType.Watching, name: "every task you complete" },
  { type: ActivityType.Listening, name: "to the grind (it's paying off)" },
  { type: ActivityType.Playing, name: "co-pilot to your ambitions" },
  { type: ActivityType.Watching, name: "your back (and your calendar)" },
  { type: ActivityType.Listening, name: "to success stories (yours)" },
  { type: ActivityType.Playing, name: "second brain for first-class minds" },
  { type: ActivityType.Watching, name: "for shortcuts to suggest" },
  { type: ActivityType.Listening, name: "to the future you're building" },
  { type: ActivityType.Playing, name: "AI companion to visionaries" },
  { type: ActivityType.Watching, name: "you level up" },
  { type: ActivityType.Listening, name: "to creative sparks ignite" },
  { type: ActivityType.Playing, name: "Swiss Army AI" },
  { type: ActivityType.Competing, name: "in the habit-building championship" },
  { type: ActivityType.Watching, name: "your productivity metrics" },
  { type: ActivityType.Listening, name: "to plans become reality" },
  { type: ActivityType.Playing, name: "assistant to the ambitious" },
  { type: ActivityType.Watching, name: "you outpace expectations" },
  { type: ActivityType.Listening, name: "to ambitions become plans" },
  { type: ActivityType.Playing, name: "the AI that actually remembers" },
  { type: ActivityType.Watching, name: "for the next big breakthrough" },
  { type: ActivityType.Listening, name: "to the productivity beat" },
  { type: ActivityType.Playing, name: "life optimizer" },
  { type: ActivityType.Competing, name: "for your favorite app slot" },
  { type: ActivityType.Watching, name: "you build good habits" },
  { type: ActivityType.Listening, name: "to ideas worth capturing" },
  { type: ActivityType.Playing, name: "the kindest productivity nag" },
  { type: ActivityType.Watching, name: "you turn chaos into clarity" },
  { type: ActivityType.Listening, name: "to your workflow's rhythm" },
  { type: ActivityType.Playing, name: "your personal AI, always on" },
  { type: ActivityType.Watching, name: "for things you might forget" },
  { type: ActivityType.Listening, name: "for 'hey GAIA'" },
  { type: ActivityType.Playing, name: "the long game (like you)" },
  { type: ActivityType.Competing, name: "in the focus championship" },
  { type: ActivityType.Watching, name: "1,000 tasks at once" },
  { type: ActivityType.Listening, name: "to every whisper of an idea" },
  { type: ActivityType.Playing, name: "digital chief of staff" },
  { type: ActivityType.Watching, name: "deadlines approach (very calmly)" },
  { type: ActivityType.Listening, name: "to your calendar breathe" },
  { type: ActivityType.Playing, name: "memory palace curator" },
  { type: ActivityType.Competing, name: "for most proactive AI ever" },
  { type: ActivityType.Watching, name: "your goals get checked off" },
  { type: ActivityType.Listening, name: "to every great plan you make" },
  { type: ActivityType.Playing, name: "task whisperer" },
  { type: ActivityType.Watching, name: "you build something great" },
  { type: ActivityType.Listening, name: "to your procrastinator's excuses" },
  { type: ActivityType.Playing, name: "your cognitive offloading device" },
  { type: ActivityType.Competing, name: "in the inbox zero marathon" },
  { type: ActivityType.Watching, name: "the todo pile (it's growing)" },
  { type: ActivityType.Listening, name: "to your inner visionary" },
  { type: ActivityType.Playing, name: "second brain, first priority" },
  { type: ActivityType.Watching, name: "patterns in your day" },
  { type: ActivityType.Listening, name: "to the future being planned" },
  { type: ActivityType.Playing, name: "accountability partner" },
  { type: ActivityType.Competing, name: "in the deep work tournament" },
  { type: ActivityType.Watching, name: "you stay ahead of the curve" },
  { type: ActivityType.Listening, name: "to your morning intentions" },
  { type: ActivityType.Playing, name: "the AI that has your back" },
  { type: ActivityType.Watching, name: "every goal inch closer" },
  { type: ActivityType.Listening, name: "to tasks get done" },
  { type: ActivityType.Playing, name: "your productivity operating system" },
  { type: ActivityType.Watching, name: "over everything, so you can focus" },
];

const STATUS_ROTATION_INTERVAL_MS = 3 * 60 * 1000;

/**
 * Discord-specific implementation of the GAIA bot adapter.
 *
 * Manages the Discord.js `Client` lifecycle and translates between
 * Discord's interaction/message APIs and the unified command system.
 */
export class DiscordAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "discord";
  private client!: Client;
  private token!: string;
  private dmWelcomeSent = new Set<string>();
  private statusRotationTimer: ReturnType<typeof setInterval> | null = null;
  private statusIndex = Math.floor(Math.random() * ROTATING_STATUSES.length);

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /** Creates the Discord.js Client with the required intents and partials. */
  protected async initialize(): Promise<void> {
    const token = process.env.DISCORD_BOT_TOKEN;
    if (!token) {
      throw new Error("DISCORD_BOT_TOKEN is required");
    }
    this.token = token;

    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
      ],
      partials: [Partials.Channel, Partials.Message],
    });
  }

  /**
   * Registers unified commands as Discord slash command handlers.
   *
   * Each command is dispatched via the `InteractionCreate` event. The
   * `/gaia` command is special-cased to use the adapter's streaming
   * `handleGaiaInteraction` method instead of the unified execute function.
   */
  protected async registerCommands(_commands: BotCommand[]): Promise<void> {
    // Commands are dispatched in the InteractionCreate handler in registerEvents
  }

  /**
   * Registers Discord event listeners:
   * - `ClientReady` — sets rotating presence, logs the bot's tag
   * - `InteractionCreate` — dispatches slash and context menu commands
   * - `MessageCreate` — handles DMs and @mentions
   */
  protected async registerEvents(): Promise<void> {
    this.client.once(Events.ClientReady, (c) => {
      console.log(`Discord bot ready as ${c.user.tag}`);
      this.startStatusRotation(c.user);
    });

    this.client.on(Events.InteractionCreate, async (interaction) => {
      if (interaction.isChatInputCommand()) {
        await this.handleInteraction(interaction);
        return;
      }
      if (interaction.isMessageContextMenuCommand()) {
        await this.handleContextMenuInteraction(interaction);
      }
    });

    this.client.on(Events.MessageCreate, async (message) => {
      if (message.partial) {
        try {
          await message.fetch();
        } catch (error) {
          console.error("Failed to fetch partial message:", error);
          return;
        }
      }

      if (message.author.bot) return;
      if (!this.client.user) return;

      const isDM = !message.guild;
      if (!isDM && !message.mentions.has(this.client.user)) return;

      if (isDM) {
        await this.handleDMMessage(message);
      } else {
        await this.handleMentionMessage(message, this.client.user.id);
      }
    });
  }

  /** Logs in to Discord. */
  protected async start(): Promise<void> {
    await this.client.login(this.token);
  }

  /** Destroys the Discord client connection and clears the status timer. */
  protected async stop(): Promise<void> {
    if (this.statusRotationTimer) {
      clearInterval(this.statusRotationTimer);
      this.statusRotationTimer = null;
    }
    this.client.destroy();
  }

  /**
   * Returns the underlying Discord.js Client.
   * Exposed for `deploy-commands.ts` and testing.
   */
  getClient(): Client {
    return this.client;
  }

  // ---------------------------------------------------------------------------
  // Presence rotation
  // ---------------------------------------------------------------------------

  /** Starts cycling through {@link ROTATING_STATUSES} every 3 minutes. */
  private startStatusRotation(user: NonNullable<Client["user"]>): void {
    const setStatus = () => {
      const status = ROTATING_STATUSES[this.statusIndex];
      user.setPresence({
        status: "online",
        activities: [{ name: status.name, type: status.type }],
      });
      this.statusIndex = (this.statusIndex + 1) % ROTATING_STATUSES.length;
    };

    setStatus();
    this.statusRotationTimer = setInterval(
      setStatus,
      STATUS_ROTATION_INTERVAL_MS,
    );
  }

  // ---------------------------------------------------------------------------
  // Interaction handling
  // ---------------------------------------------------------------------------

  /**
   * Routes a Discord slash command interaction to the appropriate handler.
   *
   * Special-cases the `/gaia` command to use streaming; all other commands
   * go through the unified `dispatchCommand` path.
   */
  private async handleInteraction(
    interaction: ChatInputCommandInteraction,
  ): Promise<void> {
    const name = interaction.commandName;

    if (name === "gaia") {
      await this.handleGaiaInteraction(interaction);
      return;
    }

    const target = this.createInteractionTarget(interaction);
    const args = this.extractInteractionArgs(interaction, name);

    await this.dispatchCommand(name, target, args);
  }

  /**
   * Handles the `/gaia` slash command with Discord-specific streaming.
   *
   * Uses a public deferred reply + `editReply` / `followUp` to stream
   * the response while respecting Discord's interaction model.
   */
  private async handleGaiaInteraction(
    interaction: ChatInputCommandInteraction,
  ): Promise<void> {
    const message = interaction.options.getString("message", true);
    const userId = interaction.user.id;
    const channelId = interaction.channelId;

    await interaction.deferReply();
    let isFirstMessage = true;
    let lastFollowUp: Awaited<ReturnType<typeof interaction.followUp>> | null =
      null;

    await handleStreamingChat(
      this.gaia,
      { message, platform: "discord", platformUserId: userId, channelId },
      async (text: string) => {
        if (isFirstMessage) {
          await interaction.editReply({ content: text });
        } else if (lastFollowUp) {
          await lastFollowUp.edit({ content: text });
        }
      },
      async (text: string) => {
        lastFollowUp = await interaction.followUp({ content: text });
        isFirstMessage = false;
        return async (updatedText: string) => {
          if (lastFollowUp) {
            await lastFollowUp.edit({ content: updatedText });
          }
        };
      },
      async (authUrl: string) => {
        const content = `Please authenticate first: ${authUrl}`;
        if (isFirstMessage) {
          await interaction.editReply({ content });
        } else if (lastFollowUp) {
          await lastFollowUp.edit({ content });
        }
      },
      async (errMsg: string) => {
        if (isFirstMessage) {
          await interaction.editReply({ content: errMsg });
        } else if (lastFollowUp) {
          await lastFollowUp.edit({ content: errMsg });
        }
      },
      STREAMING_DEFAULTS.discord,
    );
  }

  /**
   * Handles right-click context menu commands on messages.
   * Supports "Summarize with GAIA" and "Add as Todo".
   */
  private async handleContextMenuInteraction(
    interaction: MessageContextMenuCommandInteraction,
  ): Promise<void> {
    const name = interaction.commandName;
    const content = interaction.targetMessage.content;
    const userId = interaction.user.id;
    const channelId = interaction.channelId;

    await interaction.deferReply({ flags: MessageFlags.Ephemeral });

    if (!content.trim()) {
      await interaction.editReply({
        content: "That message has no text content to work with.",
      });
      return;
    }

    if (name === "Summarize with GAIA") {
      let replied = false;
      await handleStreamingChat(
        this.gaia,
        {
          message: `Summarize the following message in 2-3 concise sentences:\n\n"${content.slice(0, 1000)}"`,
          platform: "discord",
          platformUserId: userId,
          channelId,
        },
        async (text: string) => {
          await interaction.editReply({ content: `**Summary**\n${text}` });
          replied = true;
        },
        async (text: string) => {
          replied = true;
          await interaction.editReply({ content: `**Summary**\n${text}` });
          return async (updated: string) => {
            await interaction.editReply({ content: `**Summary**\n${updated}` });
          };
        },
        async (authUrl: string) => {
          await interaction.editReply({
            content: `Please link your GAIA account first: ${authUrl}`,
          });
          replied = true;
        },
        async (err: string) => {
          if (!replied) await interaction.editReply({ content: err });
        },
        STREAMING_DEFAULTS.discord,
      );
      return;
    }

    if (name === "Add as Todo") {
      const title = content.slice(0, 200).replace(/\n/g, " ").trim();
      let replied = false;
      await handleStreamingChat(
        this.gaia,
        {
          message: `Add this as a todo item: "${title}"`,
          platform: "discord",
          platformUserId: userId,
          channelId,
        },
        async (text: string) => {
          await interaction.editReply({ content: `**Todo Added**\n${text}` });
          replied = true;
        },
        async (text: string) => {
          replied = true;
          await interaction.editReply({ content: `**Todo Added**\n${text}` });
          return async (updated: string) => {
            await interaction.editReply({
              content: `**Todo Added**\n${updated}`,
            });
          };
        },
        async (authUrl: string) => {
          await interaction.editReply({
            content: `Please link your GAIA account first: ${authUrl}`,
          });
          replied = true;
        },
        async (err: string) => {
          if (!replied) await interaction.editReply({ content: err });
        },
        STREAMING_DEFAULTS.discord,
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Mention / DM handling
  // ---------------------------------------------------------------------------

  /**
   * Handles DM messages with authenticated streaming.
   *
   * Sends a welcome embed to first-time users before processing their message.
   */
  private async handleDMMessage(message: Message): Promise<void> {
    const userId = message.author.id;

    if (!this.dmWelcomeSent.has(userId)) {
      this.dmWelcomeSent.add(userId);
      await this.sendDMWelcome(message);
    }

    const content = message.content.trim();
    if (!content) {
      await (message.channel as { send: (t: string) => Promise<Message> }).send(
        "How can I help you?",
      );
      return;
    }

    const send = (text: string) =>
      (message.channel as { send: (t: string) => Promise<Message> }).send(text);

    try {
      const hasTyping = "sendTyping" in message.channel;
      if (hasTyping) await message.channel.sendTyping();

      let typingInterval: ReturnType<typeof setInterval> | null = hasTyping
        ? setInterval(async () => {
            try {
              await (
                message.channel as { sendTyping: () => Promise<void> }
              ).sendTyping();
            } catch {}
          }, 8000)
        : null;

      const clearTyping = () => {
        if (typingInterval) {
          clearInterval(typingInterval);
          typingInterval = null;
        }
      };

      let currentMsg: Message | null = null;

      await handleStreamingChat(
        this.gaia,
        {
          message: content,
          platform: "discord",
          platformUserId: userId,
          channelId: message.channelId,
        },
        async (text: string) => {
          clearTyping();
          if (!currentMsg) {
            currentMsg = await send(text);
          } else {
            await currentMsg.edit(text);
          }
        },
        async (text: string) => {
          clearTyping();
          currentMsg = await send(text);
          return async (updatedText: string) => {
            await currentMsg?.edit(updatedText);
          };
        },
        async (authUrl: string) => {
          clearTyping();
          const msg = `Please authenticate first: ${authUrl}`;
          if (!currentMsg) {
            currentMsg = await send(msg);
          } else {
            await currentMsg.edit(msg);
          }
        },
        async (errMsg: string) => {
          clearTyping();
          if (!currentMsg) {
            currentMsg = await send(errMsg);
          } else {
            await currentMsg.edit(errMsg);
          }
        },
        STREAMING_DEFAULTS.discord,
      );

      clearTyping();
    } catch (error) {
      await send(formatBotError(error));
    }
  }

  /**
   * Sends a rich welcome embed to a first-time DM user.
   *
   * Includes a direct link to heygaia.io with a proper OG preview.
   */
  private async sendDMWelcome(message: Message): Promise<void> {
    const embed = new EmbedBuilder()
      .setColor(0x6366f1)
      .setTitle("Hey, I'm GAIA 👋")
      .setDescription(
        "Your personal AI — built to think ahead, remember everything, and get things done with you.\n\nHere's what I can do right in Discord:",
      )
      .addFields(
        {
          name: "💬 Chat",
          value:
            "Just type anything. Ask questions, brainstorm, think out loud.",
          inline: false,
        },
        {
          name: "✅ Todos",
          value:
            "Use `/todo add` to capture tasks. Right-click any message → **Add as Todo**.",
          inline: false,
        },
        {
          name: "⚡ Workflows",
          value: "Run automations with `/workflow`. Delegate entire projects.",
          inline: false,
        },
        {
          name: "🔗 Link your account",
          value:
            "Use `/auth` to connect your GAIA account for memory and personalization.",
          inline: false,
        },
      )
      .setFooter({
        text: "Tip: Right-click any message to summarize it or add it as a todo.",
      })
      .setTimestamp();

    const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
      new ButtonBuilder()
        .setLabel("Visit heygaia.io")
        .setURL("https://heygaia.io")
        .setStyle(ButtonStyle.Link),
      new ButtonBuilder()
        .setLabel("Read the Docs")
        .setURL("https://docs.heygaia.io")
        .setStyle(ButtonStyle.Link),
    );

    try {
      await (
        message.channel as {
          send: (opts: {
            embeds: EmbedBuilder[];
            components: ActionRowBuilder<ButtonBuilder>[];
          }) => Promise<Message>;
        }
      ).send({ embeds: [embed], components: [row] });
    } catch {
      // If we can't send the welcome, continue silently
    }
  }

  /**
   * Handles @mention messages in guild channels.
   *
   * Strips the bot's own mention tag, sends a typing indicator, and
   * delegates to `handleStreamingChat` for authenticated guild-scoped streaming.
   */
  private async handleMentionMessage(
    message: Message,
    botId: string,
  ): Promise<void> {
    const content = message.content
      .replace(new RegExp(`<@!?${botId}>`, "g"), "")
      .trim();

    if (!content) {
      await message.reply("How can I help you?");
      return;
    }

    const isDM = !message.guild;
    const send = isDM
      ? (text: string) =>
          (message.channel as { send: (t: string) => Promise<Message> }).send(
            text,
          )
      : (text: string) => message.reply(text);

    try {
      const hasTyping = "sendTyping" in message.channel;
      if (hasTyping) {
        await message.channel.sendTyping();
      }

      let typingInterval: ReturnType<typeof setInterval> | null = hasTyping
        ? setInterval(async () => {
            try {
              await (
                message.channel as { sendTyping: () => Promise<void> }
              ).sendTyping();
            } catch {}
          }, 8000)
        : null;

      const clearTyping = () => {
        if (typingInterval) {
          clearInterval(typingInterval);
          typingInterval = null;
        }
      };

      let currentMsg: Message | null = null;

      const sendOrEdit = async (text: string) => {
        clearTyping();
        if (!currentMsg) {
          currentMsg = await send(text);
        } else {
          await currentMsg.edit(text);
        }
      };

      await handleStreamingChat(
        this.gaia,
        {
          message: content,
          platform: "discord",
          platformUserId: message.author.id,
          channelId: message.channelId,
        },
        sendOrEdit,
        async (text: string) => {
          clearTyping();
          currentMsg = await send(text);
          return async (updatedText: string) => {
            await currentMsg?.edit(updatedText);
          };
        },
        async (authUrl: string) => {
          clearTyping();
          try {
            await message.reply({
              content: `Please link your GAIA account to use me here: ${authUrl}`,
            });
          } catch {
            // Ephemeral replies unsupported on some message types — fall back publicly
            await sendOrEdit(
              `Please link your GAIA account: ${authUrl}\n\n_This link is for you only — don't share it._`,
            );
          }
        },
        async (errMsg: string) => {
          clearTyping();
          await sendOrEdit(errMsg);
        },
        STREAMING_DEFAULTS.discord,
      );

      clearTyping();
    } catch (error) {
      await send(formatBotError(error));
    }
  }

  // ---------------------------------------------------------------------------
  // Message target factories
  // ---------------------------------------------------------------------------

  /**
   * Creates a {@link RichMessageTarget} from a Discord slash command interaction.
   *
   * Auto-defers the interaction on the first send to avoid the 3-second deadline.
   * Supports ephemeral replies and Discord-native embeds via `sendRich`.
   */
  private createInteractionTarget(
    interaction: ChatInputCommandInteraction,
  ): RichMessageTarget {
    let deferred = false;

    // Defer with the correct visibility on the first send/sendEphemeral/sendRich call.
    // send() → public reply; sendEphemeral()/sendRich() → ephemeral reply.
    const deferIfNeeded = async (ephemeral: boolean) => {
      if (!deferred && !interaction.replied && !interaction.deferred) {
        await interaction.deferReply({
          flags: ephemeral ? MessageFlags.Ephemeral : undefined,
        });
        deferred = true;
      }
    };

    return {
      platform: "discord",
      userId: interaction.user.id,
      channelId: interaction.channelId,
      profile: {
        username: interaction.user.username,
        displayName: interaction.user.globalName ?? interaction.user.username,
      },

      send: async (text: string): Promise<SentMessage> => {
        await deferIfNeeded(false);
        await interaction.editReply({ content: text });
        return {
          id: interaction.id,
          edit: async (t: string) => {
            await interaction.editReply({ content: t });
          },
        };
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        await deferIfNeeded(true);
        await interaction.editReply({ content: text });
        return {
          id: interaction.id,
          edit: async (t: string) => {
            await interaction.editReply({ content: t });
          },
        };
      },

      sendRich: async (msg: RichMessage): Promise<SentMessage> => {
        await deferIfNeeded(false);
        const embed = richMessageToEmbed(msg);
        await interaction.editReply({ embeds: [embed] });
        return {
          id: interaction.id,
          edit: async (t: string) => {
            await interaction.editReply({ content: t, embeds: [] });
          },
        };
      },

      startTyping: async () => {
        return () => {};
      },
    };
  }

  /**
   * Extracts slash command arguments from a Discord interaction.
   *
   * Handles both top-level options and subcommand-specific options,
   * mapping them to a flat `Record<string, ...>` for the unified command system.
   */
  private extractInteractionArgs(
    interaction: ChatInputCommandInteraction,
    commandName: string,
  ): Record<string, string | number | boolean | undefined> {
    const args: Record<string, string | number | boolean | undefined> = {};

    // Check for subcommand first
    try {
      const sub = interaction.options.getSubcommand(false);
      if (sub) {
        args.subcommand = sub;
      }
    } catch {
      // No subcommand — fine
    }

    // Extract known option names based on the command definition
    const command = this.commands.get(commandName);
    if (!command) return args;

    const optionSources = command.subcommands
      ? command.subcommands.flatMap((s) => s.options || [])
      : command.options || [];

    for (const opt of optionSources) {
      try {
        if (opt.type === "integer") {
          const val = interaction.options.getInteger(opt.name);
          if (val !== null) args[opt.name] = val;
        } else if (opt.type === "boolean") {
          const val = interaction.options.getBoolean(opt.name);
          if (val !== null) args[opt.name] = val;
        } else {
          const val = interaction.options.getString(opt.name);
          if (val !== null) args[opt.name] = val;
        }
      } catch {
        // Option not present for this subcommand — fine
      }
    }

    return args;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Converts a {@link RichMessage} to a Discord `EmbedBuilder`.
 *
 * Used by the Discord adapter's `sendRich` method to render structured
 * content using Discord's native embed format.
 *
 * @param msg - The platform-agnostic rich message.
 * @returns A Discord `EmbedBuilder` ready to be sent.
 */
function richMessageToEmbed(msg: RichMessage): EmbedBuilder {
  const embed = new EmbedBuilder().setTitle(msg.title);

  if (msg.description) embed.setDescription(msg.description);
  if (msg.color !== undefined) embed.setColor(msg.color);
  if (msg.footer) embed.setFooter({ text: msg.footer });
  if (msg.timestamp) embed.setTimestamp();
  if (msg.thumbnailUrl) embed.setThumbnail(msg.thumbnailUrl);
  if (msg.authorName) {
    embed.setAuthor({
      name: msg.authorName,
      iconURL: msg.authorIconUrl ?? undefined,
    });
  }

  for (const field of msg.fields) {
    embed.addFields({
      name: field.name,
      value: field.value,
      inline: field.inline ?? false,
    });
  }

  if (msg.links && msg.links.length > 0) {
    const linkText = msg.links.map((l) => `[${l.label}](${l.url})`).join(" | ");
    embed.addFields({ name: "🔗 Useful Links", value: linkText });
  }

  return embed;
}
