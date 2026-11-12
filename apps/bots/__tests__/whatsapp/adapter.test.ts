/**
 * Tests for the WhatsAppAdapter.
 *
 * The adapter constructor and boot() require live Kapso credentials and a
 * running HTTP server, so we test observable behaviors that don't need a live
 * connection by mocking @kapso/whatsapp-cloud-api, hono, @hono/node-server,
 * ./webhook, and @gaia/shared, then exercising the adapter's private/protected
 * methods directly via TypeScript casts.
 *
 * Covered behaviors:
 * 1.  platform property returns "whatsapp"
 * 2.  sendWhatsAppText — calls waClient.messages.sendText with correct args
 * 3.  sendWhatsAppText — SentMessage.id comes from response.messages[0].id
 * 4.  sendWhatsAppText — SentMessage.edit sends a new message (no API edit)
 * 5.  sendWhatsAppText — empty messages array defaults id to ""
 * 6.  createWaTarget — platform/userId/channelId identity
 * 7.  createWaTarget.send — delegates to sendWhatsAppText
 * 8.  createWaTarget.sendEphemeral — identical to send (no ephemeral concept)
 * 9.  createWaTarget.sendRich — renders via richMessageToMarkdown (platform-aware) and sends directly
 * 10. createWaTarget.startTyping — returns a callable no-op
 * 11. handleIncomingMessage — /gaia <text> posts the message
 * 12. handleIncomingMessage — /gaia (no text) sends usage hint, no post
 * 13. handleIncomingMessage — /todo <args> dispatches todo command
 * 14. handleIncomingMessage — /help dispatches help command
 * 15. handleIncomingMessage — plain text posts the message
 * 16. handleIncomingMessage — /GAIA hello (uppercase) still posts
 * 17. postWhatsAppMessage — empty or whitespace text sends help text, no post
 * 18. postWhatsAppMessage — posts the request with the inbound wamid
 * 19. postWhatsAppMessage — the auth handler sends the link message
 * 20. conversation surface — native replies (contextMessageId), edit as a new
 *     message, reactions, the typing indicator
 * 21. dispatchCommand — unknown command sends ephemeral error
 * 22. dispatchCommand — registered command that throws sends ephemeral error
 * 23. handleIncomingMessage — sends welcome on first contact, not on second
 * 24. handleIncomingMessage — welcome sent per user (different users each get one)
 * 25. inbound order — posts go in arrival order; a /stop is dispatched at once
 *
 * Inbound media routing (build descriptor → resolveIncomingMedia → reply/chat
 * dispatch, unsupported-kind rejection, friendly error mapping) is covered in
 * media-flow.test.ts; the shared transcribe/upload/reject decision lives in
 * processBotMedia and is covered in __tests__/shared/utils/media.test.ts.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock @kapso/whatsapp-cloud-api before importing the adapter.
// ---------------------------------------------------------------------------

const mockSendText = vi.fn();
const mockMarkRead = vi.fn();
const mockSendReaction = vi.fn();
const mockWaClientInstance = {
  messages: {
    sendText: mockSendText,
    markRead: mockMarkRead,
    sendReaction: mockSendReaction,
  },
};

vi.mock("@kapso/whatsapp-cloud-api", () => ({
  WhatsAppClient: vi.fn().mockImplementation(() => mockWaClientInstance),
}));

// ---------------------------------------------------------------------------
// Mock hono before importing the adapter.
// ---------------------------------------------------------------------------

vi.mock("hono", () => ({
  Hono: vi.fn().mockImplementation(() => ({
    get: vi.fn(),
    post: vi.fn(),
    fetch: vi.fn(),
  })),
}));

// ---------------------------------------------------------------------------
// Mock @hono/node-server before importing the adapter.
// ---------------------------------------------------------------------------

vi.mock("@hono/node-server", () => ({
  serve: vi.fn(),
}));

// Mock ./webhook before importing the adapter. vi.mock factories are hoisted, so
// we can't reference module-level variables inside them — use vi.fn() inline and
// retrieve the mocks after import via vi.mocked().

vi.mock("../../whatsapp/src/webhook", () => ({
  verifyKapsoSignature: vi.fn(),
  extractWaId: vi.fn(),
  extractTextBody: vi.fn(),
  KapsoMessageEvent: undefined,
}));

// ---------------------------------------------------------------------------
// Mock @gaia/shared — BaseBotAdapter stub + shared helpers.
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared/bots", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  // Wire the REAL pure helpers the adapter imports (command-arg parsing and the
  // media error/unsupported copy) so behavior is asserted against production
  // output, not stubs.
  const real = await import("../../../../libs/shared/ts/src/bots/utils");
  return makeGaiaSharedMock("whatsapp", {
    streamingDefaults: {
      whatsapp: {
        editIntervalMs: 2000,
        streaming: false,
        platform: "whatsapp",
      },
    },
    converters: {
      extractSubcommandArgs: vi.fn(real.extractSubcommandArgs),
      friendlyMediaError: vi.fn(real.friendlyMediaError),
      unsupportedMediaMessage: vi.fn(real.unsupportedMediaMessage),
      // Real, so the welcome auth check can be held the way it is in production.
      withTimeout: vi.fn(real.withTimeout),
    },
    defaultRichMarkdown: "*GAIA Help*\nUse /gaia to chat",
  });
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import { type ReactionOutcome, richMessageToMarkdown } from "@gaia/shared/bots";
// From source, not the mocked barrel: GaiaApiError is the error class the real
// redeemLinkCode branches on, so a stub would prove nothing about the failure path.
import { GaiaApiError } from "../../../../libs/shared/ts/src/bots/api";

/** A real-shaped one-tap link code: 22 urlsafe-base64 characters. */
const LINK_CODE = "Ab3-_xY9zQ1234567890wE";
const LINK_FIRST_MESSAGE =
  "Hi! I'm a founder. I could use help with my inbox. Who are you?";

