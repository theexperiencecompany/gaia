/**
 * Tests for the DiscordAdapter.
 *
 * The adapter constructor and boot() require a live Discord token and network
 * access, so we test the observable behaviors that don't need a live connection:
 *
 * 1. platform property value
 * 2. Mention-stripping regex used in handleMentionMessage
 * 3. ROTATING_STATUSES array shape (exported indirectly through the module)
 * 4. richMessageToEmbed logic (via the adapter's sendRich path, tested
 *    using a minimal interaction mock so we never call client.login())
 * 5. createInteractionTarget – deferral, send, sendEphemeral, sendRich
 * 6. extractInteractionArgs – subcommand + typed option extraction
 * 7. handleInteraction routing (gaia vs. generic command)
 * 8. Error handling in dispatchCommand when command is unknown
 *
 * Discord.js and @gaia/shared are mocked so no real HTTP calls are made.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock discord.js before importing the adapter so the module sees the mocks.
// ---------------------------------------------------------------------------

vi.mock("discord.js", () => {
  // biome-ignore lint/complexity/useArrowFunction: vitest invokes mockImplementation as a constructor (new EmbedBuilder()), which requires function() not =>
  const EmbedBuilder = vi.fn().mockImplementation(function () {
    const self: Record<string, unknown> = {};
    const chain = (name: string) => {
      self[name] = vi.fn().mockReturnValue(self);
    };
    [
      "setTitle",
      "setDescription",
      "setColor",
      "setFooter",
      "setTimestamp",
      "setThumbnail",
      "setAuthor",
      "addFields",
    ].forEach(chain);
    return self;
  });

  return {
    EmbedBuilder,
    ActionRowBuilder: vi
      .fn()
      // biome-ignore lint/complexity/useArrowFunction: vitest invokes mockImplementation as a constructor (new ActionRowBuilder()), which requires function() not =>
      .mockImplementation(function () {
        return { addComponents: vi.fn().mockReturnThis() };
      }),
    // biome-ignore lint/complexity/useArrowFunction: vitest invokes mockImplementation as a constructor (new ButtonBuilder()), which requires function() not =>
    ButtonBuilder: vi.fn().mockImplementation(function () {
      return {
        setLabel: vi.fn().mockReturnThis(),
        setURL: vi.fn().mockReturnThis(),
        setStyle: vi.fn().mockReturnThis(),
      };
    }),
    ButtonStyle: { Link: 5 },
    // biome-ignore lint/complexity/useArrowFunction: vitest invokes mockImplementation as a constructor (new Client()), which requires function() not =>
    Client: vi.fn().mockImplementation(function () {
      return {
        once: vi.fn(),
        on: vi.fn(),
        login: vi.fn().mockResolvedValue(undefined),
        destroy: vi.fn(),
        user: { id: "bot-user-id", tag: "GAIA#0001" },
      };
    }),
    Events: {
      ClientReady: "ready",
      InteractionCreate: "interactionCreate",
      MessageCreate: "messageCreate",
      Error: "error",
    },
    GatewayIntentBits: {
      Guilds: 1,
      GuildMessages: 2,
      MessageContent: 4,
      DirectMessages: 8,
    },
    Partials: { Channel: "CHANNEL", Message: "MESSAGE" },
    ActivityType: {
      Watching: 3,
      Listening: 2,
      Playing: 0,
      Competing: 5,
    },
    MessageFlags: { Ephemeral: 64 },
  };
});

// ---------------------------------------------------------------------------
// Mock @gaia/shared so we control postAndFollow.
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared/bots", async () => {
  // The real boundary and failure recorder, so the client-error test reads the
  // bot_event the adapter really prints.
  const actual =
    await vi.importActual<typeof import("@gaia/shared/bots")>(
      "@gaia/shared/bots",
    );
  const { platformIdentity } = await vi.importActual<
    typeof import("@gaia/shared/analytics")
  >("@gaia/shared/analytics");
  const { postAndFollowSpy } = await import("../shared/mocks/postAndFollow");
  const { ArrivalOrder } = await import(
    "../../../../libs/shared/ts/src/bots/adapter/arrival-order"
  );
  const BaseBotAdapter = class {
    platform = "discord";
    gaia = {};
    config = {};
    commands = new Map();
    analytics = undefined;

    /** Mirrors the real base class: identity-bound analytics for shared helpers. */
    protected async analyticsFor(platformUserId: string) {
      return {
        client: this.analytics,
        distinctId: await this.resolveDistinctId(platformUserId),
      };
    }

    /** Unlinked-user path — these tests assert routing, not identity. */
    protected async resolveDistinctId(platformUserId: string) {
      return platformIdentity(this.platform, platformUserId);
    }

    protected async dispatchCommand(
      name: string,
      target: {
        sendEphemeral: (t: string) => Promise<unknown>;
        userId: string;
        channelId: string;
        profile?: { username?: string; displayName?: string };
      },
      args: Record<string, string | number | boolean | undefined> = {},
      rawText?: string,
    ) {
      const cmd = this.commands.get(name);
      if (!cmd) {
        await target.sendEphemeral(`Unknown command: /${name}`);
        return;
      }
      const ctx = this.buildContext(
        target.userId,
        target.channelId,
        target.profile,
      );
      try {
        await cmd.execute({ gaia: this.gaia, target, ctx, args, rawText });
      } catch (error) {
        const errMsg =
          error instanceof Error
            ? `Error: ${error.message}`
            : "Something went wrong";
        try {
          await target.sendEphemeral(errMsg);
        } catch {
          // Target may be expired
        }
      }
    }
    /** The real arrival order, so handler ordering is production's. */
    protected readonly arrivals = new ArrivalOrder();

    /** Records the post, in arrival order; tests drive the surface and auth handler it was handed. */
    protected postAndFollow(
      ...args: Parameters<typeof postAndFollowSpy>
    ): Promise<void> {
      return this.arrivals.post(() => postAndFollowSpy(...args));
    }

    protected buildContext(
      userId: string,
      channelId?: string,
      profile?: { username?: string; displayName?: string },
    ) {
      return {
        platform: this.platform,
        platformUserId: userId,
        channelId,
        profile,
      };
    }

    // Real once-per-user welcome gate (mirrors BaseBotAdapter): returns true the
    // first time a userId is seen, false on every subsequent call.
    private readonly _welcomed = new Set<string>();
    protected shouldSendWelcome(userId: string): boolean {
      if (this._welcomed.has(userId)) return false;
      this._welcomed.add(userId);
      return true;
    }

    // Real typing-indicator helper (mirrors BaseBotAdapter): fires the send
    // function once and returns a no-op stop function.
    protected startTypingIndicator(
      sendTyping: () => Promise<unknown>,
      _refreshMs: number,
    ): () => void {
      void sendTyping().catch(() => {
        // Swallow typing-indicator errors — they are non-fatal.
      });
      return () => {
        // No-op stop function (the real timer is covered by base behavior tests).
      };
    }
  };

  return {
    BaseBotAdapter,
    withWideEvent: actual.withWideEvent,
    recordBotFailure: actual.recordBotFailure,
    createBotLogger: vi.fn(() => ({
      debug: vi.fn(),
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
    })),
    hashLogIdentifier: vi.fn((value: string | number | undefined | null) => {
      if (value === undefined || value === null) return undefined;
      return `h_${String(value)}`;
    }),
    sanitizeErrorForLog: vi.fn((error: unknown) => {
      if (error instanceof Error) {
        return { error_type: error.name, error: error.message };
      }
      return { error_type: "Unknown", error: String(error) };
    }),
    formatBotError: vi.fn((err: unknown) =>
      err instanceof Error ? `Error: ${err.message}` : "Something went wrong",
    ),
    STREAMING_DEFAULTS: {
      discord: { editIntervalMs: 1200, streaming: false, platform: "discord" },
    },
    richMessageToMarkdown: vi.fn().mockReturnValue("mocked markdown"),
    // renderForPlatform is mocked as identity — conversion is exercised in the
    // shared formatters tests, not at the adapter level (which mocks @gaia/shared).
    renderForPlatform: vi.fn((t: string) => t),
    buildAuthLinkMessage: actual.buildAuthLinkMessage,
    wideLog: { warning: vi.fn() },
    parseTextArgs: vi.fn((text: string) => ({
      subcommand: text.split(" ")[0],
    })),
    REACTION_OUTCOME: actual.REACTION_OUTCOME,
  };
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import type { OutboundFile, ReactionOutcome } from "@gaia/shared/bots";
import { DiscordAdapter } from "../../discord/src/adapter";
import { captureBotEvents } from "../shared/helpers/capture-bot-event";
import {
  lastAuthHandler,
  lastSurface,
  postAndFollowSpy,
} from "../shared/mocks/postAndFollow";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a minimal ChatInputCommandInteraction mock. */
function makeChatInteraction(overrides: {
  commandName?: string;
  userId?: string;
  channelId?: string;
  replied?: boolean;
  deferred?: boolean;
  optionString?: string | null;
  subcommand?: string | null;
}) {
  const {
    commandName = "todo",
    userId = "user-123",
    channelId = "channel-abc",
    replied = false,
    deferred = false,
    optionString = null,
    subcommand = null,
  } = overrides;

  return {
    commandName,
    user: { id: userId, username: "tester", globalName: "Tester" },
    channelId,
    replied,
    deferred,
    deferReply: vi.fn().mockResolvedValue(undefined),
    editReply: vi.fn().mockResolvedValue(undefined),
    followUp: vi.fn().mockResolvedValue({ edit: vi.fn() }),
    isChatInputCommand: () => true,
    isMessageContextMenuCommand: () => false,
    options: {
      getString: vi.fn().mockReturnValue(optionString),
      getInteger: vi.fn().mockReturnValue(null),
      getBoolean: vi.fn().mockReturnValue(null),
      getSubcommand: vi.fn().mockReturnValue(subcommand),
    },
  };
}

