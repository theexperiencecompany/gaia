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
 * 2. group @mention path strips @botUsername and posts the cleaned content
 * 3. createCtxTarget.send — sends HTML text to the correct chat_id
 * 4. createCtxTarget.sendRich — formats rich message via richMessageToMarkdown
 * 5. postTelegramMessage — posts the request and hands postAndFollow the chat's surface
 * 6. conversation surface — native replies, HTML fallback, reactions, typing
 * 7. registerCommands — a slash command dispatches with the parsed subcommand args
 * 8. dispatchCommand — unknown command sends ephemeral error
 * 9. registerGaiaCommand — empty /gaia message sends usage hint
 * 10. extractTelegramMedia — pure mapping of grammY messages to media descriptors
 * 11. media routing — resolved "chat" outcome posts with attachments, "reply"
 *     outcome posts the plain reply
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock grammy before importing the adapter so the module sees the mocks.
// ---------------------------------------------------------------------------

const mockBotOn = vi.fn();
const mockBotUse = vi.fn();
const mockBotCommand = vi.fn();
const mockBotCatch = vi.fn();
const mockBotStart = vi.fn();
const mockBotStop = vi.fn().mockResolvedValue(undefined);
const mockSetMyCommands = vi.fn().mockResolvedValue(undefined);
const mockGetMe = vi.fn().mockResolvedValue({ username: "gaiabot" });
const mockGetFile = vi
  .fn()
  .mockResolvedValue({ file_path: "photos/file_1.jpg" });

const mockSetMessageReaction = vi.fn().mockResolvedValue(true);

const mockBotInstance = {
  on: mockBotOn,
  use: mockBotUse,
  command: mockBotCommand,
  catch: mockBotCatch,
  start: mockBotStart,
  stop: mockBotStop,
  api: {
    getMe: mockGetMe,
    getFile: mockGetFile,
    setMyCommands: mockSetMyCommands,
    editMessageText: vi.fn().mockResolvedValue({}),
    sendMessage: vi.fn().mockResolvedValue({ message_id: 99 }),
    sendChatAction: vi.fn().mockResolvedValue({}),
    deleteMessage: vi.fn().mockResolvedValue(true),
    setMessageReaction: mockSetMessageReaction,
  },
};

vi.mock("grammy", () => ({
  Bot: vi.fn().mockImplementation(() => mockBotInstance),
  GrammyError: class GrammyError extends Error {
    constructor(
      message: string,
      public error_code: number,
      public description: string,
    ) {
      super(message);
      this.name = "GrammyError";
    }
  },
}));

vi.mock("@grammyjs/types", () => ({}));

// Mocks @gaia/shared via the shared factory (BaseBotAdapter stub + common
// helpers), layering Telegram-specific exports (HTML converter, htmlToPlainText,
// media helpers, extractSubcommandArgs) on top via `converters`.

vi.mock("@gaia/shared/bots", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  const real = await import("../../../../libs/shared/ts/src/bots/utils");
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
      // The capped reader is real: these tests assert the adapter never
      // materialises more than the cap it was handed.
      fetchBytesCapped: vi.fn(real.fetchBytesCapped),
      friendlyMediaError: vi.fn(
        (kind: string) => `Could not process your ${kind}.`,
      ),
      unsupportedMediaMessage: vi.fn(
        (kind: string) => `I can't process ${kind} yet.`,
      ),
      // The real boundary and failure recorder, so the runtime-error test
      // reads the bot_event the adapter really prints.
      withWideEvent: vi.fn(real.withWideEvent),
      recordBotFailure: vi.fn(real.recordBotFailure),
    },
  });
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import {
  fetchBytesCapped,
  MEDIA_READ_TIMEOUT_MS,
  type ReactionOutcome,
  renderForPlatform,
  richMessageToMarkdown,
} from "@gaia/shared/bots";
import type { Message } from "@grammyjs/types";
// From source, not the mocked barrel: GaiaApiError is the error class the real
// link-code path branches on, and the mock does not re-export it.
import { GaiaApiError } from "../../../../libs/shared/ts/src/bots/api";
import {
  extractTelegramMedia,
  TelegramAdapter,
} from "../../telegram/src/adapter";
import { captureBotEvents } from "../shared/helpers/capture-bot-event";
import {
  lastAuthHandler,
  lastSurface,
  postAndFollowSpy,
} from "../shared/mocks/postAndFollow";

