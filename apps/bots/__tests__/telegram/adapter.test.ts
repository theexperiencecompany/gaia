/**
 * Tests for the TelegramAdapter.
 *
 * The adapter constructor and boot() require a live Telegram bot token and
 * network access, so we test observable behaviors that don't need a live
 * connection by mocking grammy and @gaia/shared, then exercising the
 * adapter's private/protected methods directly via TypeScript casts.
 *
 * The assertions target observable behavior — the message text/args sent, the
 * parse_mode used, the file ids/data forwarded — not which internal method ran.
 *
 * Covered behaviors:
 * 1. platform property returns "telegram"
 * 2. group @mention path strips @botUsername and streams the cleaned content
 * 3. createCtxTarget.send — sends HTML text to the correct chat_id
 * 4. createCtxTarget.sendRich — formats rich message via richMessageToMarkdown
 * 5. handleTelegramStreaming — sends "Thinking..." then delegates to handleStreamingChat
 * 6. HTML fallback — edits/sends retry as plain text when Telegram rejects HTML
 * 7. registerCommands — a slash command dispatches with the parsed subcommand args
 * 8. dispatchCommand — unknown command sends ephemeral error
 * 9. registerGaiaCommand — empty /gaia message sends usage hint
 * 10. extractTelegramMedia — pure mapping of grammY messages to media descriptors
 * 11. media routing — resolved "chat" outcome streams with attachments, "reply"
 *     outcome posts the plain reply
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
// Mock @gaia/shared via the shared factory. The factory's BaseBotAdapter stub
// supplies shouldSendWelcome / startTypingIndicator / resolveIncomingMedia and
// the common helpers; we layer the Telegram-specific exports the adapter pulls
// in (the HTML converter chokepoint, htmlToPlainText fallback, media helpers,
// extractSubcommandArgs) on top via `converters` — these are spread last into
// the returned module, so we never touch the shared mock file.
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  return makeGaiaSharedMock("telegram", {
    streamingDefaults: {
      telegram: {
        editIntervalMs: 1000,
        streaming: true,
        platform: "telegram",
      },
    },
    defaultRichMarkdown: "**GAIA Settings**\nYour settings",
    converters: {
      // renderForPlatform is the shared non-streaming chokepoint; identity here
      // so the adapter's wiring (chat_id, parse_mode) is what we assert. The
      // real conversion is covered by mention.test.ts against the live function.
      renderForPlatform: vi.fn((text: string) => text),
      // htmlToPlainText is the fallback the adapter sends when Telegram rejects
      // HTML markup. Mirror the real strip so plain-text fallback assertions are
      // meaningful (tags removed, entities decoded).
      htmlToPlainText: vi.fn((html: string) =>
        html
          .replaceAll(/<[^>]+>/g, "")
          .replaceAll(/&lt;/g, "<")
          .replaceAll(/&gt;/g, ">")
          .replaceAll(/&quot;/g, '"')
          .replaceAll(/&amp;/g, "&"),
      ),
      extractSubcommandArgs: vi.fn(
        (commandName: string, rawText: string | undefined) =>
          commandName === "todo" || commandName === "workflow"
            ? { subcommand: (rawText ?? "").trim().split(/\s+/)[0] || "list" }
            : {},
      ),
      friendlyMediaError: vi.fn(
        (kind: string) => `Could not process your ${kind}.`,
      ),
      unsupportedMediaMessage: vi.fn(
        (kind: string) => `I can't process ${kind} yet.`,
      ),
    },
  });
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import {
  handleStreamingChat,
  renderForPlatform,
  richMessageToMarkdown,
} from "@gaia/shared";
import type { Message } from "@grammyjs/types";
import {
  extractTelegramMedia,
  TelegramAdapter,
} from "../../telegram/src/adapter";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Builds a minimal grammy Context mock.
 * chat.type defaults to "private" unless overridden.
 */