/** Returns a minimal guild Message mock (for @mention handling). */
function makeGuildMessage(overrides: {
  content?: string;
  botId?: string;
  hasGuild?: boolean;
  authorBot?: boolean;
}) {
  const {
    content = "<@bot-id> hello",
    hasGuild = true,
    authorBot = false,
  } = overrides;

  return {
    content,
    author: { id: "user-123", bot: authorBot },
    guild: hasGuild ? { id: "guild-abc" } : null,
    channelId: "channel-abc",
    partial: false,
    mentions: {
      has: vi.fn().mockReturnValue(true),
    },
    channel: {
      sendTyping: vi.fn().mockResolvedValue(undefined),
      send: vi.fn().mockResolvedValue({ edit: vi.fn() }),
    },
    reply: vi.fn().mockResolvedValue({ edit: vi.fn() }),
    fetch: vi.fn().mockResolvedValue(undefined),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DiscordAdapter - platform identity", () => {
  it('reports platform as "discord"', () => {
    const adapter = new DiscordAdapter();
    expect(adapter.platform).toBe("discord");
  });
});

// ---------------------------------------------------------------------------
// createInteractionTarget
// ---------------------------------------------------------------------------

describe("DiscordAdapter - createInteractionTarget via handleInteraction", () => {
  let adapter: DiscordAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = new DiscordAdapter();
    // Plant a simple command so dispatchCommand can find it.
    // The execute calls target.send() so that createInteractionTarget's lazy
    // deferral fires — allowing deferReply assertions to work correctly.
    const mockCommand = {
      name: "todo",
      description: "Manage todos",
      options: [
        { name: "text", description: "Task text", type: "string" as const },
      ],
      execute: vi
        .fn()
        .mockImplementation(
          async ({
            target,
          }: {
            target: { send: (t: string) => Promise<unknown> };
          }) => {
            await target.send("todo response");
          },
        ),
    };
    // Access the protected `commands` map via the BaseBotAdapter stub.
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "todo",
      mockCommand,
    );
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("defers reply on first send (not previously deferred)", async () => {
    const interaction = makeChatInteraction({
      commandName: "todo",
      replied: false,
      deferred: false,
    });

    // handleInteraction is private; invoke via cast (registerEvents() wires it internally).
    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);

    expect(interaction.deferReply).toHaveBeenCalledOnce();
    expect(interaction.deferReply).toHaveBeenCalledWith({
      flags: undefined,
    });
  });

  it("does not defer if interaction is already deferred", async () => {
    const interaction = makeChatInteraction({
      commandName: "todo",
      replied: false,
      deferred: true,
    });

    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);

    // Already deferred — adapter must not double-defer.
    expect(interaction.deferReply).not.toHaveBeenCalled();
  });

  it("routes /gaia command to handleGaiaInteraction (posts and follows)", async () => {
    const interaction = makeChatInteraction({
      commandName: "gaia",
      optionString: "What is 2+2?",
    });

    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);

    // The /gaia path must defer and then post the message and follow its reply.
    expect(interaction.deferReply).toHaveBeenCalled();
    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "What is 2+2?",
        platform: "discord",
        platformUserId: "user-123",
        channelId: "channel-abc",
      }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });

  it("routes non-gaia command through dispatchCommand", async () => {
    const interaction = makeChatInteraction({ commandName: "todo" });
    const dispatchSpy = vi.spyOn(
      adapter as unknown as { dispatchCommand: () => Promise<void> },
      "dispatchCommand",
    );

    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);

    expect(dispatchSpy).toHaveBeenCalledWith(
      "todo",
      expect.objectContaining({ platform: "discord", userId: "user-123" }),
      expect.any(Object), // args extracted from interaction options
    );
  });
});

