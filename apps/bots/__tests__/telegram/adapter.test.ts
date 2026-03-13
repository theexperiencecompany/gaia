/**
 * Tests for the TelegramAdapter.
 *
 * The adapter constructor and boot() require a live Telegram bot token and
 * network access, so we test observable behaviors that don't need a live
 * connection by mocking grammy and @gaia/shared, then exercising the
 * adapter's private/protected methods directly via TypeScript casts.
 *
 * Covered behaviors:
 * 1. platform property returns "telegram"
 * 2. handleMentionMessage (registerEvents group path) strips @botUsername
 * 3. createCtxTarget.send — sends text to the correct chat_id
 * 4. createCtxTarget.sendRich — formats rich message via richMessageToMarkdown
 * 5. handleTelegramStreaming — sends "Thinking..." then delegates to handleStreamingChat
 * 6. handleTelegramStreaming — markdown fallback retries without parse_mode on rejection
 * 7. registerCommands — /todo command dispatches via dispatchCommand
 * 8. dispatchCommand — unknown command sends ephemeral error
 * 9. registerGaiaCommand — empty /gaia message sends usage hint
 * 10. handleTelegramStreaming — unknown/unauthenticated chat (no chatId) returns early
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// Mock grammy before importing the adapter so the module sees the mocks.
// ---------------------------------------------------------------------------

const mockBotOn = vi.fn();
const mockBotCommand = vi.fn();
const mockBotCatch = vi.fn();
const mockBotStart = vi.fn();
const mockBotStop = vi.fn().mockResolvedValue(undefined);
const mockSetMyCommands = vi.fn().mockResolvedValue(undefined);
const mockGetMe = vi.fn().mockResolvedValue({ username: "gaiabot" });

const mockBotInstance = {
  on: mockBotOn,
  command: mockBotCommand,
  catch: mockBotCatch,
  start: mockBotStart,
  stop: mockBotStop,
  api: {
    getMe: mockGetMe,
    setMyCommands: mockSetMyCommands,
    editMessageText: vi.fn().mockResolvedValue({}),
    sendMessage: vi.fn().mockResolvedValue({ message_id: 99 }),
    sendChatAction: vi.fn().mockResolvedValue({}),
  },
};

vi.mock("grammy", () => ({
  Bot: vi.fn().mockImplementation(() => mockBotInstance),
}));

vi.mock("@grammyjs/types", () => ({}));

// ---------------------------------------------------------------------------
// Mock @gaia/shared so we control handleStreamingChat and friends.
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared", () => {
  // formatBotError is defined before BaseBotAdapter so the stub's dispatchCommand
  // can call it for error recovery — mirroring the real BaseBotAdapter behavior.
  const formatBotErrorImpl = (err: unknown): string =>
    err instanceof Error ? `Error: ${err.message}` : "Something went wrong";

  const BaseBotAdapter = class {
    platform = "telegram";
    gaia = {};
    config = {};
    commands = new Map();

    protected async dispatchCommand(
      name: string,
      target: {
        sendEphemeral: (t: string) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
      },
      args: Record<string, string | number | boolean | undefined> = {},
      rawText?: string,
    ) {
      const cmd = (this.commands as Map<string, { execute: (p: unknown) => Promise<void> }>).get(name);
      if (!cmd) {
        await target.sendEphemeral(`Unknown command: /${name}`);
        return;
      }
      try {
        await cmd.execute({ gaia: this.gaia, target, ctx: {}, args, rawText });
      } catch (error) {
        const errMsg = formatBotErrorImpl(error);
        try {
          await target.sendEphemeral(errMsg);
        } catch {
          // Target may be expired
        }
      }
    }

    protected buildContext(userId: string, channelId?: string) {
      return { platform: this.platform, platformUserId: userId, channelId };
    }
  };

  return {
    BaseBotAdapter,
    formatBotError: vi.fn((err: unknown) =>
      err instanceof Error ? `Error: ${err.message}` : "Something went wrong",
    ),
    handleStreamingChat: vi.fn().mockResolvedValue(undefined),
    STREAMING_DEFAULTS: {
      telegram: { editIntervalMs: 1200, streaming: false, platform: "telegram" },
    },
    convertToTelegramMarkdown: vi.fn((t: string) => t),
    richMessageToMarkdown: vi.fn().mockReturnValue("**GAIA Settings**\nYour settings"),
    parseTextArgs: vi.fn((text: string) => ({
      subcommand: text.split(" ")[0] || undefined,
    })),
  };
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import { TelegramAdapter } from "../../telegram/src/adapter";
import {
  handleStreamingChat,
  convertToTelegramMarkdown,
  richMessageToMarkdown,
} from "@gaia/shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Builds a minimal grammy Context mock.
 * chat.type defaults to "private" unless overridden.
 */
