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
 * 9.  createWaTarget.sendRich — calls richMessageToMarkdown then convertToWhatsAppMarkdown then sendText
 * 10. createWaTarget.startTyping — returns a callable no-op
 * 11. handleIncomingMessage — /gaia <text> routes to handleStreamingMessage
 * 12. handleIncomingMessage — /gaia (no text) sends usage hint, no streaming
 * 13. handleIncomingMessage — /todo <args> dispatches todo command
 * 14. handleIncomingMessage — /help dispatches help command
 * 15. handleIncomingMessage — plain text routes to handleStreamingMessage
 * 16. handleIncomingMessage — /GAIA hello (uppercase) still routes to streaming
 * 17. handleStreamingMessage — empty string sends help text, no streaming
 * 18. handleStreamingMessage — whitespace-only string sends help text
 * 19. handleStreamingMessage — normal text sends "Thinking..." first
 * 20. handleStreamingMessage — calls handleStreamingChat with correct shape
 * 21. handleStreamingMessage — onAuthError callback sends link message
 * 22. handleStreamingMessage — onGenericError callback sends error via sendText
 * 23. handleStreamingMessage — sendNewMessage callback sends new message
 * 24. handleStreamingMessage — thinking message failure returns early
 * 25. handleStreamingMessage — handleStreamingChat throw edits thinkingMsg
 * 26. dispatchCommand — unknown command sends ephemeral error
 * 27. dispatchCommand — registered command that throws sends ephemeral error
 * 28. handleIncomingMessage — sends welcome on first contact, not on second
 * 29. handleIncomingMessage — welcome sent per user (different users each get one)
 * 30. handleUnsupportedMedia — replies with helpful message for image
 * 31. handleUnsupportedMedia — replies with type-specific label for audio/voice/video/document
 * 32. createWaTarget.sendRich — applies convertToWhatsAppMarkdown to rendered markdown
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock @kapso/whatsapp-cloud-api before importing the adapter.
// ---------------------------------------------------------------------------

const mockSendText = vi.fn();
const mockMarkRead = vi.fn();
const mockWaClientInstance = {
  messages: {
    sendText: mockSendText,
    markRead: mockMarkRead,
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

// ---------------------------------------------------------------------------
// Mock ./webhook before importing the adapter.
// vi.mock factories are hoisted by Vitest, so we cannot reference module-level
// variables inside them. Instead, we use vi.fn() inline and retrieve the mocks
// after import via vi.mocked().
// ---------------------------------------------------------------------------

vi.mock("../../whatsapp/src/webhook", () => ({
  verifyKapsoSignature: vi.fn(),
  extractWaId: vi.fn(),
  extractTextBody: vi.fn(),
  KapsoMessageEvent: undefined,
}));

// ---------------------------------------------------------------------------
// Mock @gaia/shared — BaseBotAdapter stub + shared helpers.
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared", async () => {
  const { makeGaiaSharedMock } = await import("../shared/mocks/gaiaSharedBase");
  return makeGaiaSharedMock("whatsapp", {
    streamingDefaults: {
      whatsapp: {
        editIntervalMs: 2000,
        streaming: false,
        platform: "whatsapp",
      },
    },
    converters: {
      convertToWhatsAppMarkdown: vi.fn((text: string) => text),
    },
    defaultRichMarkdown: "*GAIA Help*\nUse /gaia to chat",
  });
});

// ---------------------------------------------------------------------------
// Now import the real adapter (which will use the mocks above).
// ---------------------------------------------------------------------------