// ---------------------------------------------------------------------------
// sendEphemeral defers with Ephemeral flag
// ---------------------------------------------------------------------------

describe("DiscordAdapter - ephemeral replies", () => {
  it("defers with MessageFlags.Ephemeral when sendEphemeral is called first", async () => {
    const adapter = new DiscordAdapter();

    const interaction = makeChatInteraction({
      commandName: "settings",
      replied: false,
      deferred: false,
    });

    // Plant a command that calls target.sendEphemeral.
    const settingsCommand = {
      name: "settings",
      description: "Settings",
      options: [],
      execute: async ({
        target,
      }: {
        target: { sendEphemeral: (t: string) => Promise<unknown> };
      }) => {
        await target.sendEphemeral("Here are your settings.");
      },
    };
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "settings",
      settingsCommand,
    );

    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);

    expect(interaction.deferReply).toHaveBeenCalledWith({ flags: 64 });
  });
});

// ---------------------------------------------------------------------------
// extractInteractionArgs
// ---------------------------------------------------------------------------

describe("DiscordAdapter - extractInteractionArgs", () => {
  let adapter: DiscordAdapter;

  beforeEach(() => {
    adapter = new DiscordAdapter();
  });

  it("extracts string option value", async () => {
    const cmd = {
      name: "todo",
      description: "Manage todos",
      options: [{ name: "task", description: "Task", type: "string" as const }],
      execute: vi.fn(),
    };
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "todo",
      cmd,
    );

    const interaction = makeChatInteraction({
      commandName: "todo",
      optionString: "Buy milk",
    });
    interaction.options.getString = vi.fn().mockReturnValue("Buy milk");

    const args = (
      adapter as unknown as {
        extractInteractionArgs: (
          i: typeof interaction,
          name: string,
        ) => Record<string, unknown>;
      }
    ).extractInteractionArgs(interaction, "todo");

    expect(args.task).toBe("Buy milk");
  });

  it("extracts subcommand name", async () => {
    const cmd = {
      name: "todo",
      description: "Manage todos",
      subcommands: [{ name: "list", description: "List todos", options: [] }],
      execute: vi.fn(),
    };
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "todo",
      cmd,
    );

    const interaction = makeChatInteraction({
      commandName: "todo",
      subcommand: "list",
    });

    const args = (
      adapter as unknown as {
        extractInteractionArgs: (
          i: typeof interaction,
          name: string,
        ) => Record<string, unknown>;
      }
    ).extractInteractionArgs(interaction, "todo");

    expect(args.subcommand).toBe("list");
  });

  it("returns empty args when command is unknown", async () => {
    const interaction = makeChatInteraction({ commandName: "unknown" });

    const args = (
      adapter as unknown as {
        extractInteractionArgs: (
          i: typeof interaction,
          name: string,
        ) => Record<string, unknown>;
      }
    ).extractInteractionArgs(interaction, "unknown");

    expect(args).toEqual({});
  });

  it("extracts integer option value", async () => {
    const cmd = {
      name: "reminder",
      description: "Set reminder",
      options: [
        {
          name: "minutes",
          description: "Minutes from now",
          type: "integer" as const,
        },
      ],
      execute: vi.fn(),
    };
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "reminder",
      cmd,
    );

    const interaction = makeChatInteraction({ commandName: "reminder" });
    interaction.options.getInteger = vi.fn().mockReturnValue(30);

    const args = (
      adapter as unknown as {
        extractInteractionArgs: (
          i: typeof interaction,
          name: string,
        ) => Record<string, unknown>;
      }
    ).extractInteractionArgs(interaction, "reminder");

    expect(args.minutes).toBe(30);
  });
});

// ---------------------------------------------------------------------------
// handleMentionMessage — mention stripping
// ---------------------------------------------------------------------------