function makeCtx(overrides: {
  chatId?: number;
  chatType?: "private" | "group" | "supergroup";
  userId?: number;
  text?: string;
  match?: string;
  fromFirstName?: string;
  fromLastName?: string;
  fromUsername?: string;
  replyFn?: ReturnType<typeof vi.fn>;
  editMessageTextFn?: ReturnType<typeof vi.fn>;
  sendMessageFn?: ReturnType<typeof vi.fn>;
  sendChatActionFn?: ReturnType<typeof vi.fn>;
} = {}) {
  const {
    chatId = 123456,
    chatType = "private",
    userId = 999,
    text = "hello",
    match = "",
    fromFirstName = "Alice",
    fromLastName = undefined,
    fromUsername = "aliceuser",
    replyFn = vi.fn().mockResolvedValue({ message_id: 42 }),
    editMessageTextFn = vi.fn().mockResolvedValue({}),
    sendMessageFn = vi.fn().mockResolvedValue({ message_id: 55 }),
    sendChatActionFn = vi.fn().mockResolvedValue({}),
  } = overrides;

  return {
    chat: { id: chatId, type: chatType },
    from: {
      id: userId,
      first_name: fromFirstName,
      last_name: fromLastName,
      username: fromUsername,
    },
    message: { text, message_id: 10 },
    match,
    reply: replyFn,
    api: {
      editMessageText: editMessageTextFn,
      sendMessage: sendMessageFn,
      sendChatAction: sendChatActionFn,
    },
  };
}

/** Returns an adapter with bot internals pre-populated so initialize() is not needed. */
function makeAdapter(): TelegramAdapter {
  const adapter = new TelegramAdapter();
  // Inject the mock bot instance directly, bypassing initialize() which needs a real token.
  (adapter as unknown as { bot: typeof mockBotInstance }).bot = mockBotInstance;
  (adapter as unknown as { botUsername: string }).botUsername = "gaiabot";
  return adapter;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TelegramAdapter - platform identity", () => {
  it('reports platform as "telegram"', () => {
    const adapter = new TelegramAdapter();
    expect(adapter.platform).toBe("telegram");
  });
});

// ---------------------------------------------------------------------------
// handleMentionMessage — group @mention strips bot username
// ---------------------------------------------------------------------------