function makeCtx(
  overrides: {
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
  } = {},
) {
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
  // Retrieved once in beforeEach after registerEvents() registers it via bot.on("message:text", ...)
  let onHandler:
    | ((ctx: ReturnType<typeof makeCtx>) => Promise<void>)
    | undefined;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = makeAdapter();
    // Wire up the event handlers the same way boot() would.
    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();
    onHandler = vi
      .mocked(mockBotOn)
      .mock.calls.find((c) => c[0] === "message:text")?.[1] as
      | ((ctx: ReturnType<typeof makeCtx>) => Promise<void>)
      | undefined;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("strips @botUsername from group message and streams the cleaned content", async () => {
    expect(onHandler).toBeDefined();

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "@gaiabot what should I do today?",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

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
      undefined,
    );
  });

  it("replies 'How can I help you?' when mention text is empty after stripping", async () => {
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
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "plan my day",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

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
      undefined,
    );
  });

  it("skips messages that start with a command prefix '/'", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "/start",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

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

  it("sends HTML text to the correct chat_id and returns a SentMessage", async () => {
    const sendMessageFn = vi.fn().mockResolvedValue({ message_id: 77 });
    const ctx = makeCtx({ chatId: 111, sendMessageFn });

    const target = (
      adapter as unknown as {
        createCtxTarget: (
          ctx: typeof ctx,
          userId: string,
        ) => {
          send: (
            text: string,
          ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
          platform: string;
          userId: string;
          channelId?: string;
        };
      }
    ).createCtxTarget(ctx, "999");

    const sent = await target.send("Hello from GAIA");

    // Non-streaming sends go through the shared renderForPlatform chokepoint
    // (mocked as identity here) and are sent with parse_mode: "HTML".
    expect(renderForPlatform).toHaveBeenCalledWith(
      "Hello from GAIA",
      "telegram",
    );
    expect(sendMessageFn).toHaveBeenCalledWith(111, "Hello from GAIA", {
      parse_mode: "HTML",
    });
    expect(sent.id).toBe("77");
  });

  it("falls back to stripped plain text when HTML parse fails", async () => {
    const sendMessageFn = vi
      .fn()
      .mockRejectedValueOnce(new Error("can't parse entities: stray tag"))
      .mockResolvedValueOnce({ message_id: 88 });

    const ctx = makeCtx({ chatId: 111, sendMessageFn });

    const target = (
      adapter as unknown as {
        createCtxTarget: (
          ctx: typeof ctx,
          userId: string,
        ) => {
          send: (text: string) => Promise<{ id: string }>;
        };
      }
    ).createCtxTarget(ctx, "999");

    const sent = await target.send("<b>bold</b> & risky");

    // Second (fallback) call must drop parse_mode and send the tag-stripped,
    // entity-decoded plain text so the user still receives a readable message.
    // The opts arg is omitted (undefined) on the fallback path.
    expect(sendMessageFn).toHaveBeenCalledTimes(2);
    expect(sendMessageFn.mock.calls[1]).toEqual([
      111,
      "bold & risky",
      undefined,
    ]);
    expect(sent.id).toBe("88");
  });

  it("exposes correct platform, userId, and channelId on target", () => {
    const ctx = makeCtx({ chatId: 42 });

    const target = (
      adapter as unknown as {
        createCtxTarget: (
          ctx: typeof ctx,
          userId: string,
        ) => {
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
        createCtxTarget: (
          ctx: typeof ctx,
          userId: string,
        ) => {
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
    // richMessageToMarkdown is mocked to return "**GAIA Settings**\nYour settings";
    // renderForPlatform is identity in this mock, so the text is forwarded as-is
    // but with parse_mode: "HTML".
    expect(sendMessageFn).toHaveBeenCalledWith(
      555,
      "**GAIA Settings**\nYour settings",
      { parse_mode: "HTML" },
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
      undefined,
    );
  });

  it("returns early without doing anything when chat ID is missing", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });

    // Build a ctx where chat is undefined — adapter must not proceed
    const ctx = {
      chat: undefined,
      from: {
        id: 999,
        first_name: "Alice",
        last_name: undefined,
        username: "aliceuser",
      },
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
        handleTelegramStreaming: (
          ctx: typeof ctx,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(
      ctx as unknown as ReturnType<typeof makeCtx>,
      "999",
      "hello",
    );

    expect(replyFn).not.toHaveBeenCalled();
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// HTML fallback — the audit-required test: must fail if fallback logic breaks
// ---------------------------------------------------------------------------

describe("TelegramAdapter - HTML fallback retry (editMessage callback)", () => {
  let adapter: TelegramAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  // Drives one streaming turn through handleTelegramStreaming and returns the
  // edit callback it handed to handleStreamingChat. Shared by the HTML-fallback
  // tests, which differ only in the editMessageText mock and the message text.
  async function streamAndCaptureEdit(
    a: TelegramAdapter,
    editMessageTextFn: ReturnType<typeof vi.fn>,
    message: string,
  ): Promise<(text: string) => Promise<void>> {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ chatId: 100, replyFn, editMessageTextFn });

    let capturedEditCallback: ((text: string) => Promise<void>) | undefined;
    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, editMessage) => {
        capturedEditCallback = editMessage;
      },
    );

    await (
      a as unknown as {
        handleTelegramStreaming: (
          ctx: ReturnType<typeof makeCtx>,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleTelegramStreaming(ctx, "999", message);

    if (!capturedEditCallback) {
      throw new Error("edit callback was not captured");
    }
    return capturedEditCallback;
  }

  it("retries editMessageText as stripped plain text when Telegram rejects HTML", async () => {
    const editMessageTextFn = vi
      .fn()
      .mockRejectedValueOnce(
        new Error("Bad Request: can't parse entities: Unsupported start tag"),
      )
      .mockResolvedValueOnce({});

    const editCb = await streamAndCaptureEdit(
      adapter,
      editMessageTextFn,
      "stream me something",
    );

    // Simulate a streaming update with markup Telegram rejects.
    await editCb("a <b>bold</b> & risky chunk");

    // First attempt: with parse_mode: "HTML". Conversion happens inside
    // handleStreamingChat (mocked here), so the adapter callback forwards the
    // text it receives verbatim.
    expect(editMessageTextFn).toHaveBeenNthCalledWith(
      1,
      100,
      42,
      "a <b>bold</b> & risky chunk",
      { parse_mode: "HTML" },
    );

    // Second attempt (fallback): no parse_mode, tags stripped + entities decoded
    // so the user still gets a readable message (opts omitted = undefined).
    expect(editMessageTextFn).toHaveBeenNthCalledWith(
      2,
      100,
      42,
      "a bold & risky chunk",
      undefined,
    );
  });

  it("does NOT retry for 'message is not modified' errors (returns silently)", async () => {
    const editMessageTextFn = vi
      .fn()
      .mockRejectedValueOnce(new Error("Bad Request: message is not modified"));

    const editCb = await streamAndCaptureEdit(
      adapter,
      editMessageTextFn,
      "same content twice",
    );

    await editCb("unchanged content");

    // Only one attempt — must not retry for "not modified"
    expect(editMessageTextFn).toHaveBeenCalledTimes(1);
  });

  it("HTML fallback also applies to sendNewMessage (reply with new message)", async () => {
    // The sendNewMessage callback attempts ctx.reply with parse_mode: "HTML"
    // first. If that throws "can't parse entities", it falls back to ctx.reply
    // with the tag-stripped plain text and no options.
    //
    // Call sequence for replyFn:
    //   1st call: ctx.reply("Thinking...")  → succeeds (message_id: 42)
    //   2nd call: ctx.reply(html, { parse_mode: "HTML" }) → fails (parse error)
    //   3rd call: ctx.reply(plainText)      → succeeds (message_id: 99, fallback)
    const replyFn = vi
      .fn()
      .mockResolvedValueOnce({ message_id: 42 }) // Thinking...
      .mockRejectedValueOnce(
        new Error("Bad Request: can't parse entities: Unsupported start tag"),
      )
      .mockResolvedValueOnce({ message_id: 99 }); // plain fallback

    const ctx = makeCtx({ chatId: 100, replyFn });

    let capturedSendNewMessage:
      | ((
          text: string,
        ) => Promise<((updated: string) => Promise<void>) | undefined>)
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

    // Simulate a new streaming segment with markup Telegram rejects.
    await capturedSendNewMessage!("<i>unclosed italic"); // NOSONAR — non-null assertion needed; variable typed as T | undefined

    // Total calls: Thinking... + HTML attempt + plain fallback = 3
    expect(replyFn).toHaveBeenCalledTimes(3);

    // The last reply call should be plain text with no parse_mode options.
    const lastCall = replyFn.mock.calls[replyFn.mock.calls.length - 1];
    expect(lastCall[0]).toBe("unclosed italic");
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

  it("routes /todo list through dispatch with the parsed subcommand args", async () => {
    const todoExecute = vi.fn().mockResolvedValue(undefined);
    const todoCommand = {
      name: "todo",
      description: "Manage todos",
      options: [],
      execute: todoExecute,
    };
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "todo",
      todoCommand,
    );

    await (
      adapter as unknown as {
        registerCommands: (cmds: (typeof todoCommand)[]) => Promise<void>;
      }
    ).registerCommands([todoCommand]);

    // Find the handler registered for "todo"
    const todoCall = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "todo");
    expect(todoCall).toBeDefined();

    const todoHandler = todoCall![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;

    // grammY's ctx.match is the text after the command, i.e. the subcommand.
    const ctx = makeCtx({ match: "list" });
    await todoHandler(ctx);

    // The adapter derives args via extractSubcommandArgs and the command is
    // executed with the parsed subcommand — the observable contract callers see.
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
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "help",
      helpCommand,
    );

    await (
      adapter as unknown as {
        registerCommands: (cmds: (typeof helpCommand)[]) => Promise<void>;
      }
    ).registerCommands([helpCommand]);

    const startCall = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "start");
    expect(startCall).toBeDefined();

    const startHandler = startCall![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;
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
        registerCommands: (cmds: (typeof gaiaCommand)[]) => Promise<void>;
      }
    ).registerCommands([gaiaCommand]);

    // 'gaia' should be registered via bot.command("gaia", ...) from registerGaiaCommand
    const gaiaCalls = vi
      .mocked(mockBotCommand)
      .mock.calls.filter((c) => c[0] === "gaia");
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

    const sendEphemeralFn = vi
      .fn()
      .mockResolvedValue({ id: "x", edit: vi.fn() });
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
        dispatchCommand: (name: string, target: typeof target) => Promise<void>;
      }
    ).dispatchCommand("nonexistent", target);

    expect(sendEphemeralFn).toHaveBeenCalledWith(
      "Unknown command: /nonexistent",
    );
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
    (adapter as unknown as { commands: Map<string, unknown> }).commands.set(
      "broken",
      throwingCommand,
    );

    const sendEphemeralFn = vi
      .fn()
      .mockResolvedValue({ id: "e", edit: vi.fn() });
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
        dispatchCommand: (name: string, target: typeof target) => Promise<void>;
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
        registerCommands: (
          cmds: {
            name: string;
            description: string;
            options: unknown[];
            execute: ReturnType<typeof vi.fn>;
          }[],
        ) => Promise<void>;
      }
    ).registerCommands([
      {
        name: "gaia",
        description: "Chat with GAIA",
        options: [],
        execute: vi.fn(),
      },
    ]);
  });

  it("sends 'Usage: /gaia <your message>' when invoked with no text", async () => {
    const gaiaCall = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "gaia");
    expect(gaiaCall).toBeDefined();

    const gaiaHandler = gaiaCall![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;
    const replyFn = vi.fn().mockResolvedValue({ message_id: 10 });
    const ctx = makeCtx({ match: "", replyFn });

    await gaiaHandler(ctx);

    expect(replyFn).toHaveBeenCalledWith("Usage: /gaia <your message>");
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("streams when /gaia is invoked with a message", async () => {
    const gaiaCall = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "gaia");
    const gaiaHandler = gaiaCall![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;
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
      undefined,
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

    const onHandler = vi
      .mocked(mockBotOn)
      .mock.calls.find((c) => c[0] === "message:text")?.[1] as
      | ((ctx: unknown) => Promise<void>)
      | undefined;

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

  it("onAuthError edits the loading message with the auth link as HTML (same pipeline as /auth)", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const editMessageTextFn = vi.fn().mockResolvedValue({});
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatId: 500,
      chatType: "private",
      replyFn,
      editMessageTextFn,
    });

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

    // In a private chat the auth prompt is edited in place, through the SAME
    // HTML pipeline as the /auth command — so it renders identically (bold +
    // clickable link), with parse_mode HTML, not raw markdown.
    expect(editMessageTextFn).toHaveBeenCalledWith(
      500,
      42,
      expect.stringContaining("https://gaia.example.com/auth?token=abc"),
      { parse_mode: "HTML" },
    );
  });

  it("onGenericError callback edits the loading message with the error text", async () => {
    vi.clearAllMocks();
    const adapter = makeAdapter();

    const editMessageTextFn = vi.fn().mockResolvedValue({});
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatId: 600,
      chatType: "private",
      replyFn,
      editMessageTextFn,
    });

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

    // Errors go through the same HTML pipeline (parse_mode HTML) so any
    // `code`/bold in the formatted error renders instead of showing literally.
    expect(editMessageTextFn).toHaveBeenCalledWith(
      600,
      42,
      "Something went wrong on our end.",
      { parse_mode: "HTML" },
    );
  });
});