import {
  convertToWhatsAppMarkdown,
  handleStreamingChat,
  richMessageToMarkdown,
} from "@gaia/shared";
import { WhatsAppAdapter } from "../../whatsapp/src/adapter";

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
  handleStreamingMessage: (waId: string, text: string) => Promise<void>;
  handleUnsupportedMedia: (waId: string, messageType: string) => Promise<void>;
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

  it("target.sendRich calls richMessageToMarkdown then convertToWhatsAppMarkdown then sends the result", async () => {
    const target = priv.createWaTarget("15551234567");
    const richMsg = { title: "GAIA Help", sections: [] };

    vi.mocked(richMessageToMarkdown).mockReturnValue(
      "*GAIA Help*\n**Name:** Aryan",
    );
    vi.mocked(convertToWhatsAppMarkdown).mockReturnValue(
      "*GAIA Help*\n*Name:* Aryan",
    );

    await target.sendRich(richMsg);

    expect(richMessageToMarkdown).toHaveBeenCalledWith(richMsg, "whatsapp");
    expect(convertToWhatsAppMarkdown).toHaveBeenCalledWith(
      "*GAIA Help*\n**Name:** Aryan",
    );
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

  it("/gaia hello world routes to handleStreamingChat with message 'hello world'", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage(
      "15551234567",
      "/gaia hello world",
      "wamid.001",
    );

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "hello world",
        platform: "whatsapp",
        platformUserId: "15551234567",
        channelId: "15551234567",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "whatsapp" }),
      undefined,
    );
  });

  it("/gaia with no text sends usage hint and does NOT call handleStreamingChat", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "/gaia", "wamid.001");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Usage: /gaia <your message>" }),
    );
    expect(handleStreamingChat).not.toHaveBeenCalled();
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

  it("plain text routes to handleStreamingChat with the full message text", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage(
      "15551234567",
      "what is the weather?",
      "wamid.001",
    );

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "what is the weather?",
        platform: "whatsapp",
        platformUserId: "15551234567",
        channelId: "15551234567",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "whatsapp" }),
      undefined,
    );
  });

  it("/GAIA hello (uppercase command) still routes to streaming (command name is lowercased)", async () => {
    mockMarkRead.mockResolvedValue({});

    await priv.handleIncomingMessage("15551234567", "/GAIA hello", "wamid.001");

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "hello",
        platform: "whatsapp",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.anything(),
      undefined,
    );
  });
});