describe("TelegramAdapter - group mention message handling (registerEvents)", () => {
  let adapter: TelegramAdapter;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = makeAdapter();
    // Wire up the event handlers the same way boot() would.
    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("strips @botUsername from group message and streams the cleaned content", async () => {
    // Retrieve the handler registered via bot.on("message:text", ...)
    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: ReturnType<typeof makeCtx>) => Promise<void>) | undefined;

    expect(onHandler).toBeDefined();

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "@gaiabot what should I do today?",
      replyFn,
    });

    await onHandler!(ctx);

    // handleStreamingChat must be called with the mention stripped
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(), // gaia client
      expect.objectContaining({
        message: "what should I do today?",
        platform: "telegram",
        platformUserId: "999",
        channelId: "123456",
      }),
      expect.any(Function), // editMessage callback
      expect.any(Function), // sendNewMessage callback
      expect.any(Function), // onAuthError callback
      expect.any(Function), // onGenericError callback
      expect.objectContaining({ platform: "telegram" }),
    );
  });

  it("replies 'How can I help you?' when mention text is empty after stripping", async () => {
    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: ReturnType<typeof makeCtx>) => Promise<void>) | undefined;

    expect(onHandler).toBeDefined();

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "@gaiabot",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expect(replyFn).toHaveBeenCalledWith("How can I help you?");
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("ignores group messages that do not mention the bot", async () => {
    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: ReturnType<typeof makeCtx>) => Promise<void>) | undefined;

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "this message does not mention anyone",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(replyFn).not.toHaveBeenCalled();
  });

  it("routes private chat messages directly to handleTelegramStreaming", async () => {
    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: ReturnType<typeof makeCtx>) => Promise<void>) | undefined;

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "plan my day",
      replyFn,
    });

    await onHandler!(ctx);

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "plan my day",
        platform: "telegram",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "telegram" }),
    );
  });

  it("skips messages that start with a command prefix '/'", async () => {
    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: ReturnType<typeof makeCtx>) => Promise<void>) | undefined;

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "/start",
      replyFn,
    });

    await onHandler!(ctx);

    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// createCtxTarget.send — sends text to correct chat_id
// ---------------------------------------------------------------------------

describe("TelegramAdapter - createCtxTarget.send", () => {
  let adapter: TelegramAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("sends converted text to the correct chat_id and returns a SentMessage", async () => {
    const sendMessageFn = vi.fn().mockResolvedValue({ message_id: 77 });
    const ctx = makeCtx({ chatId: 111, sendMessageFn });

    const target = (
      adapter as unknown as {
        createCtxTarget: (ctx: typeof ctx, userId: string) => {
          send: (text: string) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
          platform: string;
          userId: string;
          channelId?: string;
        };
      }
    ).createCtxTarget(ctx, "999");

    const sent = await target.send("Hello from GAIA");

    expect(convertToTelegramMarkdown).toHaveBeenCalledWith("Hello from GAIA");
    expect(sendMessageFn).toHaveBeenCalledWith(111, "Hello from GAIA", {
      parse_mode: "Markdown",
    });
    expect(sent.id).toBe("77");
  });

  it("falls back to plain send when Markdown parse fails", async () => {
    const sendMessageFn = vi
      .fn()
      .mockRejectedValueOnce(new Error("can't parse entities: stray bracket"))
      .mockResolvedValueOnce({ message_id: 88 });

    const ctx = makeCtx({ chatId: 111, sendMessageFn });

    const target = (
      adapter as unknown as {
        createCtxTarget: (ctx: typeof ctx, userId: string) => {
          send: (text: string) => Promise<{ id: string }>;
        };
      }
    ).createCtxTarget(ctx, "999");

    const sent = await target.send("bad *markup");

    // Second call must be without parse_mode
    expect(sendMessageFn).toHaveBeenCalledTimes(2);
    expect(sendMessageFn.mock.calls[1]).toEqual([111, "bad *markup"]);
    expect(sent.id).toBe("88");
  });

  it("exposes correct platform, userId, and channelId on target", () => {
    const ctx = makeCtx({ chatId: 42 });

    const target = (
      adapter as unknown as {
        createCtxTarget: (ctx: typeof ctx, userId: string) => {
          platform: string;
          userId: string;
          channelId?: string;
        };
      }
    ).createCtxTarget(ctx, "7777");

    expect(target.platform).toBe("telegram");
    expect(target.userId).toBe("7777");
    expect(target.channelId).toBe("42");
  });
});

// ---------------------------------------------------------------------------
// createCtxTarget.sendRich — formats message via richMessageToMarkdown
// ---------------------------------------------------------------------------