import { WhatsAppAdapter } from "../../whatsapp/src/adapter";
import { TYPING_REFRESH_MS } from "../../whatsapp/src/constants";
import {
  lastAuthHandler,
  lastSurface,
  postAndFollowSpy,
} from "../shared/mocks/postAndFollow";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const MOCK_CONFIG = {
  kapsoApiKey: "test-api-key", // pragma: allowlist secret
  kapsoPhoneNumberId: "test-phone-id",
  kapsoWebhookSecret: "test-secret", // pragma: allowlist secret
  webhookPort: 3001,
};

/** Builds an adapter with mock client + config injected, bypassing initialize(). */
function makeAdapter(): WhatsAppAdapter {
  const adapter = new WhatsAppAdapter();
  (adapter as unknown as { waClient: typeof mockWaClientInstance }).waClient =
    mockWaClientInstance;
  (adapter as unknown as { waConfig: typeof MOCK_CONFIG }).waConfig =
    MOCK_CONFIG;
  return adapter;
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

/** Convenience cast to access private methods on the adapter. */
type PrivateAdapter = {
  sendWhatsAppText: (
    waId: string,
    text: string,
  ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
  createWaTarget: (waId: string) => {
    platform: string;
    userId: string;
    channelId: string;
    send: (
      text: string,
    ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
    sendEphemeral: (
      text: string,
    ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
    sendRich: (
      richMsg: unknown,
    ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
    startTyping: () => Promise<() => void>;
  };
  handleIncomingMessage: (
    waId: string,
    text: string,
    messageId: string,
  ) => Promise<void>;
  postWhatsAppMessage: (
    waId: string,
    text: string,
    messageId: string,
  ) => Promise<void>;
  sendWelcome: (waId: string) => Promise<void>;
  welcomeSent: Set<string>;
  dispatchCommand: (
    name: string,
    target: {
      sendEphemeral: (
        t: string,
      ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
    },
    args?: Record<string, string | number | boolean | undefined>,
    rawText?: string,
  ) => Promise<void>;
  commands: Map<string, { execute: (p: unknown) => Promise<void> }>;
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - platform identity", () => {
  it('reports platform as "whatsapp"', () => {
    const adapter = new WhatsAppAdapter();
    expect(adapter.platform).toBe("whatsapp");
  });
});

// ---------------------------------------------------------------------------
// sendWhatsAppText — private method
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - sendWhatsAppText", () => {
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("calls waClient.messages.sendText with correct arguments", async () => {
    await priv.sendWhatsAppText("15551234567", "Hello");

    expect(mockSendText).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      to: "+15551234567",
      body: "Hello",
      previewUrl: false,
    });
  });

  it("returns SentMessage with id from response.messages[0].id", async () => {
    const sent = await priv.sendWhatsAppText("15551234567", "Hello");

    expect(sent.id).toBe("wa-msg-123");
  });

  it("SentMessage.edit calls sendText again with updated text (no API edit — WhatsApp sends new message)", async () => {
    const sent = await priv.sendWhatsAppText("15551234567", "Hello");
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-456" }] });

    await sent.edit("Updated text");

    expect(mockSendText).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      to: "+15551234567",
      body: "Updated text",
      previewUrl: false,
    });
  });

  it("defaults id to empty string when response.messages is empty", async () => {
    mockSendText.mockResolvedValue({ messages: [] });

    const sent = await priv.sendWhatsAppText("15551234567", "Hello");

    expect(sent.id).toBe("");
  });
});