// ---------------------------------------------------------------------------
// extractTelegramMedia — pure mapping of a grammY Message to a media descriptor
// ---------------------------------------------------------------------------

describe("extractTelegramMedia", () => {
  it("picks the largest photo size and maps it to an image", () => {
    const msg = {
      photo: [
        { file_id: "small", width: 90, height: 90 },
        { file_id: "medium", width: 320, height: 320 },
        { file_id: "large", width: 1280, height: 1280 },
      ],
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "image",
      isVoiceNote: false,
      mimeType: "image/jpeg",
      fileId: "large",
    });
  });

  it("maps a voice note to audio with isVoiceNote true and the ogg mime", () => {
    const msg = {
      voice: { file_id: "voice-1", mime_type: "audio/ogg", duration: 5 },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "audio",
      isVoiceNote: true,
      mimeType: "audio/ogg",
      fileId: "voice-1",
    });
  });

  it("maps an audio file to audio with isVoiceNote false and its filename", () => {
    const msg = {
      audio: {
        file_id: "audio-1",
        mime_type: "audio/mpeg",
        file_name: "song.mp3",
        duration: 180,
      },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "audio",
      isVoiceNote: false,
      mimeType: "audio/mpeg",
      filename: "song.mp3",
      fileId: "audio-1",
    });
  });

  it("maps a document to the document kind with filename and mime", () => {
    const msg = {
      document: {
        file_id: "doc-1",
        mime_type: "application/pdf",
        file_name: "report.pdf",
      },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "document",
      isVoiceNote: false,
      mimeType: "application/pdf",
      filename: "report.pdf",
      fileId: "doc-1",
    });
  });

  it("maps a video to the video kind", () => {
    const msg = {
      video: { file_id: "video-1", width: 640, height: 480, duration: 12 },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "video",
      isVoiceNote: false,
      mimeType: "video/mp4",
      fileId: "video-1",
    });
  });

  it("maps a video note (round video) to the video kind", () => {
    const msg = {
      video_note: { file_id: "vnote-1", length: 240, duration: 8 },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)?.kind).toBe("video");
    expect(extractTelegramMedia(msg)?.fileId).toBe("vnote-1");
  });

  it("maps an animation (GIF) to the video kind", () => {
    const msg = {
      animation: { file_id: "gif-1", width: 320, height: 240, duration: 3 },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)?.kind).toBe("video");
    expect(extractTelegramMedia(msg)?.fileId).toBe("gif-1");
  });

  it("maps a sticker to the sticker kind", () => {
    const msg = {
      sticker: { file_id: "sticker-1", width: 512, height: 512 },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)).toEqual({
      kind: "sticker",
      isVoiceNote: false,
      mimeType: "image/webp",
      fileId: "sticker-1",
    });
  });

  it("returns null for a text-only message", () => {
    const msg = { text: "just text" } as unknown as Message;
    expect(extractTelegramMedia(msg)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Media routing — the adapter extracts, resolves, then dispatches the outcome
// ---------------------------------------------------------------------------

/** Builds a grammY-like ctx carrying a private-chat photo message. */
function makePhotoCtx(
  overrides: {
    caption?: string;
    chatType?: "private" | "group" | "supergroup";
    replyFn?: ReturnType<typeof vi.fn>;
  } = {},
) {
  const {
    caption,
    chatType = "private",
    replyFn = vi.fn().mockResolvedValue({ message_id: 42 }),
  } = overrides;
  return {
    chat: { id: 123456, type: chatType },
    from: { id: 999, first_name: "Alice", username: "aliceuser" },
    message: {
      message_id: 10,
      caption,
      photo: [
        { file_id: "small", width: 90, height: 90 },
        { file_id: "large", width: 1280, height: 1280 },
      ],
    },
    reply: replyFn,
    api: {
      editMessageText: vi.fn().mockResolvedValue({}),
      sendMessage: vi.fn().mockResolvedValue({ message_id: 55 }),
      sendChatAction: vi.fn().mockResolvedValue({}),
    },
  };
}

describe("TelegramAdapter - media message routing", () => {
  let adapter: TelegramAdapter;

  /** Overrides the per-test media resolution outcome on the adapter. */
  function setResolveOutcome(outcome: unknown): void {
    (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia.mockResolvedValueOnce(outcome);
  }

  function invokeMediaHandler(ctx: ReturnType<typeof makePhotoCtx>) {
    return (
      adapter as unknown as {
        handleTelegramMediaMessage: (
          ctx: ReturnType<typeof makePhotoCtx>,
        ) => Promise<void>;
      }
    ).handleTelegramMediaMessage(ctx);
  }

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("streams a 'chat' outcome forwarding the uploaded attachment's fileId and data", async () => {
    const attachment = {
      fileId: "uploaded-file-1",
      fileType: "image/jpeg",
      filename: "photo.jpg",
    };
    setResolveOutcome({
      action: "chat",
      text: "describe this image",
      attachments: [attachment],
    });

    const ctx = makePhotoCtx({ caption: "describe this image" });
    await invokeMediaHandler(ctx);

    // The resolved chat turn is streamed with the attachment forwarded as both
    // fileIds (for lookup) and fileData (full metadata) — the observable
    // contract the backend relies on.
    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "describe this image",
        platform: "telegram",
        platformUserId: "999",
        channelId: "123456",
        fileIds: ["uploaded-file-1"],
        fileData: [attachment],
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "telegram" }),
      undefined,
    );
  });

  it("posts a plain reply for a 'reply' outcome and does not stream", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    setResolveOutcome({
      action: "reply",
      text: "I can't process videos yet.",
    });

    const ctx = makePhotoCtx({ replyFn });
    await invokeMediaHandler(ctx);

    expect(replyFn).toHaveBeenCalledWith("I can't process videos yet.");
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("passes the extracted media and a download thunk to resolveIncomingMedia", async () => {
    setResolveOutcome({ action: "reply", text: "ok" });

    const ctx = makePhotoCtx({ caption: "look at this" });
    await invokeMediaHandler(ctx);

    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;

    expect(resolve).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: "image",
        isVoiceNote: false,
        mimeType: "image/jpeg",
        caption: "look at this",
      }),
      expect.any(Function), // download thunk (deferred until needed)
      "999",
      "123456",
    );
  });

  it("ignores a group photo that does not @mention the bot in its caption", async () => {
    setResolveOutcome({ action: "reply", text: "should not be used" });

    const ctx = makePhotoCtx({ chatType: "group", caption: "just a photo" });
    await invokeMediaHandler(ctx);

    // No mention → no resolution, no stream, no reply.
    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;
    expect(resolve).not.toHaveBeenCalled();
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});