describe("TelegramAdapter - createCtxTarget.sendRich", () => {
  it("renders rich message to markdown and sends it via api.sendMessage", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const sendMessageFn = vi.fn().mockResolvedValue({ message_id: 200 });
    const ctx = makeCtx({ chatId: 555, chatType: "private", sendMessageFn });

    const target = (
      adapter as unknown as {
        createCtxTarget: (ctx: typeof ctx, userId: string) => {
          sendRich: (msg: object) => Promise<{ id: string }>;
        };
      }
    ).createCtxTarget(ctx, "1234");

    const richMsg = {
      type: "embed" as const,
      title: "GAIA Settings",
      description: "Your preferences",
      fields: [{ name: "Theme", value: "Dark", inline: false }],
    };

    const sent = await target.sendRich(richMsg);

    expect(richMessageToMarkdown).toHaveBeenCalledWith(richMsg, "telegram");
    // richMessageToMarkdown is mocked to return "**GAIA Settings**\nYour settings"
    expect(sendMessageFn).toHaveBeenCalledWith(
      555,
      "**GAIA Settings**\nYour settings",
      { parse_mode: "Markdown" },
    );
    expect(sent.id).toBe("200");
  });
});

// ---------------------------------------------------------------------------
// handleTelegramStreaming — sends "Thinking..." before streaming
// ---------------------------------------------------------------------------