// ---------------------------------------------------------------------------
// handleStreamingMessage — private method
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - handleStreamingMessage", () => {
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

  it("empty string sends help text and does NOT call handleStreamingChat", async () => {
    await priv.handleStreamingMessage("15551234567", "");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("Hi! Send me a message"),
      }),
    );
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("whitespace-only string sends help text and does NOT call handleStreamingChat", async () => {
    await priv.handleStreamingMessage("15551234567", "   ");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("Hi! Send me a message"),
      }),
    );
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("normal text calls handleStreamingChat without sending a placeholder message first", async () => {
    await priv.handleStreamingMessage("15551234567", "plan my week");

    // No "Thinking..." or any placeholder sent before handleStreamingChat
    expect(mockSendText).not.toHaveBeenCalled();
    expect(handleStreamingChat).toHaveBeenCalled();
  });

  it("calls handleStreamingChat with the correct context shape", async () => {
    await priv.handleStreamingMessage("15551234567", "remind me to exercise");

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "remind me to exercise",
        platform: "whatsapp",
        platformUserId: "15551234567",
        channelId: "15551234567",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "whatsapp" }),
      undefined,
    );
  });

  it("onAuthError callback sends 'To use GAIA on WhatsApp, link your account first:' with the auth URL", async () => {
    vi.mocked(handleStreamingChat).mockImplementation(
      async (_gaia, _ctx, _editMsg, _sendNew, onAuthError) => {
        await onAuthError("https://auth.example.com/link");
      },
    );

    await priv.handleStreamingMessage("15551234567", "hello");

    const allCalls = mockSendText.mock.calls.map((c) => c[0].body as string);
    const authMessage = allCalls.find((b) =>
      b.includes("To use GAIA on WhatsApp, link your account first:"),
    );
    expect(authMessage).toBeDefined();
    expect(authMessage).toContain("https://auth.example.com/link");
  });

  it("onGenericError callback sends the error message via sendText", async () => {
    vi.mocked(handleStreamingChat).mockImplementation(
      async (_gaia, _ctx, _editMsg, _sendNew, _onAuth, onGenericError) => {
        await onGenericError("Something went wrong on the backend");
      },
    );

    await priv.handleStreamingMessage("15551234567", "hello");

    const allCalls = mockSendText.mock.calls.map((c) => c[0].body as string);
    expect(allCalls).toContain("Something went wrong on the backend");
  });

  it("sendNewMessage callback sends a new message via sendText and returns an edit function", async () => {
    let capturedSendNew:
      | ((text: string) => Promise<(t: string) => Promise<void>>)
      | undefined;

    vi.mocked(handleStreamingChat).mockImplementation(
      async (_gaia, _ctx, _editMsg, sendNewMessage) => {
        capturedSendNew = sendNewMessage as (
          text: string,
        ) => Promise<(t: string) => Promise<void>>;
      },
    );

    await priv.handleStreamingMessage("15551234567", "hello");

    expect(capturedSendNew).toBeDefined();

    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-new" }] });

    const editFn = await capturedSendNew!("New continuation message");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "New continuation message" }),
    );
    expect(typeof editFn).toBe("function");
  });

  it("when handleStreamingChat throws, sends 'An error occurred. Please try again.' as a new message", async () => {
    vi.mocked(handleStreamingChat).mockRejectedValueOnce(
      new Error("Streaming failure"),
    );

    await priv.handleStreamingMessage("15551234567", "hello");

    const allCalls = mockSendText.mock.calls.map((c) => c[0].body as string);
    expect(allCalls).toContain("An error occurred. Please try again.");
  });

  it("editMessage callback sends a new message on the first call (no placeholder to edit)", async () => {
    let capturedEditMsg: ((text: string) => Promise<void>) | undefined;

    vi.mocked(handleStreamingChat).mockImplementation(
      async (_gaia, _ctx, editMessage) => {
        capturedEditMsg = editMessage as (text: string) => Promise<void>;
      },
    );

    await priv.handleStreamingMessage("15551234567", "hello");

    expect(capturedEditMsg).toBeDefined();

    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-reply" }] });

    await capturedEditMsg!("Here is the response");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({ body: "Here is the response" }),
    );
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — via BaseBotAdapter stub
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - dispatchCommand (via BaseBotAdapter stub)", () => {
  let adapter: WhatsAppAdapter;
  let priv: PrivateAdapter;
  let mockSendEphemeral: ReturnType<typeof vi.fn>;
  let mockTarget: { sendEphemeral: typeof mockSendEphemeral };

  beforeEach(() => {
    vi.clearAllMocks();
    mockSendText.mockResolvedValue({ messages: [{ id: "wa-msg-123" }] });
    adapter = makeAdapter();
    priv = adapter as unknown as PrivateAdapter;

    mockSendEphemeral = vi
      .fn()
      .mockResolvedValue({ id: "eph-msg", edit: vi.fn() });
    mockTarget = { sendEphemeral: mockSendEphemeral };
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
// handleUnsupportedMedia — non-text message handling
// ---------------------------------------------------------------------------

describe("WhatsAppAdapter - handleUnsupportedMedia", () => {
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

  it('replies with "images" for image messages', async () => {
    await priv.handleUnsupportedMedia("15551234567", "image");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("images"),
      }),
    );
  });

  it('replies with "audio messages" for audio messages', async () => {
    await priv.handleUnsupportedMedia("15551234567", "audio");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("audio messages"),
      }),
    );
  });

  it('replies with "audio messages" for voice messages', async () => {
    await priv.handleUnsupportedMedia("15551234567", "voice");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("audio messages"),
      }),
    );
  });

  it('replies with "videos" for video messages', async () => {
    await priv.handleUnsupportedMedia("15551234567", "video");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("videos"),
      }),
    );
  });

  it('replies with "documents" for document messages', async () => {
    await priv.handleUnsupportedMedia("15551234567", "document");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("documents"),
      }),
    );
  });

  it("replies with generic label for unknown message types", async () => {
    await priv.handleUnsupportedMedia("15551234567", "sticker");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("sticker messages"),
      }),
    );
  });

  it("includes help hint in all media responses", async () => {
    await priv.handleUnsupportedMedia("15551234567", "image");

    expect(mockSendText).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.stringContaining("/help"),
      }),
    );
  });
});