/** A real-shaped one-tap link code: 22 urlsafe-base64 characters. */
const LINK_CODE = "Ab3-_xY9zQ1234567890wE";

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

/** Asserts postAndFollow received a request carrying these fields, a surface and an auth handler. */
function expectPosted(request: Record<string, unknown>): void {
  expect(postAndFollowSpy).toHaveBeenCalledWith(
    expect.objectContaining(request),
    expect.objectContaining({
      send: expect.any(Function),
      react: expect.any(Function),
      startTyping: expect.any(Function),
    }),
    expect.any(Function),
  );
}

type TelegramPoster = {
  postTelegramMessage: (
    ctx: unknown,
    userId: string,
    message: string,
  ) => Promise<void>;
};

type TypingIndicator = {
  startTypingIndicator: (
    send: () => Promise<unknown>,
    refreshMs: number,
  ) => () => void;
};

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

  it("strips @botUsername from group message and posts the cleaned content", async () => {
    expect(onHandler).toBeDefined();

    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "@gaiabot what should I do today?",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expectPosted({
      message: "what should I do today?",
      platform: "telegram",
      platformUserId: "999",
      channelId: "123456",
      isDm: false,
    });
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
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("ignores group messages that do not mention the bot", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "group",
      text: "this message does not mention anyone",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expect(postAndFollowSpy).not.toHaveBeenCalled();
    expect(replyFn).not.toHaveBeenCalled();
  });

  it("posts private chat messages as a DM", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "plan my day",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expectPosted({ message: "plan my day", platform: "telegram", isDm: true });
  });

  it("handles a second message while the first one's post is still pending", async () => {
    postAndFollowSpy.mockReturnValueOnce(new Promise<void>(() => undefined));

    void onHandler!(makeCtx({ text: "do the work" })); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]
    await onHandler!(makeCtx({ text: "and then" })); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expect(postAndFollowSpy.mock.calls.map(([req]) => req.message)).toEqual([
      "do the work",
      "and then",
    ]);
  });

  it("skips messages that start with a command prefix '/'", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({
      chatType: "private",
      text: "/start",
      replyFn,
    });

    await onHandler!(ctx); // NOSONAR — non-null assertion needed; type includes undefined from find()?.[1]

    expect(postAndFollowSpy).not.toHaveBeenCalled();
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

    expect(richMessageToMarkdown).toHaveBeenCalledWith(richMsg);
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
// postTelegramMessage — posts the message and hands postAndFollow the chat
// ---------------------------------------------------------------------------

describe("TelegramAdapter - postTelegramMessage", () => {
  let adapter: TelegramAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  it("posts the request with the inbound message id and does not reply itself", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = {
      ...makeCtx({ chatId: 77777, replyFn }),
      msg: { message_id: 10 },
    };

    await (adapter as unknown as TelegramPoster).postTelegramMessage(
      ctx,
      "555",
      "what is 2+2?",
    );

    expectPosted({
      message: "what is 2+2?",
      platform: "telegram",
      platformUserId: "555",
      channelId: "77777",
      isDm: true,
      platformMessageId: "10",
    });
    expect(replyFn).not.toHaveBeenCalled();
    expect(mockBotInstance.api.sendMessage).not.toHaveBeenCalled();
  });

  it("returns early without doing anything when chat ID is missing", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = { ...makeCtx({ replyFn }), chat: undefined };

    await (adapter as unknown as TelegramPoster).postTelegramMessage(
      ctx,
      "999",
      "hello",
    );

    expect(replyFn).not.toHaveBeenCalled();
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Conversation surface — what the follower renders the reply through
// ---------------------------------------------------------------------------

describe("TelegramAdapter - conversation surface", () => {
  let adapter: TelegramAdapter;
  const api = mockBotInstance.api;
  const htmlRejection = () =>
    new Error("Bad Request: can't parse entities: Unsupported start tag");

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = makeAdapter();
  });

  /** Posts one message in a chat and returns the surface handed to postAndFollow. */
  async function surfaceFor(
    chatType: "private" | "group" = "private",
  ): Promise<ReturnType<typeof lastSurface>> {
    await (adapter as unknown as TelegramPoster).postTelegramMessage(
      makeCtx({ chatId: 100, chatType }),
      "999",
      "hi",
    );
    return lastSurface();
  }

  it("sends a new message as HTML without a quote when there is nothing to reply to", async () => {
    const surface = await surfaceFor();

    await surface.send("<b>hello</b>", null);

    expect(api.sendMessage).toHaveBeenCalledWith(100, "<b>hello</b>", {
      parse_mode: "HTML",
    });
  });

  it("answers the inbound message natively when given its id", async () => {
    const surface = await surfaceFor();

    await surface.send("on it", "123");

    expect(api.sendMessage).toHaveBeenCalledWith(100, "on it", {
      parse_mode: "HTML",
      reply_parameters: { message_id: 123, allow_sending_without_reply: true },
    });
  });

  it("resends as stripped plain text, keeping the quote, when Telegram rejects the HTML", async () => {
    api.sendMessage
      .mockRejectedValueOnce(htmlRejection())
      .mockResolvedValueOnce({ message_id: 99 });
    const surface = await surfaceFor();

    await surface.send("<i>unclosed italic", "123");

    const quote = {
      reply_parameters: { message_id: 123, allow_sending_without_reply: true },
    };
    expect(api.sendMessage.mock.calls).toEqual([
      [100, "<i>unclosed italic", { parse_mode: "HTML", ...quote }],
      [100, "unclosed italic", quote],
    ]);
  });

  it("edits the sent message as HTML and retries as plain text when Telegram rejects it", async () => {
    api.editMessageText
      .mockRejectedValueOnce(htmlRejection())
      .mockResolvedValueOnce({});
    const surface = await surfaceFor();
    const sent = await surface.send("first", null);

    await sent.edit("a <b>bold</b> & risky chunk");

    expect(api.editMessageText.mock.calls).toEqual([
      [100, 99, "a <b>bold</b> & risky chunk", { parse_mode: "HTML" }],
      [100, 99, "a bold & risky chunk", undefined],
    ]);
  });

  it("treats 'message is not modified' as done without retrying", async () => {
    api.editMessageText.mockRejectedValueOnce(
      new Error("Bad Request: message is not modified"),
    );
    const surface = await surfaceFor();
    const sent = await surface.send("first", null);

    await sent.edit("unchanged content");

    expect(api.editMessageText).toHaveBeenCalledTimes(1);
  });

  it("rethrows an edit failure that resending cannot fix", async () => {
    api.editMessageText.mockRejectedValueOnce(
      new Error("Too Many Requests: retry after 5"),
    );
    const surface = await surfaceFor();
    const sent = await surface.send("first", null);

    await expect(sent.edit("next")).rejects.toThrow("Too Many Requests");
    expect(api.editMessageText).toHaveBeenCalledTimes(1);
  });

  it("deletes the sent message", async () => {
    const surface = await surfaceFor();
    const sent = await surface.send("first", null);

    await sent.delete?.();

    expect(api.deleteMessage).toHaveBeenCalledWith(100, 99);
  });

  it("reacts in the chat it was posted from", async () => {
    const react = vi
      .spyOn(adapter as unknown as TelegramReactor, "reactToMessage")
      .mockResolvedValue("attached");
    const surface = await surfaceFor("group");

    await expect(surface.react("10", "👍", "🔎")).resolves.toBe("attached");
    expect(react).toHaveBeenCalledWith("100", "10", "👍", true, "🔎");
  });

  it("starts the typing action and hands back the indicator's stop", async () => {
    const stop = vi.fn();
    vi.spyOn(
      adapter as unknown as TypingIndicator,
      "startTypingIndicator",
    ).mockImplementation((send) => {
      void send();
      return stop;
    });
    const surface = await surfaceFor();

    const stopTyping = surface.startTyping();
    expect(api.sendChatAction).toHaveBeenCalledWith(100, "typing");

    stopTyping();
    expect(stop).toHaveBeenCalledTimes(1);
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

  it("redeems a /start deep-link payload and sends the whole first contact", async () => {
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
    const redeemLinkCode = vi
      .fn()
      .mockResolvedValue({ linked: true, delivered: true, firstContact: [] });
    (adapter as unknown as { gaia: unknown }).gaia = {
      redeemLinkCode,
      getFrontendUrl: () => "https://gaia.test",
    };

    await (
      adapter as unknown as {
        registerCommands: (cmds: (typeof helpCommand)[]) => Promise<void>;
      }
    ).registerCommands([helpCommand]);

    const startHandler = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "start")![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;

    const sendMessageFn = vi.fn().mockResolvedValue({ message_id: 55 });
    await startHandler(makeCtx({ match: LINK_CODE, sendMessageFn }));

    expect(redeemLinkCode).toHaveBeenCalledWith(
      "telegram",
      "999",
      LINK_CODE,
      expect.objectContaining({ username: "aliceuser", displayName: "Alice" }),
      // A deep link is a tap, not a message: no opening turn is invented.
      undefined,
    );
    // The API composes the first contact and delivers it on the outbound queue
    // when the link completes, so /start sends nothing of its own — a bubble
    // from here would arrive alongside the server's and duplicate it.
    expect(sendMessageFn).not.toHaveBeenCalled();
    // No model turn runs behind it either: the opener turn skipped the per-pick
    // promises and lost the connect links.
    expect(postAndFollowSpy).not.toHaveBeenCalled();
    expect(helpExecute).not.toHaveBeenCalled();
  });

  it("does not chat when the /start payload fails to redeem", async () => {
    const redeemLinkCode = vi
      .fn()
      .mockRejectedValue(new GaiaApiError("expired", 400));
    (adapter as unknown as { gaia: unknown }).gaia = {
      redeemLinkCode,
      getFrontendUrl: () => "https://gaia.test",
    };

    await (
      adapter as unknown as {
        registerCommands: (c: unknown[]) => Promise<void>;
      }
    ).registerCommands([]);

    const startHandler = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "start")![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;

    const sendMessageFn = vi.fn().mockResolvedValue({ message_id: 55 });
    await startHandler(makeCtx({ match: LINK_CODE, sendMessageFn }));

    expect(postAndFollowSpy).not.toHaveBeenCalled();
    // The only thing a refused code may produce is the explanation of why.
    expect(sendMessageFn).toHaveBeenCalledTimes(1);
    expect(String(sendMessageFn.mock.calls[0][1])).toContain(
      "That link has expired",
    );
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
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("posts when /gaia is invoked with a message", async () => {
    const gaiaCall = vi
      .mocked(mockBotCommand)
      .mock.calls.find((c) => c[0] === "gaia");
    const gaiaHandler = gaiaCall![1] as (
      ctx: ReturnType<typeof makeCtx>,
    ) => Promise<void>;
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    const ctx = makeCtx({ match: "remind me to call dentist", replyFn });

    await gaiaHandler(ctx);

    expectPosted({
      message: "remind me to call dentist",
      platform: "telegram",
    });
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

    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  /** Posts one message from user 999 in chat 500 and returns the auth handler it handed postAndFollow. */
  async function authHandlerFor(
    chatType: "private" | "group",
  ): Promise<(authUrl: string) => Promise<void>> {
    const adapter = makeAdapter();
    await (adapter as unknown as TelegramPoster).postTelegramMessage(
      makeCtx({ chatId: 500, chatType }),
      "999",
      "do something",
    );
    return lastAuthHandler();
  }

  const authUrl = "https://gaia.example.com/auth?token=abc";

  it("sends the auth link in a private chat as HTML (same pipeline as /auth)", async () => {
    vi.clearAllMocks();
    const onAuthError = await authHandlerFor("private");

    await onAuthError(authUrl);

    expect(mockBotInstance.api.sendMessage.mock.calls).toEqual([
      [500, expect.stringContaining(authUrl), { parse_mode: "HTML" }],
    ]);
  });

  it("DMs the auth link from a group and tells the group it did", async () => {
    vi.clearAllMocks();
    const onAuthError = await authHandlerFor("group");

    await onAuthError(authUrl);

    expect(mockBotInstance.api.sendMessage.mock.calls).toEqual([
      [999, expect.stringContaining(authUrl), { parse_mode: "HTML" }],
      [500, "I sent you a DM with the authentication link."],
    ]);
  });

  it("points the group at a direct chat when Telegram refuses the DM, without leaking the link", async () => {
    vi.clearAllMocks();
    mockBotInstance.api.sendMessage.mockRejectedValueOnce(
      new Error("Forbidden: bot can't initiate conversation with a user"),
    );
    const onAuthError = await authHandlerFor("group");

    await onAuthError(authUrl);

    const groupMessages = mockBotInstance.api.sendMessage.mock.calls.filter(
      ([chatId]) => chatId === 500,
    );
    expect(groupMessages).toEqual([
      [500, expect.stringContaining("message me directly at @gaiabot")],
    ]);
    expect(String(groupMessages[0][1])).not.toContain(authUrl);
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

  it("carries the largest photo's declared file_size as sizeBytes", () => {
    const msg = {
      photo: [
        { file_id: "small", width: 90, height: 90, file_size: 900 },
        { file_id: "large", width: 1280, height: 1280, file_size: 11_000_000 },
      ],
    } as unknown as Message;

    expect(extractTelegramMedia(msg)?.sizeBytes).toBe(11_000_000);
  });

  it("carries file_size for voice, audio, document, video and sticker", () => {
    const cases: [Record<string, unknown>, number][] = [
      [{ voice: { file_id: "v", mime_type: "audio/ogg", file_size: 1 } }, 1],
      [{ audio: { file_id: "a", mime_type: "audio/mpeg", file_size: 2 } }, 2],
      [{ document: { file_id: "d", file_size: 3 } }, 3],
      [{ video: { file_id: "vid", file_size: 4 } }, 4],
      [{ sticker: { file_id: "s", file_size: 5 } }, 5],
    ];

    for (const [msg, expected] of cases) {
      expect(extractTelegramMedia(msg as unknown as Message)?.sizeBytes).toBe(
        expected,
      );
    }
  });

  it("leaves sizeBytes undefined when Telegram omits file_size", () => {
    const msg = {
      document: { file_id: "doc-1", mime_type: "application/pdf" },
    } as unknown as Message;

    expect(extractTelegramMedia(msg)?.sizeBytes).toBeUndefined();
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
    fileSize?: number;
  } = {},
) {
  const {
    caption,
    chatType = "private",
    replyFn = vi.fn().mockResolvedValue({ message_id: 42 }),
    fileSize,
  } = overrides;
  return {
    chat: { id: 123456, type: chatType },
    from: { id: 999, first_name: "Alice", username: "aliceuser" },
    message: {
      message_id: 10,
      caption,
      photo: [
        { file_id: "small", width: 90, height: 90 },
        { file_id: "large", width: 1280, height: 1280, file_size: fileSize },
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

  it("posts a 'chat' outcome forwarding the uploaded attachment's fileId and data", async () => {
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

    // The resolved chat message is posted with the attachment forwarded as both
    // fileIds (for lookup) and fileData (full metadata) — the observable
    // contract the backend relies on.
    expectPosted({
      message: "describe this image",
      platform: "telegram",
      platformUserId: "999",
      channelId: "123456",
      fileIds: ["uploaded-file-1"],
      fileData: [attachment],
    });
  });

  it("posts a plain reply for a 'reply' outcome and does not post a message", async () => {
    const replyFn = vi.fn().mockResolvedValue({ message_id: 42 });
    setResolveOutcome({
      action: "reply",
      text: "I can't process videos yet.",
    });

    const ctx = makePhotoCtx({ replyFn });
    await invokeMediaHandler(ctx);

    expect(replyFn).toHaveBeenCalledWith("I can't process videos yet.");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
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

  it("forwards the declared file size so an oversize photo never reaches getFile", async () => {
    setResolveOutcome({ action: "reply", text: "ok" });

    const ctx = makePhotoCtx({ fileSize: 11_000_000 });
    await invokeMediaHandler(ctx);

    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;

    expect(resolve.mock.calls[0][0]).toMatchObject({ sizeBytes: 11_000_000 });
    expect(mockGetFile).not.toHaveBeenCalled();
  });

  it("reads the Telegram file through a capped stream instead of buffering it whole", async () => {
    setResolveOutcome({ action: "reply", text: "ok" });
    (adapter as unknown as { token: string }).token = "test-token";

    const chunk = 256;
    let produced = 0;
    let cancelled = false;
    const fetchMock = vi.fn(async (_url: string) => ({
      ok: true,
      status: 200,
      body: new ReadableStream<Uint8Array>({
        pull(controller) {
          produced += chunk;
          controller.enqueue(new Uint8Array(chunk).fill(4));
        },
        cancel() {
          cancelled = true;
        },
      }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    try {
      await invokeMediaHandler(makePhotoCtx());

      const resolve = (
        adapter as unknown as {
          resolveIncomingMedia: ReturnType<typeof vi.fn>;
        }
      ).resolveIncomingMedia;
      const download = resolve.mock.calls[0][1] as (
        maxBytes: number,
      ) => Promise<Uint8Array>;

      expect(fetchMock).not.toHaveBeenCalled();
      const bytes = await download(1000);

      expect(mockGetFile).toHaveBeenCalledWith("large");
      expect(fetchMock.mock.calls[0][0]).toBe(
        "https://api.telegram.org/file/bottest-token/photos/file_1.jpg",
      );
      expect(bytes.byteLength).toBe(1000);
      expect(cancelled).toBe(true);
      expect(produced).toBeLessThanOrEqual(1000 + 2 * chunk);
      expect(vi.mocked(fetchBytesCapped).mock.calls[0][3]).toBe(
        MEDIA_READ_TIMEOUT_MS,
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("surfaces a failed file download as an error carrying the HTTP status", async () => {
    setResolveOutcome({ action: "reply", text: "ok" });
    (adapter as unknown as { token: string }).token = "test-token";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: false, status: 429, body: null })),
    );

    try {
      await invokeMediaHandler(makePhotoCtx());

      const resolve = (
        adapter as unknown as {
          resolveIncomingMedia: ReturnType<typeof vi.fn>;
        }
      ).resolveIncomingMedia;
      const download = resolve.mock.calls[0][1] as (
        maxBytes: number,
      ) => Promise<Uint8Array>;

      await expect(download(1000)).rejects.toMatchObject({ status: 429 });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("ignores a group photo that does not @mention the bot in its caption", async () => {
    setResolveOutcome({ action: "reply", text: "should not be used" });

    const ctx = makePhotoCtx({ chatType: "group", caption: "just a photo" });
    await invokeMediaHandler(ctx);

    // No mention → no resolution, no post, no reply.
    const resolve = (
      adapter as unknown as {
        resolveIncomingMedia: ReturnType<typeof vi.fn>;
      }
    ).resolveIncomingMedia;
    expect(resolve).not.toHaveBeenCalled();
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// bot.catch — grammY's last-resort handler
// ---------------------------------------------------------------------------

describe("TelegramAdapter - runtime errors", () => {
  it("records a middleware crash as a failed bot_runtime_error with its reason and hashed ids", async () => {
    const adapter = makeAdapter();
    (
      adapter as unknown as { registerErrorHandler: () => void }
    ).registerErrorHandler();
    const handler = mockBotCatch.mock.calls.at(-1)?.[0] as (err: {
      error: unknown;
      ctx: unknown;
    }) => Promise<void>;

    const events = await captureBotEvents("bot_runtime_error", () =>
      handler({
        error: new Error("Forbidden: bot was blocked by the user"),
        ctx: { from: { id: 42 }, chat: { id: 7 }, update: { update_id: 9 } },
      }),
    );

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      platform: "telegram",
      outcome: "failed",
      reason: "destination_blocked",
      user_hash: "h_42",
      channel_hash: "h_7",
      update_id: 9,
    });
  });
});

// ---------------------------------------------------------------------------
// reactToMessage — the native reaction primitive the surface reacts through
// ---------------------------------------------------------------------------

type TelegramReactor = {
  reactToMessage: (
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
    replaces: string | null,
  ) => Promise<ReactionOutcome>;
};

describe("TelegramAdapter - reactToMessage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("attaches via setMessageReaction with numeric chat and message ids", async () => {
    const adapter = makeAdapter() as unknown as TelegramReactor;

    const attached = await adapter.reactToMessage(
      "4242",
      "777",
      "👍",
      false,
      null,
    );

    expect(attached).toBe("attached");
    expect(mockSetMessageReaction).toHaveBeenCalledWith("4242", 777, [
      { type: "emoji", emoji: "👍" },
    ]);
  });

  it("replaces GAIA's earlier reaction by setting the new one alone", async () => {
    const adapter = makeAdapter() as unknown as TelegramReactor;

    await adapter.reactToMessage("4242", "777", "👍", false, "🔎");

    expect(mockSetMessageReaction.mock.calls).toEqual([
      ["4242", 777, [{ type: "emoji", emoji: "👍" }]],
    ]);
  });

  it("sends a heart without the variation selector Telegram's reaction list omits", async () => {
    const adapter = makeAdapter() as unknown as TelegramReactor;

    const attached = await adapter.reactToMessage(
      "4242",
      "777",
      "❤️",
      false,
      null,
    );

    expect(attached).toBe("attached");
    expect(mockSetMessageReaction).toHaveBeenCalledWith("4242", 777, [
      { type: "emoji", emoji: "❤" },
    ]);
  });

  it("refuses without sending text when Telegram rejects the emoji", async () => {
    mockSetMessageReaction.mockRejectedValueOnce(new Error("Bad Request"));
    const adapter = makeAdapter() as unknown as TelegramReactor;

    const attached = await adapter.reactToMessage(
      "4242",
      "777",
      "✅",
      false,
      null,
    );

    expect(attached).toBe("attach_failed");
    expect(mockBotInstance.api.sendMessage).not.toHaveBeenCalled();
  });
});