describe("TelegramAdapter - handleTelegramStreaming (streaming setup)", () => {
  let adapter: TelegramAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("sends 'Thinking...' via ctx.reply before invoking handleStreamingChat", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ replyFn });

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "tell me a joke");

    expect(replyFn).toHaveBeenCalledWith("Thinking...");
    expect(handleStreamingChat).toHaveBeenCalled();
  });

  it("calls handleStreamingChat with the correct request shape", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 77777, replyFn });

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "555", "what is 2+2?");

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(), // gaia client
      expect.objectContaining({
        message: "what is 2+2?",
        platform: "telegram",
        platformUserId: "555",
        channelId: "77777",
      }),
      expect.any(Function), // editMessage callback
      expect.any(Function), // sendNewMessage callback
      expect.any(Function), // onAuthError callback
      expect.any(Function), // onGenericError callback
      expect.objectContaining({ platform: "telegram" }),
    );
  });

  it("returns early without doing anything when chat ID is missing", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });

    // Build a ctx where chat is undefined — adapter must not proceed
    const ctx = {
      chat: undefined,
      from: { id: 999, first_name: "Alice", last_name: undefined, username: "aliceuser" },
      message: { text: "hello", message_id: 10 },
      match: "",
      reply: replyFn,
      api: {
        editMessageText: vi.fn(),
        sendMessage: vi.fn(),
        sendChatAction: vi.fn(),
      },
    };

    await (
      adapter as unknown as {
        handleTelegramStreaming: (ctx: typeof ctx, userId: string, message: string) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx as unknown as ReturnType<typeof makeCtx>, "999", "hello");

    expect(replyFn).not.toHaveBeenCalled();
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Markdown fallback — the audit-required test: must fail if fallback logic breaks
// ---------------------------------------------------------------------------

describe("TelegramAdapter - markdown fallback retry (editMessage callback)", () => {
  let adapter: TelegramAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("retries editMessageText without parse_mode when Telegram rejects markdown", async () => {
    const editMessageTextFn = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("Bad Request: can't parse entities: Character '@' is reserved"),
      )
      .mockResolvedValueOnce({});

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 100, replyFn, editMessageTextFn });

    let capturedEditCallback:
      | ((text: string) => Promise<void>)
      | undefined;

    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, editMessage) => {
        capturedEditCallback = editMessage;
      },
    );

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "stream me something");

    expect(capturedEditCallback).toBeDefined();

    // Simulate streaming update with bad markdown
    await capturedEditCallback!("text with *bad markup @here");

    // First attempt: with parse_mode: "Markdown"
    expect(editMessageTextFn).toHaveBeenNthCalledWith(
      1,
      100,
      42,
      "text with *bad markup @here", // convertToTelegramMarkdown is mocked as identity
      { parse_mode: "Markdown" },
    );

    // Second attempt (fallback): without parse_mode
    expect(editMessageTextFn).toHaveBeenNthCalledWith(
      2,
      100,
      42,
      "text with *bad markup @here",
    );
  });

  it("does NOT retry for 'message is not modified' errors (returns silently)", async () => {
    const editMessageTextFn = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("Bad Request: message is not modified"),
      );

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 100, replyFn, editMessageTextFn });

    let capturedEditCallback:
      | ((text: string) => Promise<void>)
      | undefined;

    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, editMessage) => {
        capturedEditCallback = editMessage;
      },
    );

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "same content twice");

    await capturedEditCallback!("unchanged content");

    // Only one attempt — must not retry for "not modified"
    expect(editMessageTextFn).toHaveBeenCalledTimes(1);
  });

  it("markdown fallback also applies to sendNewMessage (reply with new message)", async () => {
    // The sendNewMessage callback attempts ctx.reply with parse_mode first.
    // If that throws "can't parse entities", it falls back to ctx.reply without options.
    //
    // Call sequence for replyFn:
    //   1st call: ctx.reply("Thinking...")  → succeeds (message_id: 42)
    //   2nd call: ctx.reply(converted, { parse_mode: "Markdown" }) → fails (parse error)
    //   3rd call: ctx.reply(text)           → succeeds (message_id: 99, fallback)
    const replyFn = vi
      .fn()
      .mockResolvedValueOnce({ message_id: 42 })          // Thinking...
      .mockRejectedValueOnce(
        new Error("Bad Request: can't parse entities in bold text"),
      )
      .mockResolvedValueOnce({ message_id: 99 });          // plain fallback

    const ctx = makeCtx({ chatId: 100, replyFn });

    let capturedSendNewMessage:
      | ((text: string) => Promise<((updated: string) => Promise<void>) | undefined>)
      | undefined;

    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, _edit, sendNewMessage) => {
        capturedSendNewMessage = sendNewMessage;
      },
    );

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "new content");

    expect(capturedSendNewMessage).toBeDefined();

    // Simulate a new streaming segment with broken markdown
    await capturedSendNewMessage!("*unclosed bold"); // NOSONAR — non-null assertion needed; variable typed as T | undefined

    // Total calls: Thinking... + markdown attempt + plain fallback = 3
    expect(replyFn).toHaveBeenCalledTimes(3);

    // The last reply call should be without parse_mode options (plain fallback)
    const lastCall = replyFn.mock.calls[replyFn.mock.calls.length - 1];
    expect(lastCall[0]).toBe("*unclosed bold");
    expect(lastCall[1]).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// registerCommands — command routing via dispatchCommand
// ---------------------------------------------------------------------------