// ---------------------------------------------------------------------------
// createWaTarget — private method
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - createWaTarget", () => {
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('target.platform is "whatsapp"', () => {
    const target = priv.createWaTarget("15551234567");
    expect(target.platform).toBe("whatsapp");
  });

  it("target.userId equals the waId", () => {
    const target = priv.createWaTarget("15551234567");
    expect(target.userId).toBe("15551234567");
  });

  it("target.channelId equals the waId", () => {
    const target = priv.createWaTarget("15551234567");
    expect(target.channelId).toBe("15551234567");
  });

  it("target.send calls sendText and returns a SentMessage", async () => {
    const target = priv.createWaTarget("15551234567");

    const sent = await target.send("Hello via send");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Hello via send", to: "+15551234567" }),
    );
    expect(sent.id).toBe("wa-msg-123");
  });

  it("target.sendEphemeral behaves identically to send (no ephemeral concept in WhatsApp)", async () => {
    const target = priv.createWaTarget("15551234567");

    const sent = await target.sendEphemeral("Ephemeral message");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: "Ephemeral message",
        to: "+15551234567",
      }),
    );
    expect(sent.id).toBe("wa-msg-123");
  });

  it("target.sendRich renders via richMessageToMarkdown (already platform-aware) and sends it directly", async () => {
    const target = priv.createWaTarget("15551234567");
    const richMsg = { title: "GAIA Help", sections: [] };

    // richMessageToMarkdown emits platform-agnostic CommonMark (mocked here);
    // the target converts it for WhatsApp via the shared renderForPlatform
    // chokepoint before sending.
    vi.mocked(richMessageToMarkdown).mockReturnValueOnce(
      "*GAIA Help*\n*Name:* Aryan",
    );

    await target.sendRich(richMsg);

    expect(richMessageToMarkdown).toHaveBeenCalledWith(richMsg);
    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "*GAIA Help*\n*Name:* Aryan" }),
    );
  });

  it("target.startTyping returns a callable no-op that does not throw", async () => {
    const target = priv.createWaTarget("15551234567");

    const stopTyping = await target.startTyping();

    expect(() => stopTyping()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleIncomingMessage — private method
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - handleIncomingMessage", () => {
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows typing indicator via markRead for every incoming message", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "hello", "wamid.001");

    expect(mockMarkRead).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      messageId: "wamid.001",
      typingIndicator: { type: "text" },
    });
  });

  it("redeems a trailing #code from an unlinked sender and says nothing itself", async () => {
    mockMarkRead.mockResolvedValue({});
    const redeemLinkCode = vi
      .fn()
      .mockResolvedValue({ linked: true, delivered: true, firstContact: [] });
    (adapter as unknown as { gaia: unknown }).gaia = {
      checkAuthStatus: vi.fn().mockResolvedValue({ authenticated: false }),
      redeemLinkCode,
      getFrontendUrl: () => "https://gaia.test",
      getPricingUrl: () => "https://gaia.test/pricing",
    };

    await priv.handleIncomingMessage(
      "15551234567",
      `${LINK_FIRST_MESSAGE} #${LINK_CODE}`,
      "wamid.001",
    );

    expect(redeemLinkCode).toHaveBeenCalledWith(
      "whatsapp",
      "15551234567",
      LINK_CODE,
      undefined,
      // The prefill is editable, so what they sent is their own opening turn.
      LINK_FIRST_MESSAGE,
    );
    // The API composes the first contact and delivers it on the outbound queue
    // when the link completes, so the bot must not send anything of its own:
    // a bubble from here would arrive alongside the server's and duplicate it.
    expect(mockSendText).not.toHaveBeenCalled();
    // Nor may the stripped text run as a turn — that would answer the user's
    // own prewritten opener a second time.
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("sends nothing of the first contact when the #code fails to redeem", async () => {
    mockMarkRead.mockResolvedValue({});
    const redeemLinkCode = vi
      .fn()
      .mockRejectedValue(new GaiaApiError("expired", 400));
    (adapter as unknown as { gaia: unknown }).gaia = {
      checkAuthStatus: vi.fn().mockResolvedValue({ authenticated: false }),
      redeemLinkCode,
      getFrontendUrl: () => "https://gaia.test",
      getPricingUrl: () => "https://gaia.test/pricing",
    };

    await priv.handleIncomingMessage(
      "15551234567",
      `${LINK_FIRST_MESSAGE} #${LINK_CODE}`,
      "wamid.001",
    );

    // The only thing a refused code may produce is the explanation of why.
    const sent = mockSendText.mock.calls.map((c) => JSON.stringify(c[0]));
    expect(sent).toHaveLength(1);
    expect(sent[0]).toContain("That link has expired");
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("strips a stray #code from an already-linked sender without redeeming", async () => {
    mockMarkRead.mockResolvedValue({});
    const redeemLinkCode = vi.fn();
    (adapter as unknown as { gaia: unknown }).gaia = {
      checkAuthStatus: vi.fn().mockResolvedValue({ authenticated: true }),
      redeemLinkCode,
      getFrontendUrl: () => "https://gaia.test",
      getPricingUrl: () => "https://gaia.test/pricing",
    };

    await priv.handleIncomingMessage(
      "15551234567",
      `remind me tomorrow #${LINK_CODE}`,
      "wamid.001",
    );

    expect(redeemLinkCode).not.toHaveBeenCalled();
    // Nothing was redeemed, so this is the user's own words: a normal turn.
    expect(postAndFollowSpy.mock.calls[0][0]).toMatchObject({
      message: "remind me tomorrow",
    });
  });

  it("leaves a real hashtag alone", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage(
      "15551234567",
      "post this #launch",
      "wamid.001",
    );

    expect(postAndFollowSpy.mock.calls[0][0]).toMatchObject({
      message: "post this #launch",
    });
  });

  it("/gaia hello world posts the message 'hello world'", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage(
      "15551234567",
      "/gaia hello world",
      "wamid.001",
    );

    expectPosted({
      message: "hello world",
      platform: "whatsapp",
      platformUserId: "15551234567",
      channelId: "15551234567",
    });
  });

  it("/gaia with no text sends usage hint and does NOT post", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "/gaia", "wamid.001");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Usage: /gaia <your message>" }),
    );
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("/todo list dispatches 'todo' command with subcommand arg", async () => {
    mockMarkRead.mockResolvedValue({});
    const todoExecute = vi.fn().mockResolvedValue(undefined);
    priv.commands.set("todo", { execute: todoExecute });

    await priv.handleIncomingMessage("15551234567", "/todo list", "wamid.001");

    expect(todoExecute).toHaveBeenCalledWith(
      expect.objectContaining({
        args: expect.objectContaining({ subcommand: "list" }),
        rawText: "list",
      }),
    );
  });

  it("/help dispatches 'help' command with empty args", async () => {
    mockMarkRead.mockResolvedValue({});
    const helpExecute = vi.fn().mockResolvedValue(undefined);
    priv.commands.set("help", { execute: helpExecute });

    await priv.handleIncomingMessage("15551234567", "/help", "wamid.001");

    expect(helpExecute).toHaveBeenCalledWith(
      expect.objectContaining({
        args: {},
      }),
    );
  });

  it("plain text posts the full message text", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage(
      "15551234567",
      "what is the weather?",
      "wamid.001",
    );

    expectPosted({
      message: "what is the weather?",
      platform: "whatsapp",
      platformUserId: "15551234567",
      channelId: "15551234567",
    });
  });

  it("/GAIA hello (uppercase command) still posts (command name is lowercased)", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "/GAIA hello", "wamid.001");

    expectPosted({
      message: "hello",
      platform: "whatsapp",
    });
  });
});