describe("DiscordAdapter - mention stripping via handleMentionMessage", () => {
  /**
   * These tests call the real handleMentionMessage method and assert on
   * what content reaches postAndFollow — the actual production behavior.
   *
   * BOT_ID matches the Client mock: user.id = "bot-user-id"
   */
  const BOT_ID = "bot-user-id";
  let adapter: DiscordAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = new DiscordAdapter();
  });

  it("strips <@botId> mention before passing content to postAndFollow", async () => {
    const message = makeGuildMessage({
      content: `<@${BOT_ID}> remind me to call dentist`,
      botId: BOT_ID,
    });

    await (
      adapter as unknown as {
        handleMentionMessage: (
          m: typeof message,
          botId: string,
        ) => Promise<void>;
      }
    ).handleMentionMessage(message, BOT_ID);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: "remind me to call dentist" }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });

  it("strips <@!botId> nickname mention before passing to postAndFollow", async () => {
    const message = makeGuildMessage({
      content: `<@!${BOT_ID}> what time is it?`,
      botId: BOT_ID,
    });

    await (
      adapter as unknown as {
        handleMentionMessage: (
          m: typeof message,
          botId: string,
        ) => Promise<void>;
      }
    ).handleMentionMessage(message, BOT_ID);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: "what time is it?" }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });

  it("replies 'How can I help you?' when message is only a mention (empty after strip)", async () => {
    const message = makeGuildMessage({
      content: `<@${BOT_ID}>`,
      botId: BOT_ID,
    });

    await (
      adapter as unknown as {
        handleMentionMessage: (
          m: typeof message,
          botId: string,
        ) => Promise<void>;
      }
    ).handleMentionMessage(message, BOT_ID);

    expect(message.reply).toHaveBeenCalledWith("How can I help you?");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("leaves unrelated content unchanged when passed to postAndFollow", async () => {
    const message = makeGuildMessage({
      content: `<@${BOT_ID}> remind me about something`,
      botId: BOT_ID,
    });

    await (
      adapter as unknown as {
        handleMentionMessage: (
          m: typeof message,
          botId: string,
        ) => Promise<void>;
      }
    ).handleMentionMessage(message, BOT_ID);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({ message: "remind me about something" }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });
});

// ---------------------------------------------------------------------------
// handleMentionMessage — empty content triggers short reply
// ---------------------------------------------------------------------------

describe("DiscordAdapter - mention with empty content", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("replies 'How can I help you?' when mention content is empty", async () => {
    const adapter = new DiscordAdapter();

    const message = makeGuildMessage({ content: "<@bot-id>" });
    message.content = "";

    await (
      adapter as unknown as {
        handleMentionMessage: (
          m: typeof message,
          botId: string,
        ) => Promise<void>;
      }
    ).handleMentionMessage(message, "bot-id");

    expect(message.reply).toHaveBeenCalledWith("How can I help you?");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleDMMessage — first-time welcome
// ---------------------------------------------------------------------------

describe("DiscordAdapter - DM welcome flow", () => {
  it("sends welcome embed only on the first DM from a user", async () => {
    const adapter = new DiscordAdapter();

    const sendDMWelcomeSpy = vi.spyOn(
      adapter as unknown as { sendDMWelcome: (m: unknown) => Promise<void> },
      "sendDMWelcome",
    );

    const message = {
      content: "Hey GAIA",
      author: { id: "new-user-id", bot: false },
      guild: null,
      channelId: "dm-channel",
      partial: false,
      channel: {
        send: vi.fn().mockResolvedValue({ edit: vi.fn() }),
        sendTyping: vi.fn().mockResolvedValue(undefined),
      },
    };

    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);

    expect(sendDMWelcomeSpy).toHaveBeenCalledOnce();

    // Second DM — welcome should NOT be sent again.
    vi.clearAllMocks();
    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);

    expect(sendDMWelcomeSpy).not.toHaveBeenCalled();
  });

  it("delegates non-empty DM content to postAndFollow", async () => {
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const message = {
      content: "What is the weather today?",
      author: { id: "user-dm", bot: false },
      guild: null,
      channelId: "dm-channel",
      partial: false,
      channel: {
        send: vi.fn().mockResolvedValue({ edit: vi.fn() }),
        sendTyping: vi.fn().mockResolvedValue(undefined),
      },
    };

    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        message: "What is the weather today?",
        platform: "discord",
        platformUserId: "user-dm",
      }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });

  it("replies 'How can I help you?' when DM content is blank", async () => {
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const send = vi.fn().mockResolvedValue({ edit: vi.fn() });
    const makeBlankMessage = () => ({
      content: "   ",
      author: { id: "blank-user", bot: false },
      guild: null,
      channelId: "dm-channel",
      partial: false,
      channel: { send, sendTyping: vi.fn() },
    });

    const handleDM = (m: ReturnType<typeof makeBlankMessage>) =>
      (
        adapter as unknown as {
          handleDMMessage: (mParam: typeof m) => Promise<void>;
        }
      ).handleDMMessage(m);

    // First blank DM also triggers the one-time welcome — consume it here so the
    // second call isolates the blank-content reply.
    await handleDM(makeBlankMessage());

    send.mockClear();
    await handleDM(makeBlankMessage());

    // On the repeat DM (welcome already sent) the only reply is the blank prompt.
    expect(send).toHaveBeenCalledWith("How can I help you?");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Context menu — empty message content
// ---------------------------------------------------------------------------

describe("DiscordAdapter - context menu interaction", () => {
  it("replies with no-text error when target message has no content", async () => {
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const interaction = {
      commandName: "Summarize with GAIA",
      targetMessage: { content: "   " },
      user: { id: "user-ctx" },
      channelId: "channel-ctx",
      replied: false,
      deferred: false,
      deferReply: vi.fn().mockResolvedValue(undefined),
      editReply: vi.fn().mockResolvedValue(undefined),
      isChatInputCommand: () => false,
      isMessageContextMenuCommand: () => true,
    };

    await (
      adapter as unknown as {
        handleContextMenuInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleContextMenuInteraction(interaction);

    expect(interaction.deferReply).toHaveBeenCalledWith({ flags: 64 });
    expect(interaction.editReply).toHaveBeenCalledWith({
      content: "That message has no text content to work with.",
    });
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  function makeContextMenuInteraction(commandName: string, content: string) {
    return {
      commandName,
      targetMessage: { content, id: "target-msg-by-someone-else" },
      user: { id: "user-ctx" },
      channelId: "channel-ctx",
      replied: false,
      deferred: false,
      deferReply: vi.fn().mockResolvedValue(undefined),
      editReply: vi.fn().mockResolvedValue(undefined),
      isChatInputCommand: () => false,
      isMessageContextMenuCommand: () => true,
    };
  }

  it("posts 'Summarize with GAIA' with non-empty content", async () => {
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const interaction = makeContextMenuInteraction(
      "Summarize with GAIA",
      "This is a long message that needs summarizing.",
    );

    await (
      adapter as unknown as {
        handleContextMenuInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleContextMenuInteraction(interaction);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        message: expect.stringContaining("Summarize the following message"),
        platform: "discord",
      }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });

  it("never records the target message as the user's own message", async () => {
    // A later background reaction anchors to the stored id; the target is often
    // someone else's message, and the turn's user message is GAIA's own prompt.
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const interaction = makeContextMenuInteraction("Add as Todo", "buy milk");

    await (
      adapter as unknown as {
        handleContextMenuInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleContextMenuInteraction(interaction);

    const request = postAndFollowSpy.mock.calls[0][0];
    expect(request).not.toHaveProperty("platformMessageId");
  });

  it("posts 'Add as Todo' with non-empty content", async () => {
    vi.clearAllMocks();
    const adapter = new DiscordAdapter();

    const interaction = makeContextMenuInteraction(
      "Add as Todo",
      "Call the dentist on Friday",
    );

    await (
      adapter as unknown as {
        handleContextMenuInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleContextMenuInteraction(interaction);

    expect(postAndFollowSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        message: expect.stringContaining("Add this as a todo item"),
        platform: "discord",
      }),
      expect.objectContaining({ send: expect.any(Function) }),
      expect.any(Function),
    );
  });
});

// ---------------------------------------------------------------------------
// getClient()
// ---------------------------------------------------------------------------

describe("DiscordAdapter - getClient()", () => {
  it("exposes the internal Client via getClient()", () => {
    const adapter = new DiscordAdapter();
    // client is initialised lazily inside initialize(), which requires a token.
    // We verify the method exists and returns whatever was injected.
    const fakeClient = { fake: true };
    (adapter as unknown as { client: unknown }).client = fakeClient;
    expect(adapter.getClient()).toBe(fakeClient);
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — unknown command
// ---------------------------------------------------------------------------

describe("DiscordAdapter - dispatchCommand unknown command", () => {
  it("sends ephemeral error when command is not registered", async () => {
    const adapter = new DiscordAdapter();

    const target = {
      platform: "discord" as const,
      userId: "user-123",
      channelId: "channel-abc",
      send: vi.fn(),
      sendEphemeral: vi.fn().mockResolvedValue({ id: "x", edit: vi.fn() }),
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    await (
      adapter as unknown as {
        dispatchCommand: (
          name: string,
          targetParam: typeof target,
        ) => Promise<void>;
      }
    ).dispatchCommand("nonexistent", target);

    expect(target.sendEphemeral).toHaveBeenCalledWith(
      "Unknown command: /nonexistent",
    );
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — forwards all args to BaseBotAdapter correctly
// ---------------------------------------------------------------------------

describe("DiscordAdapter - dispatchCommand args forwarding", () => {
  it("forwards name, target, and args to BaseBotAdapter.dispatchCommand", async () => {
    const adapter = new DiscordAdapter();

    // Spy on the prototype method so we assert on the real dispatch being invoked.
    const dispatchSpy = vi
      .spyOn(
        Object.getPrototypeOf(Object.getPrototypeOf(adapter)) as {
          dispatchCommand: (
            name: string,
            target: unknown,
            args: Record<string, unknown>,
            rawText?: string,
          ) => Promise<void>;
        },
        "dispatchCommand",
      )
      .mockResolvedValue(undefined);

    const target = {
      platform: "discord" as const,
      userId: "user-999",
      channelId: "channel-xyz",
      send: vi.fn(),
      sendEphemeral: vi.fn().mockResolvedValue({ id: "x", edit: vi.fn() }),
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    const args = { task: "Buy milk", count: 3 };

    await (
      adapter as unknown as {
        dispatchCommand: (
          name: string,
          targetParam: typeof target,
          argsParam: typeof args,
        ) => Promise<void>;
      }
    ).dispatchCommand("todo", target, args);

    expect(dispatchSpy).toHaveBeenCalledWith("todo", target, args);

    dispatchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — error propagation from BaseBotAdapter
// ---------------------------------------------------------------------------

describe("DiscordAdapter - dispatchCommand error propagation", () => {
  it("propagates rejection when BaseBotAdapter.dispatchCommand rejects", async () => {
    const adapter = new DiscordAdapter();

    const boom = new Error("dispatch failed");

    const dispatchSpy = vi
      .spyOn(
        Object.getPrototypeOf(Object.getPrototypeOf(adapter)) as {
          dispatchCommand: (
            name: string,
            target: unknown,
            args: Record<string, unknown>,
          ) => Promise<void>;
        },
        "dispatchCommand",
      )
      .mockRejectedValue(boom);

    const target = {
      platform: "discord" as const,
      userId: "user-123",
      channelId: "channel-abc",
      send: vi.fn(),
      sendEphemeral: vi.fn().mockResolvedValue({ id: "x", edit: vi.fn() }),
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    await expect(
      (
        adapter as unknown as {
          dispatchCommand: (
            name: string,
            targetParam: typeof target,
            args: Record<string, unknown>,
          ) => Promise<void>;
        }
      ).dispatchCommand("todo", target, {}),
    ).rejects.toThrow("dispatch failed");

    dispatchSpy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// buildContext — constructs expected shape
// ---------------------------------------------------------------------------

describe("DiscordAdapter - buildContext", () => {
  it("constructs a context with platform, platformUserId, channelId, and profile", () => {
    const adapter = new DiscordAdapter();

    const ctx = (
      adapter as unknown as {
        buildContext: (
          userId: string,
          channelId?: string,
          profile?: { username?: string; displayName?: string },
        ) => {
          platform: string;
          platformUserId: string;
          channelId: string | undefined;
          profile: { username?: string; displayName?: string } | undefined;
        };
      }
    ).buildContext("user-42", "channel-99", {
      username: "tester",
      displayName: "Tester Display",
    });

    expect(ctx).toEqual({
      platform: "discord",
      platformUserId: "user-42",
      channelId: "channel-99",
      profile: { username: "tester", displayName: "Tester Display" },
    });
  });

  it("omits channelId and profile when not provided", () => {
    const adapter = new DiscordAdapter();

    const ctx = (
      adapter as unknown as {
        buildContext: (userId: string) => {
          platform: string;
          platformUserId: string;
          channelId: string | undefined;
          profile: unknown;
        };
      }
    ).buildContext("user-solo");

    expect(ctx.platform).toBe("discord");
    expect(ctx.platformUserId).toBe("user-solo");
    expect(ctx.channelId).toBeUndefined();
    expect(ctx.profile).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// deliverOutbound — channel vs DM routing (backend-originated proactive sends)
// ---------------------------------------------------------------------------

describe("DiscordAdapter - deliverOutbound channel routing", () => {
  type Deliverer = {
    deliverOutbound: (
      destinationId: string,
      text: string,
      isChannel: boolean,
    ) => Promise<void>;
    client: unknown;
  };

  it("sends to the channel via channels.fetch when isChannel", async () => {
    const adapter = new DiscordAdapter() as unknown as Deliverer;
    const channelSend = vi.fn().mockResolvedValue(undefined);
    const userSend = vi.fn().mockResolvedValue(undefined);
    const client = {
      channels: {
        fetch: vi
          .fn()
          .mockResolvedValue({ isTextBased: () => true, send: channelSend }),
      },
      users: { fetch: vi.fn().mockResolvedValue({ send: userSend }) },
    };
    adapter.client = client;

    await adapter.deliverOutbound("chan-1", "hi", true);

    expect(client.channels.fetch).toHaveBeenCalledWith("chan-1");
    expect(channelSend).toHaveBeenCalledWith("hi");
    expect(client.users.fetch).not.toHaveBeenCalled();
  });

  it("throws when the channel is not a sendable text channel", async () => {
    const adapter = new DiscordAdapter() as unknown as Deliverer;
    const client = {
      channels: {
        fetch: vi.fn().mockResolvedValue({ isTextBased: () => false }),
      },
      users: { fetch: vi.fn() },
    };
    adapter.client = client;

    await expect(adapter.deliverOutbound("chan-1", "hi", true)).rejects.toThrow(
      /not a sendable text channel/,
    );
  });

  it("DMs the user via users.fetch when not a channel", async () => {
    const adapter = new DiscordAdapter() as unknown as Deliverer;
    const userSend = vi.fn().mockResolvedValue(undefined);
    const client = {
      channels: { fetch: vi.fn() },
      users: { fetch: vi.fn().mockResolvedValue({ send: userSend }) },
    };
    adapter.client = client;

    await adapter.deliverOutbound("user-1", "hi", false);

    expect(client.users.fetch).toHaveBeenCalledWith("user-1");
    expect(userSend).toHaveBeenCalledWith("hi");
    expect(client.channels.fetch).not.toHaveBeenCalled();
  });
});

describe("DiscordAdapter - sendOutboundFile channel routing", () => {
  type FileDeliverer = {
    sendOutboundFile: (
      destinationId: string,
      file: OutboundFile,
      isChannel: boolean,
    ) => Promise<void>;
    client: unknown;
  };

  const shot: OutboundFile = {
    data: Buffer.from("png"),
    mime: "image/png",
    filename: "browser-step-1.png",
    caption: "Step 1",
  };

  function makeAdapter() {
    const adapter = new DiscordAdapter() as unknown as FileDeliverer;
    const channelSend = vi.fn().mockResolvedValue(undefined);
    const userSend = vi.fn().mockResolvedValue(undefined);
    const client = {
      channels: {
        fetch: vi
          .fn()
          .mockResolvedValue({ isTextBased: () => true, send: channelSend }),
      },
      users: { fetch: vi.fn().mockResolvedValue({ send: userSend }) },
    };
    adapter.client = client;
    return { adapter, client, channelSend, userSend };
  }

  it("posts a group's photo into the channel, never a DM", async () => {
    const { adapter, client, channelSend } = makeAdapter();

    await adapter.sendOutboundFile("chan-1", shot, true);

    expect(client.channels.fetch).toHaveBeenCalledWith("chan-1");
    expect(channelSend).toHaveBeenCalledWith(
      expect.objectContaining({ content: "Step 1" }),
    );
    expect(client.users.fetch).not.toHaveBeenCalled();
  });

  it("DMs a photo to the user when not a channel", async () => {
    const { adapter, client, userSend } = makeAdapter();

    await adapter.sendOutboundFile("user-1", shot, false);

    expect(client.users.fetch).toHaveBeenCalledWith("user-1");
    expect(userSend).toHaveBeenCalledWith(
      expect.objectContaining({ content: "Step 1" }),
    );
    expect(client.channels.fetch).not.toHaveBeenCalled();
  });

  it("throws when the channel a photo is for is not a sendable text channel", async () => {
    const { adapter, client } = makeAdapter();
    client.channels.fetch.mockResolvedValueOnce({ isTextBased: () => false });

    await expect(
      adapter.sendOutboundFile("voice-1", shot, true),
    ).rejects.toThrow("not a sendable text channel");
  });
});

// ---------------------------------------------------------------------------
// client errors — an unhandled 'error' event would crash the process
// ---------------------------------------------------------------------------

describe("DiscordAdapter - client errors", () => {
  it("records a client error as a failed bot_runtime_error with its reason", async () => {
    const adapter = new DiscordAdapter();
    const client = { on: vi.fn(), once: vi.fn() };
    (adapter as unknown as { client: typeof client }).client = client;
    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();
    const listener = client.on.mock.calls.find(
      ([event]) => event === "error",
    )?.[1] as ((error: Error) => void) | undefined;
    expect(listener).toBeDefined();

    const events = await captureBotEvents("bot_runtime_error", async () => {
      listener?.(new Error("read ECONNRESET"));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      platform: "discord",
      outcome: "failed",
      reason: "backend_unreachable",
    });
  });
});

// ---------------------------------------------------------------------------
// reactToMessage — the native reaction primitive, and the live turns using it
// ---------------------------------------------------------------------------

type DiscordReactor = {
  reactToMessage: (
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
    replaces: string | null,
  ) => Promise<ReactionOutcome>;
  client: unknown;
};

describe("DiscordAdapter - reactToMessage", () => {
  function makeReactor(channel: unknown, user: unknown) {
    const adapter = new DiscordAdapter() as unknown as DiscordReactor;
    adapter.client = {
      channels: { fetch: vi.fn().mockResolvedValue(channel) },
      users: { fetch: vi.fn().mockResolvedValue(user) },
    };
    return adapter;
  }

  it("reacts to the target message in a channel", async () => {
    const react = vi.fn().mockResolvedValue(undefined);
    const fetchMessage = vi.fn().mockResolvedValue({ react });
    const adapter = makeReactor(
      { isTextBased: () => true, messages: { fetch: fetchMessage } },
      {},
    );

    const attached = await adapter.reactToMessage(
      "chan-1",
      "msg-7",
      "👍",
      true,
      null,
    );

    expect(attached).toBe("attached");
    expect(fetchMessage).toHaveBeenCalledWith("msg-7");
    expect(react).toHaveBeenCalledWith("👍");
  });

  it("takes GAIA's earlier reaction off before adding the new one", async () => {
    const order: string[] = [];
    const remove = vi.fn(async () => {
      order.push("remove 🔎");
    });
    const react = vi.fn(async (emoji: string) => {
      order.push(`add ${emoji}`);
    });
    const resolve = vi.fn((emoji: string) =>
      emoji === "🔎" ? { users: { remove } } : null,
    );
    const fetchMessage = vi
      .fn()
      .mockResolvedValue({ react, reactions: { resolve } });
    const adapter = makeReactor(
      { isTextBased: () => true, messages: { fetch: fetchMessage } },
      {},
    );

    const attached = await adapter.reactToMessage(
      "chan-1",
      "msg-7",
      "👍",
      true,
      "🔎",
    );

    expect(attached).toBe("attached");
    expect(order).toEqual(["remove 🔎", "add 👍"]);
    expect(remove).toHaveBeenCalledWith();
  });

  it("reacts via the user's DM channel when not a channel", async () => {
    const react = vi.fn().mockResolvedValue(undefined);
    const dmChannel = {
      isTextBased: () => true,
      messages: { fetch: vi.fn().mockResolvedValue({ react }) },
    };
    const adapter = makeReactor(null, {
      createDM: vi.fn().mockResolvedValue(dmChannel),
    });

    const attached = await adapter.reactToMessage(
      "user-1",
      "msg-7",
      "👍",
      false,
      null,
    );

    expect(attached).toBe("attached");
    expect(react).toHaveBeenCalledWith("👍");
  });

  it("refuses without sending anything when the target cannot be fetched", async () => {
    const send = vi.fn().mockResolvedValue(undefined);
    const adapter = makeReactor(
      {
        isTextBased: () => true,
        messages: {
          fetch: vi.fn().mockRejectedValue(new Error("Unknown Message")),
        },
        send,
      },
      {},
    );

    const attached = await adapter.reactToMessage(
      "chan-1",
      "msg-7",
      "👍",
      true,
      null,
    );

    expect(attached).toBe("attach_failed");
    expect(send).not.toHaveBeenCalled();
  });
});

describe("DiscordAdapter - live turn reactions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function spyReact(adapter: DiscordAdapter) {
    return vi
      .spyOn(adapter as unknown as DiscordReactor, "reactToMessage")
      .mockResolvedValue("attached");
  }

  it("reacts to a guild mention in its channel", async () => {
    const adapter = new DiscordAdapter();
    const react = spyReact(adapter);
    const message = { ...makeGuildMessage({}), id: "msg-in" };

    await (
      adapter as unknown as {
        handleMentionMessage: (m: typeof message, b: string) => Promise<void>;
      }
    ).handleMentionMessage(message, "bot-id");

    await expect(lastSurface().react("msg-in", "👍", null)).resolves.toBe(
      "attached",
    );
    expect(react).toHaveBeenCalledWith(
      "channel-abc",
      "msg-in",
      "👍",
      true,
      null,
    );
  });

  it("reacts to a DM through the author's DM channel", async () => {
    const adapter = new DiscordAdapter();
    const react = spyReact(adapter);
    const message = makeDmMessage("thanks!");

    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);

    await expect(lastSurface().react("dm-msg", "👍", "🔎")).resolves.toBe(
      "attached",
    );
    expect(react).toHaveBeenCalledWith("user-dm", "dm-msg", "👍", false, "🔎");
  });
});

/** A DM Message mock whose channel send resolves to an editable message. */
function makeDmMessage(content: string) {
  const sentEdit = vi.fn().mockResolvedValue(undefined);
  return {
    id: "dm-msg",
    content,
    author: { id: "user-dm", bot: false },
    guild: null,
    channelId: "dm-channel",
    partial: false,
    sentEdit,
    channel: {
      send: vi.fn().mockResolvedValue({ edit: sentEdit }),
      sendTyping: vi.fn().mockResolvedValue(undefined),
    },
  };
}

describe("DiscordAdapter - channel surface", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function followDm(content: string) {
    const adapter = new DiscordAdapter();
    const message = makeDmMessage(content);
    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);
    message.channel.send.mockClear();
    return message;
  }

  it("posts the DM with the user's message id so the reply can quote it", async () => {
    await followDm("hello");

    expect(postAndFollowSpy.mock.calls[0][0]).toMatchObject({
      message: "hello",
      isDm: true,
      platformMessageId: "dm-msg",
    });
  });

  it("answers a quoted message natively without failing when it is gone", async () => {
    const message = await followDm("hello");

    await lastSurface().send("the answer", "123");

    expect(message.channel.send).toHaveBeenCalledExactlyOnceWith({
      content: "the answer",
      reply: { messageReference: "123", failIfNotExists: false },
    });
  });

  it("sends an unquoted message without a reply reference", async () => {
    const message = await followDm("hello");

    await lastSurface().send("the answer", null);

    expect(message.channel.send).toHaveBeenCalledExactlyOnceWith({
      content: "the answer",
    });
  });

  it("edits the message it sent", async () => {
    const message = await followDm("hello");

    const sent = await lastSurface().send("draft", null);
    await sent.edit("final");

    expect(message.sentEdit).toHaveBeenCalledWith("final");
  });

  it("starts the typing indicator in the channel", async () => {
    const message = await followDm("hello");
    message.channel.sendTyping.mockClear();

    lastSurface().startTyping();

    expect(message.channel.sendTyping).toHaveBeenCalledOnce();
  });

  it("sends the auth link into the DM when the account is not linked", async () => {
    const message = await followDm("hello");

    await lastAuthHandler()("https://gaia.test/link");

    expect(message.channel.send).toHaveBeenCalledExactlyOnceWith(
      expect.stringContaining("https://gaia.test/link"),
    );
  });

  it("tells the user the post failed when postAndFollow throws", async () => {
    postAndFollowSpy.mockRejectedValueOnce(new Error("refused"));
    const adapter = new DiscordAdapter();
    const message = makeDmMessage("hello");

    await (
      adapter as unknown as {
        handleDMMessage: (m: typeof message) => Promise<void>;
      }
    ).handleDMMessage(message);

    expect(message.channel.send).toHaveBeenCalledWith("Error: refused");
  });
});

describe("DiscordAdapter - mention auth prompt", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  async function followMention(authorSend: ReturnType<typeof vi.fn>) {
    const adapter = new DiscordAdapter();
    const message = {
      ...makeGuildMessage({ content: "<@bot-id> hi" }),
      id: "msg-in",
      author: { id: "user-123", bot: false, send: authorSend },
    };
    await (
      adapter as unknown as {
        handleMentionMessage: (m: typeof message, b: string) => Promise<void>;
      }
    ).handleMentionMessage(message, "bot-id");
    return message;
  }

  it("DMs the link and points the channel at the DMs", async () => {
    const authorSend = vi.fn().mockResolvedValue(undefined);
    const message = await followMention(authorSend);

    await lastAuthHandler()("https://gaia.test/link");

    expect(authorSend).toHaveBeenCalledWith(
      expect.stringContaining("https://gaia.test/link"),
    );
    expect(message.reply).toHaveBeenCalledWith(
      "To use GAIA here, please link your account. Check your DMs for the link.",
    );
  });

  it("asks the user to open their DMs when the DM is refused", async () => {
    const authorSend = vi.fn().mockRejectedValue(new Error("DMs closed"));
    const message = await followMention(authorSend);

    await lastAuthHandler()("https://gaia.test/link");

    expect(message.reply).toHaveBeenCalledWith(
      "To use GAIA here, please link your account. Enable DMs from server members and try again, or use /auth in a private message.",
    );
  });
});

describe("DiscordAdapter - interaction surface", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function makeFollowUps() {
    const followUpEdit = vi.fn().mockResolvedValue(undefined);
    const followUp = vi.fn().mockResolvedValue({ edit: followUpEdit });
    return { followUp, followUpEdit };
  }

  async function followGaia(userSend: ReturnType<typeof vi.fn>) {
    const adapter = new DiscordAdapter();
    const base = makeChatInteraction({
      commandName: "gaia",
      optionString: "hi",
    });
    const { followUp, followUpEdit } = makeFollowUps();
    const interaction = {
      ...base,
      followUp,
      user: { ...base.user, send: userSend },
    };
    await (
      adapter as unknown as {
        handleInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleInteraction(interaction);
    return { interaction, followUpEdit };
  }

  it("fills the deferred /gaia reply first, then sends follow-ups", async () => {
    const { interaction, followUpEdit } = await followGaia(vi.fn());

    const first = await lastSurface().send("first", null);
    await first.edit("first, edited");
    const second = await lastSurface().send("second", null);
    await second.edit("second, edited");

    expect(interaction.editReply.mock.calls).toEqual([
      [{ content: "first" }],
      [{ content: "first, edited" }],
    ]);
    expect(interaction.followUp).toHaveBeenCalledExactlyOnceWith({
      content: "second",
    });
    expect(followUpEdit).toHaveBeenCalledWith({ content: "second, edited" });
  });

  it("sends every bubble as a follow-up under a context-menu header", async () => {
    const adapter = new DiscordAdapter();
    const { followUp } = makeFollowUps();
    const interaction = {
      commandName: "Summarize with GAIA",
      targetMessage: { content: "a long message", id: "target" },
      user: { id: "user-ctx" },
      channelId: "channel-ctx",
      guild: { id: "guild-1" },
      deferReply: vi.fn().mockResolvedValue(undefined),
      editReply: vi.fn().mockResolvedValue(undefined),
      followUp,
    };
    await (
      adapter as unknown as {
        handleContextMenuInteraction: (i: typeof interaction) => Promise<void>;
      }
    ).handleContextMenuInteraction(interaction);

    await lastSurface().send("summary text", null);

    expect(interaction.editReply.mock.calls).toEqual([
      [{ content: "**Summary**" }],
    ]);
    expect(followUp).toHaveBeenCalledExactlyOnceWith({
      content: "summary text",
    });
    expect(postAndFollowSpy.mock.calls[0][0]).toMatchObject({ isDm: false });
  });

  it("DMs the /gaia auth link and says so in the public reply", async () => {
    const userSend = vi.fn().mockResolvedValue(undefined);
    const { interaction } = await followGaia(userSend);

    await lastAuthHandler()("https://gaia.test/link");

    expect(userSend).toHaveBeenCalledWith(
      expect.stringContaining("https://gaia.test/link"),
    );
    expect(interaction.editReply).toHaveBeenCalledWith({
      content:
        "To use GAIA, please authenticate first. Check your DMs for the link.",
    });
    expect(interaction.followUp).not.toHaveBeenCalled();
  });

  it("falls back to an ephemeral /gaia auth link when the DM is refused", async () => {
    const { interaction } = await followGaia(
      vi.fn().mockRejectedValue(new Error("DMs closed")),
    );

    await lastAuthHandler()("https://gaia.test/link");

    expect(interaction.followUp).toHaveBeenCalledWith({
      content: expect.stringContaining("https://gaia.test/link"),
      ephemeral: true,
    });
    expect(interaction.editReply).toHaveBeenCalledWith({
      content:
        "To use GAIA, please authenticate first. An ephemeral link has been sent above.",
    });
  });
});

describe("DiscordAdapter - arrival order", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts a DM whose welcome is slow before a second DM that arrived after it", async () => {
    const adapter = new DiscordAdapter();
    const on = vi.fn();
    (adapter as unknown as { client: unknown }).client = {
      once: vi.fn(),
      on,
      user: { id: "bot-user-id" },
    };
    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();
    const onMessage = on.mock.calls.find(
      ([event]) => event === "messageCreate",
    )?.[1] as (m: ReturnType<typeof makeDmMessage>) => Promise<void>;
    let finishWelcome: () => void = () => undefined;
    vi.spyOn(
      adapter as unknown as { sendDMWelcome: () => Promise<void> },
      "sendDMWelcome",
    ).mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishWelcome = resolve;
        }),
    );

    const first = onMessage(makeDmMessage("one"));
    const second = onMessage(makeDmMessage("two"));
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(postAndFollowSpy).not.toHaveBeenCalled();

    finishWelcome();
    await Promise.all([first, second]);
    expect(
      postAndFollowSpy.mock.calls.map(([request]) => request.message),
    ).toEqual(["one", "two"]);
  });
});