describe("TelegramAdapter - registerCommands command routing", () => {
  let adapter: TelegramAdapter;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("routes /todo command through dispatchCommand with parsed subcommand", async () => {
    const todoExecute = vi.fn().mockResolvedValue(undefined);
    const todoCommand = {
      name: "todo",
      description: "Manage todos",
      options: [],
      execute: todoExecute,
    };
    (
      adapter as unknown as { commands: Map<string, unknown> }
    ).commands.set("todo", todoCommand);

    await (
      adapter as unknown as {
        registerCommands: (cmds: typeof todoCommand[]) => Promise<void>;
      }
    ).registerCommands([todoCommand]);

    // Find the handler registered for "todo"
    const todoCall = vi.mocked(mockBotCommand).mock.calls.find(
      (c) => c[0] === "todo",
    );
    expect(todoCall).toBeDefined();

    const todoHandler = todoCall![1] as (ctx: ReturnType<typeof makeCtx>) => Promise<void>;

    const ctx = makeCtx({ match: "list" });
    await todoHandler(ctx);

    // dispatchCommand should have been invoked with the command name
    expect(todoExecute).toHaveBeenCalledWith(
      expect.objectContaining({
        args: expect.objectContaining({ subcommand: "list" }),
      }),
    );
  });

  it("maps /start to the 'help' command handler", async () => {
    const helpExecute = vi.fn().mockResolvedValue(undefined);
    const helpCommand = {
      name: "help",
      description: "Get help",
      options: [],
      execute: helpExecute,
    };
    (
      adapter as unknown as { commands: Map<string, unknown> }
    ).commands.set("help", helpCommand);

    await (
      adapter as unknown as {
        registerCommands: (cmds: typeof helpCommand[]) => Promise<void>;
      }
    ).registerCommands([helpCommand]);

    const startCall = vi.mocked(mockBotCommand).mock.calls.find(
      (c) => c[0] === "start",
    );
    expect(startCall).toBeDefined();

    const startHandler = startCall![1] as (ctx: ReturnType<typeof makeCtx>) => Promise<void>;
    const ctx = makeCtx();
    await startHandler(ctx);

    expect(helpExecute).toHaveBeenCalled();
  });

  it("skips the 'gaia' command from the loop (routes to registerGaiaCommand)", async () => {
    const gaiaCommand = {
      name: "gaia",
      description: "Chat with GAIA",
      options: [],
      execute: vi.fn(),
    };

    await (
      adapter as unknown as {
        registerCommands: (cmds: typeof gaiaCommand[]) => Promise<void>;
      }
    ).registerCommands([gaiaCommand]);

    // 'gaia' should be registered via bot.command("gaia", ...) from registerGaiaCommand
    const gaiaCalls = vi.mocked(mockBotCommand).mock.calls.filter(
      (c) => c[0] === "gaia",
    );
    expect(gaiaCalls.length).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — error recovery: unknown command sends ephemeral error
// ---------------------------------------------------------------------------

describe("TelegramAdapter - dispatchCommand error recovery", () => {
  it("sends ephemeral error message when command is not registered", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const sendEphemeralFn = vi.fn().mockResolvedValue({ id: "x", edit: vi.fn() });
    const target = {
      platform: "telegram" as const,
      userId: "999",
      channelId: "123456",
      send: vi.fn(),
      sendEphemeral: sendEphemeralFn,
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    await (
      adapter as unknown as {
        dispatchCommand: (
          name: string,
          target: typeof target,
        ) => Promise<void>;
      }
    ).dispatchCommand("nonexistent", target);

    expect(sendEphemeralFn).toHaveBeenCalledWith("Unknown command: /nonexistent");
  });

  it("sends ephemeral error when a registered command throws", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const throwingCommand = {
      name: "broken",
      description: "Breaks on execute",
      options: [],
      execute: vi.fn().mockRejectedValue(new Error("something blew up")),
    };
    (
      adapter as unknown as { commands: Map<string, unknown> }
    ).commands.set("broken", throwingCommand);

    const sendEphemeralFn = vi.fn().mockResolvedValue({ id: "e", edit: vi.fn() });
    const target = {
      platform: "telegram" as const,
      userId: "999",
      channelId: "123456",
      send: vi.fn(),
      sendEphemeral: sendEphemeralFn,
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    await (
      adapter as unknown as {
        dispatchCommand: (
          name: string,
          target: typeof target,
        ) => Promise<void>;
      }
    ).dispatchCommand("broken", target);

    expect(sendEphemeralFn).toHaveBeenCalledWith(
      expect.stringContaining("something blew up"),
    );
  });
});

// ---------------------------------------------------------------------------
// registerGaiaCommand — empty /gaia sends usage hint
// ---------------------------------------------------------------------------

describe("TelegramAdapter - /gaia command", () => {
  let adapter: TelegramAdapter;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = makeAdapter();

    // registerGaiaCommand is private; trigger it by registering a gaia command.
    await (
      adapter as unknown as {
        registerCommands: (cmds: { name: string; description: string; options: unknown[]; execute: ReturnType<typeof vi.fn> }[]) => Promise<void>;
      }
    ).registerCommands([
      { name: "gaia", description: "Chat with GAIA", options: [], execute: vi.fn() },
    ]);
  });

  it("sends 'Usage: /gaia <your message>' when invoked with no text", async () => {
    const gaiaCall = vi.mocked(mockBotCommand).mock.calls.find(
      (c) => c[0] === "gaia",
    );
    expect(gaiaCall).toBeDefined();

    const gaiaHandler = gaiaCall![1] as (ctx: ReturnType<typeof makeCtx>) => Promise<void>;
    const replyFn = vi.fn().mockResolvedValue({ message_id: 10 });
    const ctx = makeCtx({ match: "", replyFn });

    await gaiaHandler(ctx);

    expect(replyFn).toHaveBeenCalledWith("Usage: /gaia <your message>");
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("streams when /gaia is invoked with a message", async () => {
    const gaiaCall = vi.mocked(mockBotCommand).mock.calls.find(
      (c) => c[0] === "gaia",
    );
    const gaiaHandler = gaiaCall![1] as (ctx: ReturnType<typeof makeCtx>) => Promise<void>;
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ match: "remind me to call dentist", replyFn });

    await gaiaHandler(ctx);

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "remind me to call dentist",
        platform: "telegram",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "telegram" }),
    );
  });
});