// ---------------------------------------------------------------------------
// postWhatsAppMessage — posts the message and hands postAndFollow the chat
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - postWhatsAppMessage", () => {
  const WA_ID = "15551234567";
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    mockMarkRead.mockResolvedValue({});
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  /** Posts one message answering wamid.in and returns the surface handed to postAndFollow. */
  async function surfaceFor(): Promise<ReturnType<typeof lastSurface>> {
    await priv.postWhatsAppMessage(WA_ID, "hello", "wamid.in");
    return lastSurface();
  }

  it("empty string sends help text and does NOT post", async () => {
    await priv.postWhatsAppMessage(WA_ID, "", "wamid.in");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("Hi! Send me a message"),
      }),
    );
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("whitespace-only string sends help text and does NOT post", async () => {
    await priv.postWhatsAppMessage(WA_ID, "   ", "wamid.in");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("Hi! Send me a message"),
      }),
    );
    expect(postAndFollowSpy).not.toHaveBeenCalled();
  });

  it("posts the request as a DM carrying the inbound wamid, sending nothing itself", async () => {
    await priv.postWhatsAppMessage(WA_ID, "remind me to exercise", "wamid.in");

    expectPosted({
      message: "remind me to exercise",
      platform: "whatsapp",
      platformUserId: WA_ID,
      channelId: WA_ID,
      isDm: true,
      platformMessageId: "wamid.in",
    });
    expect(mockSendText).not.toHaveBeenCalled();
  });

  it("the auth handler sends the shared canonical auth-link message with the URL", async () => {
    await priv.postWhatsAppMessage(WA_ID, "hello", "wamid.in");

    await lastAuthHandler()("https://auth.example.com/link");

    expect(mockSendText).toHaveBeenCalledTimes(1);
    const body = mockSendText.mock.calls[0][0].body as string;
    expect(body).toContain("https://auth.example.com/link");
    // Uses the single shared buildAuthLinkMessage (not a WhatsApp-specific
    // hardcoded string) so /auth and the chat auth-prompt stay identical.
    expect(body).toContain("Link your account to GAIA");
  });

  it("surface.send answers the given message natively through Kapso's contextMessageId", async () => {
    const surface = await surfaceFor();

    await surface.send("on it", "wamid.earlier");

    expect(mockSendText).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      to: `+${WA_ID}`,
      body: "on it",
      previewUrl: false,
      contextMessageId: "wamid.earlier",
    });
  });

  it("surface.send without a reply target sends a plain message", async () => {
    const surface = await surfaceFor();

    await surface.send("here you go", null);

    expect(mockSendText).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      to: `+${WA_ID}`,
      body: "here you go",
      previewUrl: false,
    });
  });

  it("a sent message's edit sends a new message, and it offers no delete", async () => {
    const surface = await surfaceFor();
    const sent = await surface.send("first", "wamid.earlier");

    await sent.edit("second");

    expect(mockSendText).toHaveBeenLastCalledWith({
      phoneNumberId: "test-phone-id",
      to: `+${WA_ID}`,
      body: "second",
      previewUrl: false,
    });
    // WhatsApp has no unsend API, which is why it never streams.
    expect(sent.delete).toBeUndefined();
  });

  it("surface.react reacts in the user's chat", async () => {
    const react = vi
      .spyOn(adapter as unknown as WhatsAppReactor, "reactToMessage")
      .mockResolvedValue("attached");
    const surface = await surfaceFor();

    await expect(surface.react("wamid.in", "👍", "🔎")).resolves.toBe(
      "attached",
    );
    expect(react).toHaveBeenCalledWith(WA_ID, "wamid.in", "👍", false, "🔎");
    expect(mockSendText).not.toHaveBeenCalled();
  });

  it("surface.startTyping shows typing against the inbound message until stopped", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    const surface = await surfaceFor();
    const typingOn = {
      phoneNumberId: "test-phone-id",
      messageId: "wamid.in",
      typingIndicator: { type: "text" },
    };

    const stopTyping = surface.startTyping();
    expect(mockMarkRead).toHaveBeenCalledWith(typingOn);
    vi.advanceTimersByTime(TYPING_REFRESH_MS);
    expect(mockMarkRead).toHaveBeenCalledTimes(2);

    stopTyping();
    vi.advanceTimersByTime(TYPING_REFRESH_MS * 3);
    expect(mockMarkRead).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — via BaseBotAdapter stub
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - dispatchCommand (via BaseBotAdapter stub)", () => {
  type DispatchTarget = Parameters<PrivateAdapter["dispatchCommand"]>[1];
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;
  let mockSendEphemeral: ReturnType<typeof vi.fn>;
  let mockTarget: DispatchTarget;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;

    mockSendEphemeral = vi
      .fn()
      .mockResolvedValue({ id: "eph-msg", edit: vi.fn() });
    mockTarget = {
      sendEphemeral:
        mockSendEphemeral as unknown as DispatchTarget["sendEphemeral"],
    };
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("unknown command sends 'Unknown command: /unknown' via target.sendEphemeral", async () => {
    await priv.dispatchCommand("unknown", mockTarget, {}, undefined);

    expect(mockSendEphemeral).toHaveBeenCalledWith("Unknown command: /unknown");
  });

  it("registered command that throws sends the error message via target.sendEphemeral", async () => {
    priv.commands.set("boom", {
      execute: async () => {
        throw new Error("Command exploded");
      },
    });

    await priv.dispatchCommand("boom", mockTarget, {}, undefined);

    expect(mockSendEphemeral).toHaveBeenCalledWith("Error: Command exploded");
  });
});

// ---------------------------------------------------------------------------
// Welcome message — first contact tracking
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - welcome message", () => {
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    mockMarkRead.mockResolvedValue({});
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("sends welcome on first message from a user", async () => {
    await priv.handleIncomingMessage("15551234567", "hello", "wamid.001");

    // First call should be the welcome message
    const allBodies = mockSendText.mock.calls.map((c) => c[0].body as string);
    expect(allBodies.some((b) => b.includes("Hey, I'm GAIA"))).toBe(true);
  });

  it("does NOT send welcome on second message from the same user", async () => {
    await priv.handleIncomingMessage("15551234567", "hello", "wamid.001");
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-456" }] });
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "again", "wamid.002");

    const allBodies = mockSendText.mock.calls.map((c) => c[0].body as string);
    expect(allBodies.some((b) => b.includes("Hey, I'm GAIA"))).toBe(false);
  });

  it("sends welcome to different users independently", async () => {
    await priv.handleIncomingMessage("15551234567", "hello", "wamid.001");
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-789" }] });
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("14441234567", "hi", "wamid.003");

    const allBodies = mockSendText.mock.calls.map((c) => c[0].body as string);
    expect(allBodies.some((b) => b.includes("Hey, I'm GAIA"))).toBe(true);
  });

  it("welcome message includes key sections (Chat, Todos, Workflows, Link)", async () => {
    await priv.sendWelcome("15551234567");

    const body = mockSendText.mock.calls[0][0].body as string;
    expect(body).toContain("Chat");
    expect(body).toContain("Todos");
    expect(body).toContain("Workflows");
    expect(body).toContain("Link your account");
    expect(body).toContain("/auth");
    expect(body).toContain("heygaia.io");
  });

  it("welcome failure does not throw (silent catch)", async () => {
    mockSendText.mockRejectedValueOnce(new Error("Network error"));

    await expect(priv.sendWelcome("15551234567")).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// reactToMessage — the native reaction primitive the surface reacts through
// ---------------------------------------------------------------------------

type WhatsAppReactor = {
  reactToMessage: (
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
    replaces: string | null,
  ) => Promise<ReactionOutcome>;
};

describe("WhatsAppAdapter - reactToMessage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("attaches via sendReaction with the Kapso addressing", async () => {
    mockSendReaction.mockResolvedValue({ messages: [{ id: "r1" }] });
    const adapter = makeAdapter() as unknown as WhatsAppReactor;

    const attached = await adapter.reactToMessage(
      "15551234567",
      "wamid.123",
      "👍",
      false,
      null,
    );

    expect(attached).toBe("attached");
    expect(mockSendReaction).toHaveBeenCalledWith({
      phoneNumberId: "test-phone-id",
      to: "+15551234567",
      reaction: { messageId: "wamid.123", emoji: "👍" },
    });
    expect(mockSendText).not.toHaveBeenCalled();
  });

  it("refuses without sending text when Kapso rejects the reaction", async () => {
    mockSendReaction.mockRejectedValueOnce(new Error("too old to react"));
    const adapter = makeAdapter() as unknown as WhatsAppReactor;

    const attached = await adapter.reactToMessage(
      "15551234567",
      "wamid.123",
      "👍",
      false,
      null,
    );

    expect(attached).toBe("attach_failed");
    expect(mockSendText).not.toHaveBeenCalled();
  });
});