// ---------------------------------------------------------------------------
// Unauthenticated / unknown chat edge case
// ---------------------------------------------------------------------------

describe("TelegramAdapter - unauthenticated / unknown chat handling", () => {
  it("skips event handler when ctx.from is missing (no userId)", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();

    const onHandler = vi.mocked(mockBotOn).mock.calls.find(
      (c) => c[0] === "message:text",
    )?.[1] as ((ctx: unknown) => Promise<void>) | undefined;

    expect(onHandler).toBeDefined();

    const ctx = {
      chat: { id: 123, type: "private" },
      from: undefined, // no user info
      message: { text: "hello", message_id: 1 },
      match: "",
      reply: vi.fn(),
      api: {
        editMessageText: vi.fn(),
        sendMessage: vi.fn(),
        sendChatAction: vi.fn(),
      },
    };

    await onHandler!(ctx);

    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("onAuthError callback sends auth URL via DM in private chat", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const editMessageTextFn = vi.fn().mockResolvedValue({});
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 500, chatType: "private", replyFn, editMessageTextFn });

    let capturedAuthError: ((authUrl: string) => Promise<void>) | undefined;

    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, _edit, _send, onAuthError) => {
        capturedAuthError = onAuthError;
      },
    );

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "do something");

    expect(capturedAuthError).toBeDefined();

    await capturedAuthError!("https://gaia.example.com/auth?token=abc");

    // In a private chat, auth URL goes directly into the chat via editMessageText
    expect(editMessageTextFn).toHaveBeenCalledWith(
      500,
      42,
      expect.stringContaining("https://gaia.example.com/auth?token=abc"),
    );
  });

  it("onGenericError callback edits the loading message with the error text", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const editMessageTextFn = vi.fn().mockResolvedValue({});
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 600, chatType: "private", replyFn, editMessageTextFn });

    let capturedGenericError: ((errMsg: string) => Promise<void>) | undefined;

    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, _edit, _send, _auth, onGenericError) => {
        capturedGenericError = onGenericError;
      },
    );

    await (
      adapter as unknown as {
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", "do something");

    expect(capturedGenericError).toBeDefined();

    await capturedGenericError!("Something went wrong on our end.");

    expect(editMessageTextFn).toHaveBeenCalledWith(
      600,
      42,
      "Something went wrong on our end.",
    );
  });
});