describe("WhatsAppAdapter - inbound order", () => {
  const WA_ID = "15551234567";

  function textEvent(id: string, body: string) {
    return {
      message: {
        id,
        type: "text",
        text: { body },
        timestamp: String(Math.floor(Date.now() / 1000)),
      },
      conversation: { phone_number: `+${WA_ID}` },
    };
  }

  afterEach(() => {
    vi.useRealTimers();
  });

  /** An adapter whose first welcome auth check hangs until releaseFirst() — the interleaving that reordered posts. */
  async function heldInWelcome() {
    vi.clearAllMocks();
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    mockMarkRead.mockResolvedValue({});
    const webhook = await import("../../whatsapp/src/webhook");
    vi.mocked(webhook.extractWaId).mockReturnValue(WA_ID);
    vi.mocked(webhook.extractTextBody).mockImplementation(
      (event) => event.message.text?.body ?? null,
    );
    let releaseFirst = (): void => undefined;
    const checkAuthStatus = vi.fn().mockReturnValueOnce(
      new Promise((resolve) => {
        releaseFirst = () => resolve({ authenticated: true });
      }),
    );
    const adapter = makeAdapter();
    (adapter as unknown as { gaia: unknown }).gaia = {
      checkAuthStatus,
      getPricingUrl: () => "https://gaia.test/pricing",
    };
    const priv = adapter as unknown as PrivateAdapter & {
      handleWebhookEvent: (event: unknown) => void;
    };
    return { priv, checkAuthStatus, releaseFirst: () => releaseFirst() };
  }

  it("posts a sender's messages in arrival order when the first is held in its welcome check", async () => {
    const { priv, checkAuthStatus, releaseFirst } = await heldInWelcome();

    priv.handleWebhookEvent(textEvent("m0", "do the work"));
    await vi.waitFor(() => expect(checkAuthStatus).toHaveBeenCalledTimes(1));
    priv.handleWebhookEvent(textEvent("m1", "and then"));
    await new Promise((resolve) => setImmediate(resolve));

    // The second message is ready first, but its post waits for the first's.
    expect(postAndFollowSpy).not.toHaveBeenCalled();

    releaseFirst();
    await vi.waitFor(() =>
      expect(postAndFollowSpy.mock.calls.map(([req]) => req.message)).toEqual([
        "do the work",
        "and then",
      ]),
    );
  });

  it("dispatches a /stop behind a held message without waiting for it", async () => {
    const { priv, checkAuthStatus, releaseFirst } = await heldInWelcome();
    const stopExecute = vi.fn().mockResolvedValue(undefined);
    priv.commands.set("stop", { execute: stopExecute });

    priv.handleWebhookEvent(textEvent("m0", "do the work"));
    await vi.waitFor(() => expect(checkAuthStatus).toHaveBeenCalledTimes(1));
    priv.handleWebhookEvent(textEvent("m1", "/stop"));

    await vi.waitFor(() => expect(stopExecute).toHaveBeenCalledTimes(1));
    expect(postAndFollowSpy).not.toHaveBeenCalled();

    releaseFirst();
    await vi.waitFor(() => expect(postAndFollowSpy).toHaveBeenCalledTimes(1));
  });
});
